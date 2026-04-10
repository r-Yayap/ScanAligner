import cv2

from app.config.settings import ProcessingSettings
from app.infrastructure.imaging.page_analyzer import AnalyzerConfig, PageAnalyzer
from app.infrastructure.imaging.page_normalizer import NormalizeConfig, PageNormalizer
from app.infrastructure.pdf.pdf_reader import PdfPageRenderer


class PreviewService:
    def __init__(self, renderer: PdfPageRenderer, analyzer: PageAnalyzer, normalizer: PageNormalizer) -> None:
        self._renderer = renderer
        self._analyzer = analyzer
        self._normalizer = normalizer

    def preview_page(self, pdf_path, page_index: int, settings: ProcessingSettings):
        doc = self._renderer.open_document(pdf_path)
        try:
            page = doc.load_page(page_index)
            original = self._renderer.render_page_rgb(page, settings.render_dpi)
            analysis = self._analyzer.analyze(
                original,
                AnalyzerConfig(settings.content_threshold, settings.edge_dark_threshold, settings.detect_title_block),
            )
            processed = self._normalizer.normalize(
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
            overlay_original = original.copy()
            if settings.show_title_block_overlay and analysis.title_block_rect:
                tb = analysis.title_block_rect
                cv2.rectangle(overlay_original, (tb.x, tb.y), (tb.x + tb.w, tb.y + tb.h), (0, 200, 0), 3)
            return overlay_original, processed, doc.page_count
        finally:
            doc.close()
