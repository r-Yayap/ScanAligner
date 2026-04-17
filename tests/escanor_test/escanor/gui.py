from __future__ import annotations

import sys
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import APP_NAME, EscanorSettings, default_config_path, ensure_config_exists, load_settings, save_settings
from .core import (
    ANCHOR_CHOICES,
    ISO_SIZES_MM,
    compute_template_content_fractions,
    list_input_pdfs,
    load_template_image,
    process_pdf,
    resolve_output_path,
)


class ProcessingWorker(QObject):
    progress_changed = Signal(int)
    log_message = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, settings: EscanorSettings) -> None:
        super().__init__()
        self.settings = settings
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            input_path = Path(self.settings.input_path)
            output_path = Path(self.settings.output_path)

            if not input_path.exists():
                raise FileNotFoundError(f"Input path not found: {input_path}")

            pdfs = list_input_pdfs(input_path, recursive=self.settings.recursive)
            if not pdfs:
                raise RuntimeError("No PDF files were found.")

            template_fractions: Optional[tuple[float, float, float, float]] = None
            if self.settings.template_path:
                template = Path(self.settings.template_path)
                if not template.exists():
                    raise FileNotFoundError(f"Template not found: {template}")

                if self.settings.mode == "content":
                    self.log_message.emit("Loading template for content placement...")
                    template_img = load_template_image(template, dpi=self.settings.dpi)
                    template_fractions = compute_template_content_fractions(template_img)
                    self.log_message.emit(f"Template fractions loaded: {template_fractions}")
                else:
                    self.log_message.emit("Template is only used in content mode. It will be ignored for this run.")

            single_input = input_path.is_file()
            total = len(pdfs)
            self.log_message.emit(f"Escanor found {total} PDF file(s).")

            for index, pdf_path in enumerate(pdfs, start=1):
                if self._cancel_requested:
                    self.log_message.emit("Cancelled by user.")
                    break

                output_pdf = resolve_output_path(pdf_path, output_path, single_input=single_input)
                self.log_message.emit(f"[{index}/{total}] Processing: {pdf_path.name}")
                self.log_message.emit(f"Output: {output_pdf}")

                process_pdf(
                    input_pdf=pdf_path,
                    output_pdf=output_pdf,
                    page_size=self.settings.page_size,
                    dpi=self.settings.dpi,
                    margin_mm=self.settings.content_margin_mm,
                    orientation=self.settings.orientation,
                    mode=self.settings.mode,
                    canvas_margin_mm=self.settings.canvas_margin_mm,
                    template_fractions=template_fractions,
                    page_placement=self.settings.page_placement,
                    page_anchor=self.settings.page_anchor,
                    use_document_frame_consensus=self.settings.use_document_frame_consensus,
                    output_color_mode=self.settings.output_color_mode,
                    reject_paper_edge_frames=self.settings.reject_paper_edge_frames,
                    use_black_white_for_frame_detection=self.settings.use_black_white_for_frame_detection,
                    use_shared_bw_corner_lock=self.settings.use_shared_bw_corner_lock,
                )
                self.progress_changed.emit(int(index / total * 100))
                self.log_message.emit("Done.")

            self.finished.emit()
        except Exception:
            self.failed.emit(traceback.format_exc())


class PathPicker(QWidget):
    def __init__(self, placeholder: str, pick_file: bool = True, pick_folder: bool = True, save_file: bool = False, file_filter: str = "PDF Files (*.pdf)") -> None:
        super().__init__()
        self._save_file = save_file
        self._file_filter = file_filter

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit)

        self.file_button: Optional[QPushButton] = None
        self.folder_button: Optional[QPushButton] = None

        if pick_file:
            self.file_button = QPushButton("File")
            self.file_button.clicked.connect(self._select_file)
            layout.addWidget(self.file_button)

        if pick_folder:
            self.folder_button = QPushButton("Folder")
            self.folder_button.clicked.connect(self._select_folder)
            layout.addWidget(self.folder_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.edit.clear)
        layout.addWidget(self.clear_button)

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, value: str) -> None:
        self.edit.setText(value)

    def _select_file(self) -> None:
        if self._save_file:
            path, _ = QFileDialog.getSaveFileName(self, "Select File", "", self._file_filter)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Select File", "", self._file_filter)
        if path:
            self.edit.setText(path)

    def _select_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if path:
            self.edit.setText(path)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(980, 820)

        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[ProcessingWorker] = None
        self.config_path = ensure_config_exists(default_config_path())

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)

        title = QLabel(APP_NAME)
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        subtitle = QLabel(
            "Refactored scanned PDF normalizer. Default startup values are loaded from a separate config file."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #555;")
        root.addWidget(title)
        root.addWidget(subtitle)

        root.addWidget(self._build_paths_box())
        root.addWidget(self._build_options_box())
        root.addWidget(self._build_config_box())

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #444;")
        root.addWidget(self.hint)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        root.addWidget(self.progress)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)
        root.addLayout(buttons)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        root.addWidget(self.log, 1)

        self.mode_combo.currentTextChanged.connect(self.update_mode_ui)
        self.start_button.clicked.connect(self.start_processing)
        self.cancel_button.clicked.connect(self.cancel_processing)
        self.reload_config_button.clicked.connect(self.reload_config)
        self.save_config_button.clicked.connect(self.save_current_as_defaults)
        self.open_config_folder_button.clicked.connect(self.open_config_folder)

        self.apply_settings_to_ui(load_settings(self.config_path))
        self.update_mode_ui(self.mode_combo.currentText())

    def _build_paths_box(self) -> QGroupBox:
        box = QGroupBox("Paths")
        form = QFormLayout(box)

        self.input_picker = PathPicker(
            "Choose a single PDF file or a folder containing PDFs",
            pick_file=True,
            pick_folder=True,
            save_file=False,
            file_filter="PDF Files (*.pdf)",
        )
        self.output_picker = PathPicker(
            "Choose output PDF path for single input, or output folder for batch",
            pick_file=True,
            pick_folder=True,
            save_file=True,
            file_filter="PDF Files (*.pdf)",
        )
        self.template_picker = PathPicker(
            "Optional template PDF or image",
            pick_file=True,
            pick_folder=False,
            save_file=False,
            file_filter="Supported Files (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
        )

        form.addRow("Input", self.input_picker)
        form.addRow("Output", self.output_picker)
        form.addRow("Template", self.template_picker)
        return box

    def _build_options_box(self) -> QGroupBox:
        box = QGroupBox("Processing Options")
        form = QFormLayout(box)

        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(sorted(ISO_SIZES_MM.keys()))

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["page", "outer_frame", "content"])

        self.page_placement_combo = QComboBox()
        self.page_placement_combo.addItems(["fill", "balanced"])

        self.page_anchor_combo = QComboBox()
        self.page_anchor_combo.addItems(ANCHOR_CHOICES)

        self.orientation_combo = QComboBox()
        self.orientation_combo.addItems(["auto", "landscape", "portrait"])

        self.output_color_combo = QComboBox()
        self.output_color_combo.addItems(["color", "grayscale", "black_white"])

        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 600)

        self.content_margin_spin = QDoubleSpinBox()
        self.content_margin_spin.setRange(0.0, 100.0)
        self.content_margin_spin.setDecimals(2)
        self.content_margin_spin.setSingleStep(1.0)

        self.canvas_margin_spin = QDoubleSpinBox()
        self.canvas_margin_spin.setRange(0.0, 100.0)
        self.canvas_margin_spin.setDecimals(2)
        self.canvas_margin_spin.setSingleStep(1.0)

        self.recursive_check = QCheckBox("Include subfolders when input is a folder")
        self.frame_consensus_check = QCheckBox("Use document frame consensus in outer_frame mode")
        self.reject_paper_edge_check = QCheckBox("Reject paper-edge / missing-frame detections")
        self.bw_frame_detection_check = QCheckBox("Use black-and-white mask for frame detection")
        self.shared_bw_corner_lock_check = QCheckBox("Reuse same B/W mask for BR corner locking and final export")

        form.addRow("Page Size", self.page_size_combo)
        form.addRow("Mode", self.mode_combo)
        form.addRow("Page Placement", self.page_placement_combo)
        form.addRow("Page Anchor / Fallback", self.page_anchor_combo)
        form.addRow("Orientation", self.orientation_combo)
        form.addRow("DPI", self.dpi_spin)
        form.addRow("Output Color", self.output_color_combo)
        form.addRow("Content Margin (mm)", self.content_margin_spin)
        form.addRow("Canvas Margin (mm)", self.canvas_margin_spin)
        form.addRow("", self.recursive_check)
        form.addRow("", self.frame_consensus_check)
        form.addRow("", self.reject_paper_edge_check)
        form.addRow("", self.bw_frame_detection_check)
        form.addRow("", self.shared_bw_corner_lock_check)
        return box

    def _build_config_box(self) -> QGroupBox:
        box = QGroupBox("Config")
        layout = QGridLayout(box)

        self.config_path_label = QLabel(str(self.config_path))
        self.config_path_label.setTextInteractionFlags(self.config_path_label.textInteractionFlags())

        self.reload_config_button = QPushButton("Reload Config")
        self.save_config_button = QPushButton("Save Current as Defaults")
        self.open_config_folder_button = QPushButton("Open Config Folder")

        tip = QLabel(
            "Escanor auto-loads this file on startup. You can edit it manually or save the current UI state back into it."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #555;")

        layout.addWidget(QLabel("Config file"), 0, 0)
        layout.addWidget(self.config_path_label, 0, 1, 1, 3)
        layout.addWidget(self.reload_config_button, 1, 1)
        layout.addWidget(self.save_config_button, 1, 2)
        layout.addWidget(self.open_config_folder_button, 1, 3)
        layout.addWidget(tip, 2, 0, 1, 4)
        return box

    def append_log(self, text: str) -> None:
        self.log.appendPlainText(text)
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log.setTextCursor(cursor)

    def update_mode_ui(self, mode: str) -> None:
        is_page = mode == "page"
        is_outer_frame = mode == "outer_frame"
        is_content = mode == "content"

        self.page_placement_combo.setEnabled(is_page)
        self.page_anchor_combo.setEnabled(is_page or is_outer_frame)
        self.canvas_margin_spin.setEnabled(is_page or is_outer_frame)
        self.content_margin_spin.setEnabled(is_content)
        self.template_picker.setEnabled(is_content)
        self.frame_consensus_check.setEnabled(is_outer_frame)
        self.reject_paper_edge_check.setEnabled(is_outer_frame)
        self.bw_frame_detection_check.setEnabled(is_outer_frame)
        self.shared_bw_corner_lock_check.setEnabled(is_outer_frame and self.output_color_combo.currentText() == "black_white")

        if is_outer_frame:
            self.hint.setText(
                "Outer Frame mode is the best starting point for engineering sheets. It tries to lock the detected printed frame so the bottom-right frame corner lands consistently. Page Anchor is used only as fallback behavior."
            )
        elif is_page:
            self.hint.setText(
                "Page mode normalizes the whole sheet to the canvas. Use fill for simpler full-sheet fitting and balanced for proportional placement."
            )
        else:
            self.hint.setText(
                "Content mode crops visible content and places it on the target canvas. Template is only used in this mode."
            )

    def apply_settings_to_ui(self, settings: EscanorSettings) -> None:
        self.input_picker.setText(settings.input_path)
        self.output_picker.setText(settings.output_path)
        self.template_picker.setText(settings.template_path)

        self.page_size_combo.setCurrentText(settings.page_size)
        self.mode_combo.setCurrentText(settings.mode)
        self.orientation_combo.setCurrentText(settings.orientation)
        self.dpi_spin.setValue(settings.dpi)
        self.output_color_combo.setCurrentText(settings.output_color_mode)
        self.content_margin_spin.setValue(settings.content_margin_mm)
        self.canvas_margin_spin.setValue(settings.canvas_margin_mm)
        self.page_placement_combo.setCurrentText(settings.page_placement)
        self.page_anchor_combo.setCurrentText(settings.page_anchor)

        self.recursive_check.setChecked(settings.recursive)
        self.frame_consensus_check.setChecked(settings.use_document_frame_consensus)
        self.reject_paper_edge_check.setChecked(settings.reject_paper_edge_frames)
        self.bw_frame_detection_check.setChecked(settings.use_black_white_for_frame_detection)
        self.shared_bw_corner_lock_check.setChecked(settings.use_shared_bw_corner_lock)

    def gather_settings_from_ui(self) -> EscanorSettings:
        return EscanorSettings(
            input_path=self.input_picker.text(),
            output_path=self.output_picker.text(),
            template_path=self.template_picker.text(),
            recursive=self.recursive_check.isChecked(),
            page_size=self.page_size_combo.currentText(),
            mode=self.mode_combo.currentText(),
            orientation=self.orientation_combo.currentText(),
            dpi=self.dpi_spin.value(),
            output_color_mode=self.output_color_combo.currentText(),
            content_margin_mm=self.content_margin_spin.value(),
            canvas_margin_mm=self.canvas_margin_spin.value(),
            page_placement=self.page_placement_combo.currentText(),
            page_anchor=self.page_anchor_combo.currentText(),
            use_document_frame_consensus=self.frame_consensus_check.isChecked(),
            reject_paper_edge_frames=self.reject_paper_edge_check.isChecked(),
            use_black_white_for_frame_detection=self.bw_frame_detection_check.isChecked(),
            use_shared_bw_corner_lock=self.shared_bw_corner_lock_check.isChecked(),
        )

    def validate_inputs(self, settings: EscanorSettings) -> bool:
        if not settings.input_path:
            QMessageBox.warning(self, "Missing Input", "Please choose an input PDF file or folder.")
            return False
        if not settings.output_path:
            QMessageBox.warning(self, "Missing Output", "Please choose an output path or folder.")
            return False
        return True

    def reload_config(self) -> None:
        try:
            settings = load_settings(self.config_path)
            self.apply_settings_to_ui(settings)
            self.update_mode_ui(self.mode_combo.currentText())
            self.append_log(f"Reloaded config: {self.config_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Config Error", f"Could not reload config.\n\n{exc}")

    def save_current_as_defaults(self) -> None:
        try:
            settings = self.gather_settings_from_ui()
            save_settings(settings, self.config_path)
            self.append_log(f"Saved current UI values to config: {self.config_path}")
            QMessageBox.information(self, "Saved", f"Defaults saved to:\n{self.config_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Config Error", f"Could not save config.\n\n{exc}")

    def open_config_folder(self) -> None:
        folder = self.config_path.parent
        QMessageBox.information(self, "Config Folder", f"Config folder:\n{folder}")

    def start_processing(self) -> None:
        settings = self.gather_settings_from_ui()
        if not self.validate_inputs(settings):
            return

        self.progress.setValue(0)
        self.log.clear()
        self.append_log("Starting Escanor...")

        self.worker_thread = QThread(self)
        self.worker = ProcessingWorker(settings)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress_changed.connect(self.progress.setValue)
        self.worker.log_message.connect(self.append_log)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.cleanup_worker)

        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.worker_thread.start()

    def cancel_processing(self) -> None:
        if self.worker is not None:
            self.worker.request_cancel()
            self.append_log("Cancel requested...")

    def on_finished(self) -> None:
        self.progress.setValue(100)
        self.append_log("Escanor finished.")
        QMessageBox.information(self, "Finished", "Escanor completed the processing run.")
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def on_failed(self, error_text: str) -> None:
        self.append_log(error_text)
        QMessageBox.critical(self, "Error", error_text)
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def cleanup_worker(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        if self.worker_thread is not None:
            self.worker_thread.deleteLater()
            self.worker_thread = None


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
