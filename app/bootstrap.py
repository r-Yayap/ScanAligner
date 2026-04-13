from pathlib import Path

from app.application.services.preview_service import PreviewService
from app.application.use_cases.process_documents_use_case import ProcessDocumentsUseCase
from app.infrastructure.imaging.page_analyzer import PageAnalyzer
from app.infrastructure.imaging.page_normalizer import PageNormalizer
from app.infrastructure.logging.logger_factory import configure_logging
from app.infrastructure.pdf.pdf_reader import PdfPageRenderer
from app.infrastructure.pdf.pdf_writer import PdfWriter
from app.presentation.presenters.main_presenter import MainPresenter
from app.ui.main_window import MainWindow


def build_app() -> tuple[MainWindow, MainPresenter]:
    logger = configure_logging(Path.cwd() / "logs")
    logger.info("Bootstrapping Eskan")

    renderer = PdfPageRenderer()
    analyzer = PageAnalyzer()
    normalizer = PageNormalizer()
    writer = PdfWriter()

    preview_service = PreviewService(renderer, analyzer, normalizer)
    process_use_case = ProcessDocumentsUseCase(renderer, analyzer, normalizer, writer)

    view = MainWindow()
    presenter = MainPresenter(view, preview_service, process_use_case)

    view.btn_add.clicked.connect(lambda: _on_add(view, presenter))
    view.file_list.files_dropped.connect(lambda paths: _on_drop(paths, view, presenter))
    view.btn_remove.clicked.connect(lambda: presenter.remove_selected(view.selected_file_indexes()))
    view.btn_clear.clicked.connect(presenter.clear_files)
    view.btn_browse_out.clicked.connect(view.choose_output_dir)
    view.btn_browse_template.clicked.connect(lambda: _select_template(view, presenter))
    view.btn_preview.clicked.connect(lambda: _refresh_preview(view, presenter, 0))
    view.btn_prev.clicked.connect(lambda: _navigate(view, presenter, -1))
    view.btn_next.clicked.connect(lambda: _navigate(view, presenter, 1))
    view.file_list.currentRowChanged.connect(lambda _: _refresh_preview(view, presenter, 0))
    view.chk_manual_title_block.toggled.connect(lambda _: _refresh_preview(view, presenter, 0))
    view.btn_clear_title_selection.clicked.connect(lambda: _clear_title_selection(view, presenter))
    view.lbl_original.selection_changed.connect(lambda _: _refresh_preview(view, presenter, 0))
    view.btn_start.clicked.connect(lambda: _start(view, presenter))
    view.btn_cancel.clicked.connect(presenter.cancel_processing)

    return view, presenter


def _on_add(view: MainWindow, presenter: MainPresenter) -> None:
    from PySide6.QtWidgets import QFileDialog

    files, _ = QFileDialog.getOpenFileNames(view, "Select PDFs", filter="PDF files (*.pdf)")
    if not files:
        return
    mode = view.maybe_append_or_replace()
    if mode == "cancel":
        return
    presenter.add_paths(files, replace=mode == "replace")


def _on_drop(paths: list[str], view: MainWindow, presenter: MainPresenter) -> None:
    mode = view.maybe_append_or_replace()
    if mode == "cancel":
        return
    presenter.add_paths(paths, replace=mode == "replace")


def _refresh_preview(view: MainWindow, presenter: MainPresenter, delta: int) -> None:
    if not presenter.input_files:
        return
    presenter.current_page = max(0, presenter.current_page + delta)
    settings = view.get_settings()
    idx = view.current_file_index()
    presenter.preview(idx, presenter.current_page, settings)


def _navigate(view: MainWindow, presenter: MainPresenter, delta: int) -> None:
    _refresh_preview(view, presenter, delta)


def _start(view: MainWindow, presenter: MainPresenter) -> None:
    view.processing_started()
    presenter.start_processing(view.get_settings())


def _clear_title_selection(view: MainWindow, presenter: MainPresenter) -> None:
    view.clear_title_block_selection()
    _refresh_preview(view, presenter, 0)


def _select_template(view: MainWindow, presenter: MainPresenter) -> None:
    view.choose_title_template()
    _refresh_preview(view, presenter, 0)
