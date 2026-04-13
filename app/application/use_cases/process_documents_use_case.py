from collections import Counter
from math import ceil
from pathlib import Path
from time import perf_counter
from typing import Callable

import cv2

from app.application.dto.progress import ProgressUpdate
from app.config.settings import ProcessingSettings
from app.domain.enums.page_size_mode import PageSizeMode
from app.domain.models.document_task import DocumentTask
from app.domain.models.page_bounds import Rect
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
        on_log: Callable[[str], None] | None = None,
    ) -> tuple[int, int]:
        def log(message: str) -> None:
            if on_log is not None:
                on_log(message)

        run_start = perf_counter()
        processed = 0
        template = self._load_title_block_template(settings)
        target_size, reference_content_size = self._compute_batch_layout(tasks, settings, cancel_requested, log if settings.debug_tracing else None)
        if settings.debug_tracing:
            template_source = "none"
            if settings.title_block_template_path is not None:
                template_source = f"file:{settings.title_block_template_path.name}"
            elif settings.derive_template_from_selection and settings.manual_title_block_rect is not None:
                template_source = "manual-selection"
            log(
                f"[DEBUG] Layout target={target_size}, reference-content={reference_content_size}, template-source={template_source}, "
                f"template-region-start={int(settings.template_search_region_ratio * 100)}%, min-matches={settings.template_min_good_matches}, "
                f"max-features={settings.template_max_features}"
            )
        for file_idx, task in enumerate(tasks, start=1):
            if cancel_requested():
                break
            file_start = perf_counter()
            doc = self._renderer.open_document(task.input_path)
            try:
                output_pages = []
                for pidx in range(doc.page_count):
                    if cancel_requested():
                        break
                    page = doc.load_page(pidx)
                    image = self._renderer.render_page_rgb(page, settings.render_dpi)
                    manual_rect = self._manual_title_block_rect(image.shape[1], image.shape[0], settings)
                    if template is None and settings.derive_template_from_selection and manual_rect is not None:
                        template = image[manual_rect.y:manual_rect.y + manual_rect.h, manual_rect.x:manual_rect.x + manual_rect.w].copy()
                    analysis = self._analyzer.analyze(
                        image,
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
                    if settings.debug_tracing:
                        log(
                            f"[DEBUG] Processed {task.input_path.name}: {len(output_pages)} page(s) in "
                            f"{perf_counter() - file_start:.2f}s"
                        )
            finally:
                doc.close()
        if settings.debug_tracing:
            log(f"[DEBUG] Total processing time: {perf_counter() - run_start:.2f}s")
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
        on_log: Callable[[str], None] | None = None,
    ) -> tuple[tuple[int, int], tuple[int, int]]:
        sizes = []
        content_sizes = []
        sampled_pages = 0
        total_pages = 0
        for task in tasks:
            if cancel_requested():
                break
            doc = self._renderer.open_document(task.input_path)
            try:
                page_indexes = self._sample_page_indexes(doc.page_count, settings.preflight_sample_pages)
                total_pages += doc.page_count
                for idx in page_indexes:
                    page = doc.load_page(idx)
                    image = self._renderer.render_page_rgb(page, settings.render_dpi)
                    sizes.append((image.shape[1], image.shape[0]))
                    analysis = self._analyzer.analyze(image, AnalyzerConfig(settings.content_threshold, settings.edge_dark_threshold))
                    content_sizes.append((analysis.crop_rect.w, analysis.crop_rect.h))
                    sampled_pages += 1
            finally:
                doc.close()

        target_size = self._compute_target_size(sizes, settings)
        reference_content_size = max(content_sizes, key=lambda s: s[0] * s[1]) if content_sizes else target_size
        if settings.normalize_margins and 0 <= settings.margin_ratio < 0.5:
            usable_ratio = 1.0 - (2.0 * settings.margin_ratio)
            min_w = ceil(reference_content_size[0] / max(usable_ratio, 1e-6))
            min_h = ceil(reference_content_size[1] / max(usable_ratio, 1e-6))
            target_size = (max(target_size[0], min_w), max(target_size[1], min_h))
        if on_log is not None:
            on_log(
                f"[DEBUG] Preflight analyzed {sampled_pages}/{total_pages} page(s) using sample size {settings.preflight_sample_pages}."
            )
        return target_size, reference_content_size

    def _sample_page_indexes(self, page_count: int, sample_pages: int) -> list[int]:
        if page_count <= 0:
            return []
        if sample_pages <= 0 or sample_pages >= page_count:
            return list(range(page_count))
        if sample_pages == 1:
            return [0]
        last = page_count - 1
        indexes = {0, last}
        step = last / float(sample_pages - 1)
        indexes.update(int(round(i * step)) for i in range(sample_pages))
        return sorted(indexes)

    def _manual_title_block_rect(self, width: int, height: int, settings: ProcessingSettings) -> Rect | None:
        if not settings.manual_title_block_enabled or settings.manual_title_block_rect is None:
            return None
        x, y, w, h = settings.manual_title_block_rect
        x = max(0, min(x, width - 1))
        y = max(0, min(y, height - 1))
        w = max(1, min(w, width - x))
        h = max(1, min(h, height - y))
        return Rect(x, y, w, h)

    def _load_title_block_template(self, settings: ProcessingSettings):
        if settings.title_block_template_path is None:
            return None
        path = settings.title_block_template_path
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
