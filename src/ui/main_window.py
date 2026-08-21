import os
import sys
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QFont, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QSlider, QCheckBox, QGroupBox, QMessageBox, QFrame, QSplitter
)

from src.ui.workers import IndexWorker, SearchWorker
from src.utils.file_utils import open_document_in_default_app, format_file_size
from src.utils.logger import get_logger

logger = get_logger("ui_main_window")

STYLESHEET = """
QMainWindow {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
QWidget {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    font-size: 13px;
    color: #cdd6f4;
}
QGroupBox {
    font-weight: bold;
    border: 1px solid #45475a;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 15px;
    background-color: #181825;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 15px;
    padding: 0 5px;
    color: #89b4fa;
}
QPushButton {
    background-color: #89b4fa;
    color: #11111b;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #b4befe;
}
QPushButton:pressed {
    background-color: #74c7ec;
}
QPushButton:disabled {
    background-color: #45475a;
    color: #6c7086;
}
QLineEdit, QSlider {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px;
}
QProgressBar {
    border: 1px solid #45475a;
    border-radius: 6px;
    text-align: center;
    background-color: #313244;
}
QProgressBar::chunk {
    background-color: #a6e3a1;
    border-radius: 5px;
}
QTableWidget {
    background-color: #181825;
    gridline-color: #313244;
    border: 1px solid #45475a;
    border-radius: 8px;
}
QHeaderView::section {
    background-color: #313244;
    color: #89b4fa;
    padding: 6px;
    font-weight: bold;
    border: none;
}
QLabel#DropLabel {
    border: 2px dashed #89b4fa;
    border-radius: 10px;
    padding: 20px;
    background-color: #1e1e2e;
    color: #a6adc8;
}
"""

class DragDropLabel(QLabel):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setObjectName("DropLabel")
        self.setText("Drag & Drop PDF File Here\nor Click 'Browse PDF'")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) > 0 and urls[0].toLocalFile().lower().endswith(".pdf"):
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            self.parent_window.set_pdf_path(file_path)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF to Word Template Finder")
        self.resize(1100, 750)
        self.setStyleSheet(STYLESHEET)

        self.selected_folder = ""
        self.selected_pdf = ""
        self.index_worker = None
        self.search_worker = None

        self._init_ui()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(12)

        # Header Title
        title_label = QLabel("PDF to Word Template Finder")
        title_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #89b4fa; margin-bottom: 5px;")
        main_layout.addWidget(title_label)

        # Step 1 & 2 Controls Box
        controls_group = QGroupBox("Configuration & Inputs")
        controls_layout = QVBoxLayout(controls_group)

        # Folder Selection Row
        folder_row = QHBoxLayout()
        self.folder_label = QLabel("Search Folder: (No folder selected)")
        self.folder_label.setStyleSheet("color: #a6adc8;")
        btn_select_folder = QPushButton("Select Folder")
        btn_select_folder.clicked.connect(self.select_folder)

        self.chk_recursive = QCheckBox("Search Subfolders")
        self.chk_recursive.setChecked(True)

        folder_row.addWidget(btn_select_folder)
        folder_row.addWidget(self.folder_label, 1)
        folder_row.addWidget(self.chk_recursive)
        controls_layout.addLayout(folder_row)

        # PDF Upload Row & Drag-Drop
        pdf_row = QHBoxLayout()
        self.drop_label = DragDropLabel(self)
        self.drop_label.setMaximumHeight(80)

        btn_select_pdf = QPushButton("Browse PDF")
        btn_select_pdf.clicked.connect(self.select_pdf)

        pdf_row.addWidget(btn_select_pdf)
        pdf_row.addWidget(self.drop_label, 1)
        controls_layout.addLayout(pdf_row)

        # Threshold Slider & Search Action Row
        threshold_row = QHBoxLayout()
        threshold_row.addWidget(QLabel("Similarity Threshold:"))
        self.slider_threshold = QSlider(Qt.Orientation.Horizontal)
        self.slider_threshold.setRange(30, 100)
        self.slider_threshold.setValue(100)
        self.slider_threshold.valueChanged.connect(self.update_threshold_label)

        self.lbl_threshold_val = QLabel("100%")
        self.lbl_threshold_val.setStyleSheet("font-weight: bold; color: #a6e3a1;")

        self.btn_start_search = QPushButton("Start Template Search")
        self.btn_start_search.setStyleSheet("background-color: #a6e3a1; color: #11111b; font-size: 14px; padding: 10px 20px;")
        self.btn_start_search.clicked.connect(self.start_search)

        threshold_row.addWidget(self.slider_threshold)
        threshold_row.addWidget(self.lbl_threshold_val)
        threshold_row.addSpacing(20)
        threshold_row.addWidget(self.btn_start_search)

        controls_layout.addLayout(threshold_row)
        main_layout.addWidget(controls_group)

        # Progress & Status Bar
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)

        self.lbl_status = QLabel("Ready.")
        self.lbl_status.setStyleSheet("color: #bac2de;")

        progress_layout.addWidget(self.lbl_status, 1)
        progress_layout.addWidget(self.progress_bar, 1)
        main_layout.addLayout(progress_layout)

        # Results Table Box
        results_group = QGroupBox("Matching Word Templates")
        results_layout = QVBoxLayout(results_group)

        self.table_results = QTableWidget()
        self.table_results.setColumnCount(10)
        self.table_results.setHorizontalHeaderLabels([
            "Match %", "Confidence", "Word File Name", "Folder",
            "Matching Pages", "Matching Sections", "Modified Date", "Size",
            "Why Selected", "Action"
        ])
        self.table_results.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_results.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        self.table_results.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        results_layout.addWidget(self.table_results)

        main_layout.addWidget(results_group, 1)

        # Bottom Statistics Bar
        self.lbl_stats = QLabel("Indexed Templates: 0 | Matches Found: 0 | Execution Time: 0.0s")
        self.lbl_stats.setStyleSheet("color: #6c7086; font-size: 11px;")
        main_layout.addWidget(self.lbl_stats)

    def update_threshold_label(self, val: int):
        self.lbl_threshold_val.setText(f"{val}%")

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder Containing Word Documents")
        if folder:
            self.selected_folder = folder
            self.folder_label.setText(f"Search Folder: {folder}")
            self.start_indexing()

    def select_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select PDF File", "", "PDF Files (*.pdf)")
        if file_path:
            self.set_pdf_path(file_path)

    def set_pdf_path(self, file_path: str):
        self.selected_pdf = file_path
        file_name = os.path.basename(file_path)
        self.drop_label.setText(f"Selected PDF:\n{file_name}")
        self.lbl_status.setText(f"PDF Selected: {file_name}")

    def start_indexing(self):
        if not self.selected_folder:
            return

        self.progress_bar.setVisible(True)
        self.lbl_status.setText("Scanning and indexing Word templates...")
        self.index_worker = IndexWorker(self.selected_folder, self.chk_recursive.isChecked())
        self.index_worker.progress_signal.connect(self.on_index_progress)
        self.index_worker.finished_signal.connect(self.on_index_finished)
        self.index_worker.error_signal.connect(self.on_worker_error)
        self.index_worker.start()

    def on_index_progress(self, current: int, total: int, msg: str):
        if total > 0:
            pct = int((current / total) * 100)
            self.progress_bar.setValue(pct)
        self.lbl_status.setText(msg)

    def on_index_finished(self, docs: list):
        self.progress_bar.setVisible(False)
        count = len(docs)
        self.lbl_status.setText(f"Indexing completed. {count} Word template(s) ready.")
        self.lbl_stats.setText(f"Indexed Templates: {count} | Matches Found: 0 | Execution Time: 0.0s")

    def start_search(self):
        if not self.selected_pdf:
            QMessageBox.warning(self, "PDF Missing", "Please select or drop a PDF file to search against templates.")
            return

        if not self.selected_folder:
            QMessageBox.warning(self, "Folder Missing", "Please select a folder containing Word templates.")
            return

        threshold = float(self.slider_threshold.value())
        self.progress_bar.setVisible(True)
        self.btn_start_search.setEnabled(False)

        self.search_worker = SearchWorker(self.selected_pdf, threshold)
        self.search_worker.progress_signal.connect(self.on_search_progress)
        self.search_worker.finished_signal.connect(self.on_search_finished)
        self.search_worker.error_signal.connect(self.on_worker_error)
        self.search_worker.start()

    def on_search_progress(self, current: int, total: int, msg: str):
        self.progress_bar.setValue(current)
        self.lbl_status.setText(msg)

    def on_search_finished(self, results: list, elapsed: float, is_scanned: bool):
        self.progress_bar.setVisible(False)
        self.btn_start_search.setEnabled(True)

        scanned_badge = " (OCR Scanned PDF)" if is_scanned else " (Editable PDF)"
        self.lbl_status.setText(f"Search complete in {elapsed:.2f}s.{scanned_badge}")

        self.populate_results_table(results)

        total_indexed = self.search_worker.index_manager.db.get_all_documents()
        self.lbl_stats.setText(
            f"Indexed Templates: {len(total_indexed)} | Matches Found: {len(results)} | Execution Time: {elapsed:.2f}s"
        )

    def populate_results_table(self, results: list):
        self.table_results.setRowCount(0)
        for row_idx, res in enumerate(results):
            self.table_results.insertRow(row_idx)

            # Match %
            item_match = QTableWidgetItem(f"{res.overall_score:.1f}%")
            item_match.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_match.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            if res.overall_score >= 85:
                item_match.setForeground(Qt.GlobalColor.green)
            else:
                item_match.setForeground(Qt.GlobalColor.yellow)

            # Confidence
            item_conf = QTableWidgetItem(f"{res.confidence_score:.1f}%")
            item_conf.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # File Name
            item_name = QTableWidgetItem(res.word_file_name)
            item_name.setToolTip(res.file_path)

            # Folder
            item_folder = QTableWidgetItem(res.folder_name)

            # Matching Pages
            pages_str = ", ".join(str(p) for p in res.matching_pages) if res.matching_pages else "-"
            item_pages = QTableWidgetItem(pages_str)

            # Matching Sections
            sections_str = ", ".join(res.matching_sections) if res.matching_sections else "General Text"
            item_sections = QTableWidgetItem(sections_str)

            # Modified & Size
            item_date = QTableWidgetItem(res.last_modified_date)
            item_size = QTableWidgetItem(res.file_size_str)

            # Why Selected
            item_reason = QTableWidgetItem(res.selection_reason or res.rejected_reason or "-")
            item_reason.setToolTip(res.selection_reason or res.rejected_reason or "")
            item_reason.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            # Action Button
            btn_open = QPushButton("Open Doc")
            btn_open.setStyleSheet("background-color: #89b4fa; color: #11111b; font-size: 11px;")
            file_path = res.file_path
            btn_open.clicked.connect(lambda _, fp=file_path: open_document_in_default_app(fp))

            self.table_results.setItem(row_idx, 0, item_match)
            self.table_results.setItem(row_idx, 1, item_conf)
            self.table_results.setItem(row_idx, 2, item_name)
            self.table_results.setItem(row_idx, 3, item_folder)
            self.table_results.setItem(row_idx, 4, item_pages)
            self.table_results.setItem(row_idx, 5, item_sections)
            self.table_results.setItem(row_idx, 6, item_date)
            self.table_results.setItem(row_idx, 7, item_size)
            self.table_results.setItem(row_idx, 8, item_reason)
            self.table_results.setCellWidget(row_idx, 9, btn_open)

    def on_worker_error(self, err_msg: str):
        self.progress_bar.setVisible(False)
        self.btn_start_search.setEnabled(True)
        self.lbl_status.setText("Error occurred during operation.")
        QMessageBox.critical(self, "Processing Error", f"An error occurred:\n{err_msg}")
