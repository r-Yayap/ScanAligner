from dataclasses import dataclass

import cv2
import numpy as np

from app.domain.models.page_bounds import PageAnalysis, Rect


@dataclass(slots=True)
class AnalyzerConfig:
    content_threshold: int
    edge_dark_threshold: int
    detect_title_block: bool = True
    manual_title_block_rect: Rect | None = None


class PageAnalyzer:
    """Detects content bounds, crop area, and skew angle."""

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
        angles = []
        for l in lines[:, 0]:
            x1, y1, x2, y2 = l
            angle = np.degrees(np.arctan2((y2 - y1), (x2 - x1)))
            if -30 < angle < 30:
                angles.append(angle)
        return float(np.median(angles)) if angles else 0.0

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
