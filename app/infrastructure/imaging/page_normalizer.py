from dataclasses import dataclass

import cv2
import numpy as np

from app.domain.models.page_bounds import PageAnalysis


@dataclass(slots=True)
class NormalizeConfig:
    deskew: bool
    normalize_margins: bool
    margin_ratio: float


class PageNormalizer:
    """Applies crop, deskew, and margin normalization on a page image."""

    def normalize(self, bgr: np.ndarray, analysis: PageAnalysis, cfg: NormalizeConfig, target_size: tuple[int, int]) -> np.ndarray:
        x, y, w, h = analysis.crop_rect.x, analysis.crop_rect.y, analysis.crop_rect.w, analysis.crop_rect.h
        cropped = bgr[y:y + h, x:x + w]
        if cfg.deskew and abs(analysis.skew_angle) > 0.2:
            cropped = self._rotate(cropped, analysis.skew_angle)
        if not cfg.normalize_margins:
            return cv2.resize(cropped, target_size, interpolation=cv2.INTER_AREA)

        canvas_w, canvas_h = target_size
        margin_x = int(canvas_w * cfg.margin_ratio)
        margin_y = int(canvas_h * cfg.margin_ratio)
        usable_w = max(1, canvas_w - 2 * margin_x)
        usable_h = max(1, canvas_h - 2 * margin_y)
        scale = min(usable_w / max(1, cropped.shape[1]), usable_h / max(1, cropped.shape[0]))
        new_w = max(1, int(cropped.shape[1] * scale))
        new_h = max(1, int(cropped.shape[0] * scale))
        resized = cv2.resize(cropped, (new_w, new_h), interpolation=cv2.INTER_AREA)
        canvas = np.full((canvas_h, canvas_w, 3), 255, dtype=np.uint8)
        x0 = (canvas_w - new_w) // 2
        y0 = (canvas_h - new_h) // 2
        canvas[y0:y0 + new_h, x0:x0 + new_w] = resized
        return canvas

    def _rotate(self, img: np.ndarray, angle: float) -> np.ndarray:
        h, w = img.shape[:2]
        center = (w // 2, h // 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(img, matrix, (w, h), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))
