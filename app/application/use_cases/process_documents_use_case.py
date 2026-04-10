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
        target_size, reference_content_size = self._compute_batch_layout(tasks, settings, cancel_requested)
        for file_idx, task in enumerate(tasks, start=1):
            if cancel_requested():
                break
            doc = self._renderer.open_document(task.input_path)
            try:
                output_pages = []
                for pidx in range(doc.page_count):
                    if cancel_requested():
                        break
                    page = doc.load_page(pidx)
                    image = self._renderer.render_page_rgb(page, settings.render_dpi)
                    analysis = self._analyzer.analyze(
                        image,
                        AnalyzerConfig(settings.content_threshold, settings.edge_dark_threshold, settings.detect_title_block),
                    )
                    page_result = self._normalizer.normalize(
                        image,
                        analysis,
                        NormalizeConfig(
                            settings.deskew,
                            settings.normalize_margins,
                            settings.margin_ratio,
                            settings.content_anchor,
                            reference_content_size,
                            settings.detect_title_block,
                        ),
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

    def _compute_target_size(self, sizes: list[tuple[int, int]], settings: ProcessingSettings) -> tuple[int, int]:
        if not sizes:
            return (2480, 3508)
        if settings.page_size_mode == PageSizeMode.FORCE_UNIFORM:
            return max(sizes, key=lambda s: s[0] * s[1])
        if settings.page_size_mode == PageSizeMode.FIT_TO_CONTENT:
            return min(sizes, key=lambda s: s[0] * s[1])
        return Counter(sizes).most_common(1)[0][0]

    def _compute_batch_layout(
        self,
        tasks: list[DocumentTask],
        settings: ProcessingSettings,
        cancel_requested: Callable[[], bool],
    ) -> tuple[tuple[int, int], tuple[int, int]]:
        sizes = []
        content_sizes = []
        for task in tasks:
            if cancel_requested():
                break
            doc = self._renderer.open_document(task.input_path)
            try:
                for idx in range(doc.page_count):
                    page = doc.load_page(idx)
                    pix = page.get_pixmap(matrix=doc[idx].derotation_matrix)
                    sizes.append((pix.width, pix.height))
                    image = self._renderer.render_page_rgb(page, settings.render_dpi)
                    analysis = self._analyzer.analyze(image, AnalyzerConfig(settings.content_threshold, settings.edge_dark_threshold))
                    content_sizes.append((analysis.crop_rect.w, analysis.crop_rect.h))
            finally:
                doc.close()

        target_size = self._compute_target_size(sizes, settings)
        reference_content_size = max(content_sizes, key=lambda s: s[0] * s[1]) if content_sizes else target_size
        return target_size, reference_content_size
