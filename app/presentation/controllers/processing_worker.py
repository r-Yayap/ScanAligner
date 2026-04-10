from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.application.dto.progress import ProgressUpdate
from app.application.services.file_discovery_service import FileDiscoveryService
from app.application.use_cases.process_documents_use_case import ProcessDocumentsUseCase
from app.config.settings import ProcessingSettings


class ProcessingWorker(QObject):
    progress = Signal(object)
    finished = Signal(int, int)
    failed = Signal(str)
    log = Signal(str)

    def __init__(
        self,
        use_case: ProcessDocumentsUseCase,
        discovery: FileDiscoveryService,
        inputs: list[Path],
        settings: ProcessingSettings,
    ) -> None:
        super().__init__()
        self._use_case = use_case
        self._discovery = discovery
        self._inputs = inputs
        self._settings = settings
        self._cancel = False

    @Slot()
    def run(self) -> None:
        try:
            tasks = self._discovery.build_tasks(self._inputs, self._settings.output_dir, self._settings.output_suffix, self._settings.overwrite)
            self.log.emit(f"Queued {len(tasks)} files")
            processed, total = self._use_case.execute(tasks, self._settings, self._on_progress, self._is_cancelled)
            self.finished.emit(processed, total)
        except Exception as exc:
            self.failed.emit(str(exc))

    @Slot()
    def cancel(self) -> None:
        self._cancel = True
        self.log.emit("Cancellation requested")

    def _is_cancelled(self) -> bool:
        return self._cancel

    def _on_progress(self, update: ProgressUpdate) -> None:
        self.progress.emit(update)
