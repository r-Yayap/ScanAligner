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
            analysis = self._analyzer.analyze(original, AnalyzerConfig(settings.content_threshold, settings.edge_dark_threshold))
            processed = self._normalizer.normalize(
                original,
                analysis,
                NormalizeConfig(settings.deskew, settings.normalize_margins, settings.margin_ratio),
                target_size=(original.shape[1], original.shape[0]),
            )
            return original, processed, doc.page_count
        finally:
            doc.close()
