from collections import Counter
from pathlib import Path
from typing import Callable

from app.application.dto.progress import ProgressUpdate
from app.config.settings import ProcessingSettings
from app.domain.enums.page_size_mode import PageSizeMode
from app.domain.models.document_task import DocumentTask
from app.infrastructure.imaging.page_analyzer import AnalyzerConfig, PageAnalyzer
from app.infrastructure.imaging.page_normalizer import NormalizeConfig, PageNormalizer
from app.infrastructure.pdf.pdf_reader import PdfPageRenderer
from app.infrastructure.pdf.pdf_writer import PdfWriter


class ProcessDocumentsUseCase:
    def __init__(self, renderer: PdfPageRenderer, analyzer: PageAnalyzer, normalizer: PageNormalizer, writer: PdfWriter) -> None:
        self._renderer = renderer
        self._analyzer = analyzer
        self._normalizer = normalizer
        self._writer = writer

    def execute(
        self,
        tasks: list[DocumentTask],
        settings: ProcessingSettings,
        on_progress: Callable[[ProgressUpdate], None],
        cancel_requested: Callable[[], bool],
    ) -> tuple[int, int]:
        processed = 0
        for file_idx, task in enumerate(tasks, start=1):
            if cancel_requested():
                break
            doc = self._renderer.open_document(task.input_path)
            try:
                target_size = self._compute_target_size(doc, settings)
                output_pages = []
                for pidx in range(doc.page_count):
                    if cancel_requested():
                        break
                    page = doc.load_page(pidx)
                    image = self._renderer.render_page_rgb(page, settings.render_dpi)
                    analysis = self._analyzer.analyze(image, AnalyzerConfig(settings.content_threshold, settings.edge_dark_threshold))
                    page_result = self._normalizer.normalize(
                        image,
                        analysis,
                        NormalizeConfig(settings.deskew, settings.normalize_margins, settings.margin_ratio),
                        target_size,
                    )
                    output_pages.append(page_result)
                    on_progress(ProgressUpdate(file_idx, len(tasks), pidx + 1, doc.page_count, f"{task.input_path.name}"))
                if output_pages:
                    self._writer.write_from_images(output_pages, task.output_path)
                    processed += 1
            finally:
                doc.close()
        return processed, len(tasks)

    def _compute_target_size(self, doc, settings: ProcessingSettings) -> tuple[int, int]:
        sizes = []
        for idx in range(doc.page_count):
            page = doc.load_page(idx)
            pix = page.get_pixmap(matrix=doc[idx].derotation_matrix)
            sizes.append((pix.width, pix.height))
        if settings.page_size_mode == PageSizeMode.FORCE_UNIFORM:
            return max(sizes, key=lambda s: s[0] * s[1])
        if settings.page_size_mode == PageSizeMode.FIT_TO_CONTENT:
            return min(sizes, key=lambda s: s[0] * s[1])
        return Counter(sizes).most_common(1)[0][0]
