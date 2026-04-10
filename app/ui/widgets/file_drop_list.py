from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QListWidget


class FileDropList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(url.toLocalFile()).as_posix() for url in event.mimeData().urls()]
        self.files_dropped.emit(paths)
        event.acceptProposedAction()
