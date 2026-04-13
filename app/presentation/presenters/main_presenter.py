from pathlib import Path

import cv2
from PySide6.QtCore import QThread
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QMessageBox

from app.application.services.file_discovery_service import FileDiscoveryService
from app.application.services.preview_service import PreviewService
from app.application.use_cases.process_documents_use_case import ProcessDocumentsUseCase
from app.common.utils.path_utils import expand_pdf_paths
from app.config.settings import ProcessingSettings
from app.presentation.controllers.processing_worker import ProcessingWorker


class MainPresenter:
    def __init__(self, view, preview_service: PreviewService, process_use_case: ProcessDocumentsUseCase) -> None:
        self.view = view
        self.preview_service = preview_service
        self.process_use_case = process_use_case
        self.file_discovery = FileDiscoveryService()
        self.input_files: list[Path] = []
        self.current_page = 0
        self.thread: QThread | None = None
        self.worker: ProcessingWorker | None = None

    def add_paths(self, raw_paths: list[str], replace: bool = False) -> None:
        items = [Path(p) for p in raw_paths]
        files = expand_pdf_paths(items)
        if replace:
            self.input_files = files
        else:
            for f in files:
                if f not in self.input_files:
                    self.input_files.append(f)
        self.view.set_files(self.input_files)

    def clear_files(self) -> None:
        self.input_files = []
        self.view.set_files(self.input_files)

    def remove_selected(self, indexes: list[int]) -> None:
        self.input_files = [p for i, p in enumerate(self.input_files) if i not in indexes]
        self.view.set_files(self.input_files)

    def preview(
        self,
        file_index: int,
        page_index: int,
        settings: ProcessingSettings,
        include_processed: bool = False,
        preview_mode: str = "processed",
    ) -> None:
        if not self.input_files:
            return
        path = self.input_files[file_index]
        original, processed, page_total = self.preview_service.preview_page(
            path,
            page_index,
            settings,
            include_processed=include_processed,
            preview_mode=preview_mode,
        )
        current = min(page_index, max(0, page_total - 1)) + 1
        self.current_page = current - 1
        self.view.set_page_label(current, page_total)
        self.view.show_preview(self._to_pixmap(original), self._to_pixmap(processed) if processed is not None else None)

    def start_processing(self, settings: ProcessingSettings) -> None:
        if not self.input_files:
            QMessageBox.warning(self.view, "No Input", "Please add PDFs first.")
            return
        self.thread = QThread(self.view)
        self.worker = ProcessingWorker(self.process_use_case, self.file_discovery, self.input_files, settings)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.view.update_progress)
        self.worker.log.connect(self.view.append_log)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.start()

    def cancel_processing(self) -> None:
        if self.worker:
            self.worker.cancel()

    def _on_finished(self, processed: int, total: int) -> None:
        self.view.append_log(f"Completed {processed}/{total} files")
        self.view.processing_done()

    def _on_failed(self, message: str) -> None:
        self.view.append_log(f"Error: {message}")
        QMessageBox.critical(self.view, "Processing Error", message)
        self.view.processing_done()

    def _to_pixmap(self, bgr) -> QPixmap:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        image = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        return QPixmap.fromImage(image.copy())
