import cv2
import numpy as np

from app.config.settings import ProcessingSettings
from app.domain.models.page_bounds import Rect
from app.infrastructure.imaging.page_analyzer import AnalyzerConfig, PageAnalyzer
from app.infrastructure.imaging.page_normalizer import NormalizeConfig, PageNormalizer
from app.infrastructure.pdf.pdf_reader import PdfPageRenderer


class PreviewService:
    def __init__(self, renderer: PdfPageRenderer, analyzer: PageAnalyzer, normalizer: PageNormalizer) -> None:
        self._renderer = renderer
        self._analyzer = analyzer
        self._normalizer = normalizer

    def preview_page(
        self,
        pdf_path,
        page_index: int,
        settings: ProcessingSettings,
        include_processed: bool = False,
        preview_mode: str = "processed",
    ):
        doc = self._renderer.open_document(pdf_path)
        try:
            safe_index = max(0, min(page_index, max(0, doc.page_count - 1)))
            page = doc.load_page(safe_index)
            original = self._renderer.render_page_rgb(page, settings.render_dpi)
            if not include_processed:
                return original, None, doc.page_count
            manual_rect = self._manual_title_block_rect(original.shape[1], original.shape[0], settings)
            template = self._load_title_block_template(settings, original, manual_rect)
            analysis = self._analyzer.analyze(
                original,
                AnalyzerConfig(
                    settings.content_threshold,
                    settings.edge_dark_threshold,
                    settings.detect_title_block,
                    manual_rect,
                    template,
                    settings.template_search_region_ratio,
                    settings.template_min_good_matches,
                    settings.template_max_features,
                ),
            )
            overlay_original = original.copy()
            if settings.show_title_block_overlay and analysis.title_block_rect:
                tb = analysis.title_block_rect
                cv2.rectangle(overlay_original, (tb.x, tb.y), (tb.x + tb.w, tb.y + tb.h), (0, 200, 0), 3)
            processed = self._build_preview(
                preview_mode=preview_mode,
                original=original,
                analysis=analysis,
                template=template,
                settings=settings,
            )
            return overlay_original, processed, doc.page_count
        finally:
            doc.close()

    def _build_preview(self, preview_mode: str, original, analysis, template, settings: ProcessingSettings):
        if preview_mode == "template_vs_detected":
            return self._build_template_comparison(original, template, analysis.title_block_rect)
        if preview_mode == "template_search_region":
            return self._build_search_region_overlay(original, analysis.crop_rect, settings.template_search_region_ratio)
        return self._normalizer.normalize(
            original,
            analysis,
            NormalizeConfig(
                settings.deskew,
                settings.normalize_margins,
                settings.margin_ratio,
                settings.content_anchor,
                None,
                settings.detect_title_block,
            ),
            target_size=(original.shape[1], original.shape[0]),
        )

    def _build_template_comparison(self, original, template, detected_rect):
        frame_height = max(220, int(original.shape[0] * 0.35))
        frame_width = max(380, int(original.shape[1] * 0.35))
        left = self._fit_with_caption(template, (frame_width, frame_height), "Selected template")
        detected = None
        if detected_rect is not None:
            detected = original[
                detected_rect.y:detected_rect.y + detected_rect.h,
                detected_rect.x:detected_rect.x + detected_rect.w,
            ].copy()
        right = self._fit_with_caption(detected, (frame_width, frame_height), "Detected object")
        return cv2.hconcat([left, right])

    def _build_search_region_overlay(self, original, crop_rect: Rect, ratio: float):
        overlay = original.copy()
        sx = crop_rect.x + int(crop_rect.w * max(0.1, min(0.9, ratio)))
        sy = crop_rect.y + int(crop_rect.h * max(0.1, min(0.9, ratio)))
        cv2.rectangle(overlay, (crop_rect.x, crop_rect.y), (crop_rect.x + crop_rect.w, crop_rect.y + crop_rect.h), (255, 200, 0), 2)
        cv2.rectangle(overlay, (sx, sy), (crop_rect.x + crop_rect.w, crop_rect.y + crop_rect.h), (255, 0, 180), 3)
        cv2.putText(overlay, "Template search focus", (sx + 12, min(overlay.shape[0] - 12, sy + 28)), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 0, 180), 2, cv2.LINE_AA)
        return overlay

    def _fit_with_caption(self, image, frame_size: tuple[int, int], caption: str):
        frame_w, frame_h = frame_size
        canvas = np.full((frame_h, frame_w, 3), 255, dtype=np.uint8)
        content_h = frame_h - 36
        if image is not None and image.size > 0:
            scale = min(frame_w / max(1, image.shape[1]), content_h / max(1, image.shape[0]))
            resized = cv2.resize(image, (max(1, int(image.shape[1] * scale)), max(1, int(image.shape[0] * scale))), interpolation=cv2.INTER_AREA)
            x = (frame_w - resized.shape[1]) // 2
            y = max(2, (content_h - resized.shape[0]) // 2)
            canvas[y:y + resized.shape[0], x:x + resized.shape[1]] = resized
        else:
            cv2.putText(canvas, "Not available", (20, content_h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (60, 60, 60), 2, cv2.LINE_AA)
        cv2.putText(canvas, caption, (12, frame_h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (25, 25, 25), 2, cv2.LINE_AA)
        return canvas

    def _manual_title_block_rect(self, width: int, height: int, settings: ProcessingSettings) -> Rect | None:
        if not settings.manual_title_block_enabled or settings.manual_title_block_rect is None:
            return None
        x, y, w, h = settings.manual_title_block_rect
        x = max(0, min(x, width - 1))
        y = max(0, min(y, height - 1))
        w = max(1, min(w, width - x))
        h = max(1, min(h, height - y))
        return Rect(x, y, w, h)

    def _load_title_block_template(self, settings: ProcessingSettings, original, manual_rect: Rect | None):
        if settings.title_block_template_path is not None:
            template = self._load_template_file(settings.title_block_template_path)
            if template is not None:
                return template
        if settings.derive_template_from_selection and manual_rect is not None:
            return original[manual_rect.y:manual_rect.y + manual_rect.h, manual_rect.x:manual_rect.x + manual_rect.w].copy()
        return None

    def _load_template_file(self, path):
        if path.suffix.lower() == ".pdf":
            doc = self._renderer.open_document(path)
            try:
                if doc.page_count == 0:
                    return None
                first_page = doc.load_page(0)
                return self._renderer.render_page_rgb(first_page, 200)
            finally:
                doc.close()
        return cv2.imread(str(path))
