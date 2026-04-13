from dataclasses import dataclass
import hashlib

import cv2
import numpy as np

from app.domain.models.page_bounds import PageAnalysis, Rect
from app.infrastructure.imaging.title_block_template_aligner import (
    create_detector,
    knn_ratio_match,
    preprocess_for_features,
)


@dataclass(slots=True)
class AnalyzerConfig:
    content_threshold: int
    edge_dark_threshold: int
    detect_title_block: bool = True
    manual_title_block_rect: Rect | None = None
    title_block_template: np.ndarray | None = None
    template_search_region_ratio: float = 0.55
    template_min_good_matches: int = 20
    template_max_features: int = 2200


class PageAnalyzer:
    """Detects content bounds, crop area, and skew angle."""
    def __init__(self) -> None:
        self._template_cache_key: str | None = None
        self._template_cache_gray: np.ndarray | None = None
        self._template_cache_keypoints = None
        self._template_cache_descriptors = None

    def analyze(self, bgr: np.ndarray, cfg: AnalyzerConfig) -> PageAnalysis:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        inv = cv2.threshold(gray, cfg.content_threshold, 255, cv2.THRESH_BINARY_INV)[1]
        pts = cv2.findNonZero(inv)
        if pts is None:
            h, w = gray.shape
            rect = Rect(0, 0, w, h)
            return PageAnalysis(rect, rect, 0.0)
        x, y, w, h = cv2.boundingRect(pts)
        content = Rect(x, y, w, h)
        crop = self._trim_dark_edges(gray, content, cfg.edge_dark_threshold)
        skew = self._estimate_skew(inv)
        title_block = cfg.manual_title_block_rect
        if title_block is None and cfg.detect_title_block:
            title_block = self._detect_title_block_from_template(gray, crop, cfg.title_block_template, cfg)
            if title_block is None:
                title_block = self._detect_title_block(gray, crop)

        return PageAnalysis(content, crop, skew, title_block)

    def _trim_dark_edges(self, gray: np.ndarray, content: Rect, dark_threshold: int) -> Rect:
        h, w = gray.shape
        margin_x = max(5, int(w * 0.01))
        margin_y = max(5, int(h * 0.01))
        x0 = max(0, content.x - margin_x)
        y0 = max(0, content.y - margin_y)
        x1 = min(w, content.x + content.w + margin_x)
        y1 = min(h, content.y + content.h + margin_y)
        roi = gray[y0:y1, x0:x1]
        mask = roi > dark_threshold
        ys, xs = np.where(mask)
        if len(xs) == 0:
            return content
        return Rect(x0 + int(xs.min()), y0 + int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))

    def _estimate_skew(self, inv_binary: np.ndarray) -> float:
        lines = cv2.HoughLinesP(inv_binary, 1, np.pi / 180, threshold=100, minLineLength=120, maxLineGap=10)
        if lines is None:
            return 0.0

        weighted_angles: list[tuple[float, float]] = []
        for l in lines[:, 0]:
            x1, y1, x2, y2 = l
            angle = np.degrees(np.arctan2((y2 - y1), (x2 - x1)))
            if not (-15.0 < angle < 15.0):
                continue
            length = float(np.hypot(x2 - x1, y2 - y1))
            if length < 80:
                continue
            weighted_angles.append((angle, length))

        if len(weighted_angles) < 8:
            return 0.0

        angles = np.array([a for a, _ in weighted_angles], dtype=np.float32)
        lengths = np.array([w for _, w in weighted_angles], dtype=np.float32)
        median = float(np.median(angles))
        mad = float(np.median(np.abs(angles - median)))
        tolerance = max(1.2, mad * 2.5)
        inlier_mask = np.abs(angles - median) <= tolerance
        if int(np.count_nonzero(inlier_mask)) < 6:
            return 0.0

        inlier_angles = angles[inlier_mask]
        inlier_lengths = lengths[inlier_mask]
        weighted_mean = float(np.average(inlier_angles, weights=inlier_lengths))
        return weighted_mean if abs(weighted_mean) >= 0.2 else 0.0

    def _detect_title_block(self, gray: np.ndarray, crop: Rect) -> Rect | None:
        """Detect a title block by finding strong rectangular structure at bottom-right."""
        page_roi = gray[crop.y:crop.y + crop.h, crop.x:crop.x + crop.w]
        if page_roi.size == 0:
            return None

        roi_h, roi_w = page_roi.shape
        sx = max(0, int(roi_w * 0.55))
        sy = max(0, int(roi_h * 0.55))
        focus = page_roi[sy:, sx:]
        if focus.size == 0:
            return None

        blur = cv2.GaussianBlur(focus, (3, 3), 0)
        binary = cv2.threshold(blur, 220, 255, cv2.THRESH_BINARY_INV)[1]
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        best = None
        best_score = -1.0
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < focus.shape[1] * focus.shape[0] * 0.02:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            if w < 50 or h < 25:
                continue
            aspect = w / max(h, 1)
            if not (1.5 <= aspect <= 8.0):
                continue
            fill_ratio = area / max(w * h, 1)
            if fill_ratio < 0.45:
                continue

            global_x = sx + x
            global_y = sy + y
            cx = global_x + (w / 2)
            cy = global_y + (h / 2)
            br_bias = (cx / max(roi_w, 1)) + (cy / max(roi_h, 1))

            edge_patch = binary[max(y - 2, 0):min(y + h + 2, binary.shape[0]), max(x - 2, 0):min(x + w + 2, binary.shape[1])]
            edge_density = float(np.count_nonzero(edge_patch)) / max(edge_patch.size, 1)
            score = (area * br_bias) * (0.6 + edge_density)
            if score > best_score:
                best_score = score
                best = Rect(crop.x + global_x, crop.y + global_y, w, h)
        return best

    def _detect_title_block_from_template(
        self,
        gray: np.ndarray,
        crop: Rect,
        template_bgr: np.ndarray | None,
        cfg: AnalyzerConfig,
    ) -> Rect | None:
        if template_bgr is None:
            return None

        roi = gray[crop.y:crop.y + crop.h, crop.x:crop.x + crop.w]
        if roi.size == 0:
            return None

        template_gray = preprocess_for_features(template_bgr)
        template_key = self._template_signature(template_gray)
        roi_bgr = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
        roi_gray = preprocess_for_features(roi_bgr)

        detector, matcher, _ = create_detector(prefer_sift=True, nfeatures=cfg.template_max_features)
        kp_t, des_t = self._template_features(detector, template_key, template_gray)
        search_ratio = min(0.9, max(0.1, cfg.template_search_region_ratio))
        roi_h, roi_w = roi_gray.shape
        sx = int(roi_w * search_ratio)
        sy = int(roi_h * search_ratio)
        focused_roi = roi_gray[sy:, sx:]
        if focused_roi.size == 0:
            return None
        kp_r, des_r = detector.detectAndCompute(focused_roi, None)
        if des_t is None or des_r is None:
            return None

        good = knn_ratio_match(des_t, des_r, matcher, ratio=0.75)
        if len(good) < cfg.template_min_good_matches:
            return None

        src_pts = np.float32([kp_t[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst_pts = np.float32([(kp_r[m.trainIdx].pt[0] + sx, kp_r[m.trainIdx].pt[1] + sy) for m in good]).reshape(-1, 1, 2)
        homography, inlier_mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 4.0)
        if homography is None:
            return None

        inliers = int(inlier_mask.sum()) if inlier_mask is not None else 0
        if inliers < max(10, int(0.25 * len(good))):
            return None

        h_t, w_t = template_gray.shape[:2]
        corners = np.float32([[0, 0], [w_t - 1, 0], [w_t - 1, h_t - 1], [0, h_t - 1]]).reshape(-1, 1, 2)
        projected = cv2.perspectiveTransform(corners, homography).reshape(-1, 2)
        if not cv2.isContourConvex(np.int32(projected)):
            return None
        x, y, w, h = cv2.boundingRect(np.int32(projected))
        if w <= 0 or h <= 0:
            return None
        roi_area = max(1, roi_w * roi_h)
        rect_area = w * h
        area_ratio = rect_area / roi_area
        if not (0.002 <= area_ratio <= 0.25):
            return None
        return Rect(crop.x + x, crop.y + y, w, h)

    def _template_signature(self, gray: np.ndarray) -> str:
        return hashlib.md5(gray.tobytes()).hexdigest()

    def _template_features(self, detector, key: str, template_gray: np.ndarray):
        if self._template_cache_key == key and self._template_cache_descriptors is not None:
            return self._template_cache_keypoints, self._template_cache_descriptors
        kp_t, des_t = detector.detectAndCompute(template_gray, None)
        self._template_cache_key = key
        self._template_cache_gray = template_gray
        self._template_cache_keypoints = kp_t
        self._template_cache_descriptors = des_t
        return kp_t, des_t
