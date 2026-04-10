from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QProgressBar,
    QSlider,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QAbstractItemView,
    QWidget,
)

from app.config.settings import ProcessingSettings
from app.domain.enums.page_size_mode import PageSizeMode
from app.ui.dialogs.append_replace_dialog import ask_append_or_replace
from app.ui.widgets.file_drop_list import FileDropList


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Eskan - Scan Normalization")
        self.resize(1400, 860)
        self._setup_ui()

    def _setup_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        splitter = QSplitter(Qt.Horizontal)
        left = self._build_left_panel()
        right = self._build_right_panel()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([450, 950])

        root.addWidget(splitter)
        root.addWidget(self.log_box)
        self.setCentralWidget(central)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.file_list = FileDropList()
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(QLabel("Input PDFs (drag-drop files/folders)"))
        layout.addWidget(self.file_list)

        buttons = QHBoxLayout()
        self.btn_add = QPushButton("Add")
        self.btn_remove = QPushButton("Remove Selected")
        self.btn_clear = QPushButton("Clear")
        buttons.addWidget(self.btn_add)
        buttons.addWidget(self.btn_remove)
        buttons.addWidget(self.btn_clear)
        layout.addLayout(buttons)

        settings_box = QGroupBox("Settings")
        form = QFormLayout(settings_box)
        self.chk_crop = QCheckBox(); self.chk_crop.setChecked(True)
        self.chk_deskew = QCheckBox(); self.chk_deskew.setChecked(True)
        self.chk_edges = QCheckBox(); self.chk_edges.setChecked(True)
        self.chk_margins = QCheckBox(); self.chk_margins.setChecked(True)
        self.chk_title_block = QCheckBox(); self.chk_title_block.setChecked(False)
        self.chk_title_overlay = QCheckBox(); self.chk_title_overlay.setChecked(True)
        self.chk_title_block = QCheckBox(); self.chk_title_block.setChecked(True)
        self.cmb_page_size = QComboBox()
        self.cmb_page_size.addItems([
            PageSizeMode.PRESERVE_DOMINANT.value,
            PageSizeMode.FORCE_UNIFORM.value,
            PageSizeMode.FIT_TO_CONTENT.value,
        ])
        self.spin_threshold = QSpinBox(); self.spin_threshold.setRange(100, 250); self.spin_threshold.setValue(205)
        self.spin_dark = QSpinBox(); self.spin_dark.setRange(0, 100); self.spin_dark.setValue(40)
        self.sld_margin = QSlider(Qt.Horizontal); self.sld_margin.setRange(1, 20); self.sld_margin.setValue(6)
        self.cmb_anchor = QComboBox()
        self.cmb_anchor.addItems(["bottom_right", "center", "top_left"])
        self.txt_suffix = QLineEdit("_normalized")
        self.txt_output = QLineEdit(str(Path.home() / "Documents" / "EskanOutput"))
        self.chk_overwrite = QCheckBox(); self.chk_overwrite.setChecked(False)
        self.btn_browse_out = QPushButton("Browse")
        out_row = QHBoxLayout(); out_row.addWidget(self.txt_output); out_row.addWidget(self.btn_browse_out)
        out_widget = QWidget(); out_widget.setLayout(out_row)

        form.addRow("Auto crop borders", self.chk_crop)
        form.addRow("Deskew", self.chk_deskew)
        form.addRow("Remove dark edges", self.chk_edges)
        form.addRow("Normalize margins", self.chk_margins)
        form.addRow("Detect title block", self.chk_title_block)
        form.addRow("Show title block overlay", self.chk_title_overlay)
        form.addRow("Page size mode", self.cmb_page_size)
        form.addRow("Content threshold", self.spin_threshold)
        form.addRow("Dark edge threshold", self.spin_dark)
        form.addRow("Margin %", self.sld_margin)
        form.addRow("Content anchor", self.cmb_anchor)
        form.addRow("Output suffix", self.txt_suffix)
        form.addRow("Output directory", out_widget)
        form.addRow("Overwrite", self.chk_overwrite)

        layout.addWidget(settings_box)

        ctl = QHBoxLayout()
        self.btn_start = QPushButton("Start Processing")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        ctl.addWidget(self.btn_start)
        ctl.addWidget(self.btn_cancel)
        layout.addLayout(ctl)

        self.progress = QProgressBar(); layout.addWidget(self.progress)
        self.lbl_current_file = QLabel("File: -")
        self.lbl_current_page = QLabel("Page: -")
        layout.addWidget(self.lbl_current_file)
        layout.addWidget(self.lbl_current_page)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("Prev Page")
        self.btn_next = QPushButton("Next Page")
        self.lbl_page = QLabel("0/0")
        self.btn_preview = QPushButton("Refresh Preview")
        nav.addWidget(self.btn_prev); nav.addWidget(self.btn_next); nav.addWidget(self.lbl_page); nav.addWidget(self.btn_preview)
        layout.addLayout(nav)

        pv = QHBoxLayout()
        self.lbl_original = QLabel("Original")
        self.lbl_processed = QLabel("Processed")
        self.lbl_original.setAlignment(Qt.AlignCenter)
        self.lbl_processed.setAlignment(Qt.AlignCenter)
        self.lbl_original.setMinimumSize(450, 600)
        self.lbl_processed.setMinimumSize(450, 600)
        pv.addWidget(self.lbl_original)
        pv.addWidget(self.lbl_processed)
        layout.addLayout(pv)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(150)
        return panel

    def get_settings(self) -> ProcessingSettings:
        return ProcessingSettings(
            auto_crop_borders=self.chk_crop.isChecked(),
            deskew=self.chk_deskew.isChecked(),
            remove_dark_edges=self.chk_edges.isChecked(),
            normalize_margins=self.chk_margins.isChecked(),
            detect_title_block=self.chk_title_block.isChecked(),
            show_title_block_overlay=self.chk_title_overlay.isChecked(),
            page_size_mode=PageSizeMode(self.cmb_page_size.currentText()),
            content_threshold=self.spin_threshold.value(),
            edge_dark_threshold=self.spin_dark.value(),
            margin_ratio=self.sld_margin.value() / 100,
            content_anchor=self.cmb_anchor.currentText(),
            output_suffix=self.txt_suffix.text().strip() or "_normalized",
            output_dir=Path(self.txt_output.text().strip()),
            overwrite=self.chk_overwrite.isChecked(),
        )

    def choose_output_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select output directory")
        if selected:
            self.txt_output.setText(selected)

    def maybe_append_or_replace(self) -> str:
        if self.file_list.count() == 0:
            return "append"
        return ask_append_or_replace(self)

    def set_files(self, files: list[Path]) -> None:
        self.file_list.clear()
        for f in files:
            self.file_list.addItem(str(f))

    def selected_file_indexes(self) -> list[int]:
        return sorted({self.file_list.row(item) for item in self.file_list.selectedItems()})

    def current_file_index(self) -> int:
        idx = self.file_list.currentRow()
        return 0 if idx < 0 else idx

    def set_page_count(self, total: int) -> None:
        self.lbl_page.setText(f"{self.lbl_page.text().split('/')[0]}/{total}")

    def set_page_label(self, current: int, total: int) -> None:
        self.lbl_page.setText(f"{current}/{total}")

    def show_preview(self, original, processed) -> None:
        self.lbl_original.setPixmap(original.scaled(self.lbl_original.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.lbl_processed.setPixmap(processed.scaled(self.lbl_processed.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def update_progress(self, progress) -> None:
        pct = int(((progress.file_index - 1) + progress.page_index / max(1, progress.page_total)) / max(1, progress.file_total) * 100)
        self.progress.setValue(pct)
        self.lbl_current_file.setText(f"File: {progress.message} ({progress.file_index}/{progress.file_total})")
        self.lbl_current_page.setText(f"Page: {progress.page_index}/{progress.page_total}")

    def append_log(self, text: str) -> None:
        self.log_box.append(text)

    def processing_started(self) -> None:
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)

    def processing_done(self) -> None:
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
