from dataclasses import dataclass

import cv2
import numpy as np

from app.domain.models.page_bounds import PageAnalysis


@dataclass(slots=True)
class NormalizeConfig:
    deskew: bool
    normalize_margins: bool
    margin_ratio: float
    anchor: str = "center"
    reference_content_size: tuple[int, int] | None = None
    align_to_title_block: bool = True


class PageNormalizer:
    """Applies crop, deskew, and margin normalization on a page image."""

    def normalize(self, bgr: np.ndarray, analysis: PageAnalysis, cfg: NormalizeConfig, target_size: tuple[int, int]) -> np.ndarray:
        x, y, w, h = analysis.crop_rect.x, analysis.crop_rect.y, analysis.crop_rect.w, analysis.crop_rect.h
        cropped = bgr[y:y + h, x:x + w]
        if cfg.deskew and abs(analysis.skew_angle) > 0.2:
            cropped = self._rotate(cropped, -analysis.skew_angle)
        if not cfg.normalize_margins:
            return cropped

        canvas_w, canvas_h = target_size
        margin_x = int(canvas_w * cfg.margin_ratio)
        margin_y = int(canvas_h * cfg.margin_ratio)
        usable_w = max(1, canvas_w - 2 * margin_x)
        usable_h = max(1, canvas_h - 2 * margin_y)
        ref_w, ref_h = cfg.reference_content_size or (cropped.shape[1], cropped.shape[0])
        scale = min(usable_w / max(1, ref_w), usable_h / max(1, ref_h))
        new_w = max(1, int(cropped.shape[1] * scale))
        new_h = max(1, int(cropped.shape[0] * scale))
        resized = cv2.resize(cropped, (new_w, new_h), interpolation=cv2.INTER_AREA)
        canvas = np.full((canvas_h, canvas_w, 3), 255, dtype=np.uint8)
        title_anchor = self._compute_title_block_anchor(
            analysis,
            cfg,
            cropped.shape[1],
            cropped.shape[0],
            new_w,
            new_h,
            canvas_w,
            canvas_h,
            margin_x,
            margin_y,
        )
        if title_anchor is None:
            x0, y0 = self._compute_anchor_position(canvas_w, canvas_h, new_w, new_h, margin_x, margin_y, cfg.anchor)
        else:
            x0, y0 = title_anchor
        canvas[y0:y0 + new_h, x0:x0 + new_w] = resized
        return canvas

    def _rotate(self, img: np.ndarray, angle: float) -> np.ndarray:
        h, w = img.shape[:2]
        center = (w // 2, h // 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(img, matrix, (w, h), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))

    def _compute_anchor_position(
        self,
        canvas_w: int,
        canvas_h: int,
        item_w: int,
        item_h: int,
        margin_x: int,
        margin_y: int,
        anchor: str,
    ) -> tuple[int, int]:
        if anchor == "bottom_right":
            return canvas_w - margin_x - item_w, canvas_h - margin_y - item_h
        if anchor == "top_left":
            return margin_x, margin_y
        return (canvas_w - item_w) // 2, (canvas_h - item_h) // 2

    def _compute_title_block_anchor(
        self,
        analysis: PageAnalysis,
        cfg: NormalizeConfig,
        cropped_w: int,
        cropped_h: int,
        resized_w: int,
        resized_h: int,
        canvas_w: int,
        canvas_h: int,
        margin_x: int,
        margin_y: int,
    ) -> tuple[int, int] | None:
        if not cfg.align_to_title_block or analysis.title_block_rect is None:
            return None

        tb = analysis.title_block_rect
        rel_x = max(0, tb.x - analysis.crop_rect.x)
        rel_y = max(0, tb.y - analysis.crop_rect.y)
        scale_x = resized_w / max(cropped_w, 1)
        scale_y = resized_h / max(cropped_h, 1)
        tb_x = int(rel_x * scale_x)
        tb_y = int(rel_y * scale_y)
        tb_w = max(1, int(tb.w * scale_x))
        tb_h = max(1, int(tb.h * scale_y))

        target_x, target_y = self._target_anchor_point(canvas_w, canvas_h, margin_x, margin_y, cfg.anchor)
        x0 = target_x - (tb_x + tb_w)
        y0 = target_y - (tb_y + tb_h)
        return self._clamp_to_canvas(x0, y0, resized_w, resized_h, canvas_w, canvas_h)

    def _target_anchor_point(self, canvas_w: int, canvas_h: int, margin_x: int, margin_y: int, anchor: str) -> tuple[int, int]:
        if anchor == "top_left":
            return margin_x, margin_y
        if anchor == "center":
            return canvas_w // 2, canvas_h // 2
        return canvas_w - margin_x, canvas_h - margin_y

    def _clamp_to_canvas(
        self,
        x0: int,
        y0: int,
        item_w: int,
        item_h: int,
        canvas_w: int,
        canvas_h: int,
    ) -> tuple[int, int]:
        max_x = max(0, canvas_w - item_w)
        max_y = max(0, canvas_h - item_h)
        return min(max(0, x0), max_x), min(max(0, y0), max_y)
