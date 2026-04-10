from dataclasses import dataclass

import cv2
import numpy as np

from app.domain.models.page_bounds import PageAnalysis, Rect


@dataclass(slots=True)
class AnalyzerConfig:
    content_threshold: int
    edge_dark_threshold: int


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
        return PageAnalysis(content, crop, skew)

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
