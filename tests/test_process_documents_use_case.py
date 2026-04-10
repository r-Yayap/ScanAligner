from pathlib import Path

import numpy as np

from app.application.use_cases.process_documents_use_case import ProcessDocumentsUseCase
from app.config.settings import ProcessingSettings
from app.domain.models.document_task import DocumentTask
from app.domain.models.page_bounds import PageAnalysis, Rect


class _FakePage:
    pass


class _FakeDoc:
    def __init__(self, page_count: int) -> None:
        self.page_count = page_count

    def load_page(self, idx: int) -> _FakePage:
        return _FakePage()

    def close(self) -> None:
        return None


class _FakeRenderer:
    def open_document(self, path: Path) -> _FakeDoc:
        return _FakeDoc(1)

    def render_page_rgb(self, page: _FakePage, dpi: int) -> np.ndarray:
        return np.zeros((3300, 2550, 3), dtype=np.uint8)


class _FakeAnalyzer:
    def analyze(self, bgr: np.ndarray, cfg: object) -> PageAnalysis:
        return PageAnalysis(
            content_rect=Rect(0, 0, bgr.shape[1], bgr.shape[0]),
            crop_rect=Rect(0, 0, bgr.shape[1], bgr.shape[0]),
            skew_angle=0.0,
        )


def test_compute_batch_layout_uses_render_dimensions_for_target_size() -> None:
    use_case = ProcessDocumentsUseCase(_FakeRenderer(), _FakeAnalyzer(), normalizer=object(), writer=object())  # type: ignore[arg-type]
    tasks = [DocumentTask(input_path=Path("in.pdf"), output_path=Path("out.pdf"), root_path=Path("."))]
    settings = ProcessingSettings()
    target_size, reference_content_size = use_case._compute_batch_layout(tasks, settings, cancel_requested=lambda: False)
    assert target_size == (2550, 3300)
    assert reference_content_size == (2550, 3300)
