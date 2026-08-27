import os
import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QGroupBox,
    QLineEdit, QRadioButton, QCheckBox, QProgressBar, QMessageBox, QFileDialog,
    QSplitter, QListWidget, QListWidgetItem, QAbstractItemView, QDialog,
    QScrollArea, QComboBox, QFrame, QStyleFactory
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QRect
from PyQt6.QtGui import QIcon, QPixmap, QImage, QColor, QFont, QDragEnterEvent, QDropEvent

from pdf_processor import (
    get_pdf_info, render_page_thumbnail_bytes, render_page_high_res_bytes,
    split_pdf_pages, merge_custom_pages, parse_page_range_string
)
from i18n import tr

def get_resource_path(relative_path):
    """Lấy đường dẫn tài nguyên tuyệt đối, tương thích khi đóng gói bằng PyInstaller"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


# --- THREADS XỬ LÝ NỀN (BACKGROUND WORKERS) ---

class ThumbnailWorker(QThread):
    """
    Thread nạp thumbnail các trang PDF không gây đứng giao diện.
    """
    thumbnail_loaded = pyqtSignal(str, int, bytes) # pdf_path, page_idx, img_bytes
    finished_loading = pyqtSignal()

    def __init__(self, pdf_files):
        super().__init__()
        self.pdf_files = pdf_files

    def run(self):
        for info in self.pdf_files:
            pdf_path = info["path"]
            page_count = info["page_count"]
            for idx in range(page_count):
                try:
                    img_bytes = render_page_thumbnail_bytes(pdf_path, idx, max_dim=180)
                    self.thumbnail_loaded.emit(pdf_path, idx, img_bytes)
                except Exception as e:
                    print(f"Lỗi render thumbnail {pdf_path} trang {idx}: {e}")
        self.finished_loading.emit()


class SplitWorker(QThread):
    """
    Thread thực hiện tách file PDF.
    """
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list, str)
    error = pyqtSignal(str)

    def __init__(self, pdf_files, output_dir, file_pattern, range_str, create_subfolder):
        super().__init__()
        self.pdf_files = pdf_files
        self.output_dir = output_dir
        self.file_pattern = file_pattern
        self.range_str = range_str
        self.create_subfolder = create_subfolder

    def run(self):
        try:
            all_created = []
            for file_idx, info in enumerate(self.pdf_files):
                pdf_path = info["path"]
                def cb(cur, total, name):
                    self.progress.emit(cur, total, f"File {file_idx+1}/{len(self.pdf_files)}: {name}")
                
                created = split_pdf_pages(
                    pdf_path=pdf_path,
                    output_dir=self.output_dir,
                    file_pattern=self.file_pattern,
                    range_str=self.range_str,
                    create_subfolder=self.create_subfolder,
                    progress_callback=cb
                )
                all_created.extend(created)
            self.finished.emit(all_created, self.output_dir)
        except Exception as e:
            self.error.emit(str(e))


class MergeWorker(QThread):
    """
    Thread thực hiện ghép danh sách trang PDF.
    """
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, page_items, output_pdf_path):
        super().__init__()
        self.page_items = page_items
        self.output_pdf_path = output_pdf_path

    def run(self):
        try:
            def cb(cur, total, msg):
                self.progress.emit(cur, total, msg)
                
            out = merge_custom_pages(self.page_items, self.output_pdf_path, progress_callback=cb)
            self.finished.emit(out)
        except Exception as e:
            self.error.emit(str(e))


# --- DIALOG XEM PREVIEW PHÓNG TO ---

class PagePreviewDialog(QDialog):
    def __init__(self, pdf_path, page_idx, lang_code="vi", parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.page_idx = page_idx
        self.lang_code = lang_code
        
        title_str = tr(lang_code, "preview_dialog_title", file=os.path.basename(pdf_path), page=page_idx + 1)
        self.setWindowTitle(title_str)
        self.resize(750, 900)
        
        layout = QVBoxLayout(self)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.img_label = QLabel("Đang tải / Loading...")
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(self.img_label)
        layout.addWidget(scroll)
        
        btn_close = QPushButton(tr(lang_code, "btn_close"))
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
        
        self.load_high_res()

    def load_high_res(self):
        try:
            img_bytes = render_page_high_res_bytes(self.pdf_path, self.page_idx, scale=1.8)
            pixmap = QPixmap()
            pixmap.loadFromData(img_bytes)
            self.img_label.setPixmap(pixmap)
        except Exception as e:
            self.img_label.setText(f"Lỗi tải ảnh: {e}")


# --- CỬA SỔ CHÍNH GIAO DIỆN (MAIN WINDOW) ---

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_lang = "vi" # Mặc định: Tiếng Việt
        self.resize(1180, 820)
        self.setMinimumSize(950, 680)

        # Thiết lập Icon ứng dụng
        icon_path = get_resource_path(os.path.join("assets", "icon.ico"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Hỗ trợ Kéo & Thả file
        self.setAcceptDrops(True)

        self.loaded_files = []
        self.thumbnail_cache = {}

        self.setup_ui()
        self.apply_stylesheet()
        self.retranslate_ui()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # === 1. TOP HEADER & CÁC NÚT QUẢN LÝ FILE ===
        self.file_group = QGroupBox()
        file_layout = QVBoxLayout(self.file_group)

        # Thanh nút bấm nạp file & Ngôn ngữ
        btn_bar = QHBoxLayout()
        self.btn_add_files = QPushButton()
        self.btn_add_files.setObjectName("primaryBtn")
        self.btn_add_files.clicked.connect(self.on_add_files)

        self.btn_add_folder = QPushButton()
        self.btn_add_folder.clicked.connect(self.on_add_folder)

        self.btn_remove_file = QPushButton()
        self.btn_remove_file.clicked.connect(self.on_remove_selected_file)

        self.btn_clear_all = QPushButton()
        self.btn_clear_all.clicked.connect(self.on_clear_all_files)

        self.lbl_file_summary = QLabel()
        self.lbl_file_summary.setStyleSheet("font-weight: bold; color: #4b5563;")

        # Switch Ngôn ngữ (Language Switcher)
        self.lbl_lang = QLabel()
        self.lbl_lang.setStyleSheet("font-weight: bold; color: #0369a1; font-size: 13px;")

        self.cmb_language = QComboBox()
        self.cmb_language.setObjectName("langSwitcher")
        self.cmb_language.addItem("🇻🇳 Tiếng Việt", "vi")
        self.cmb_language.addItem("🇬🇧 English", "en")
        self.cmb_language.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cmb_language.currentIndexChanged.connect(self.on_language_changed)


        btn_bar.addWidget(self.btn_add_files)
        btn_bar.addWidget(self.btn_add_folder)
        btn_bar.addWidget(self.btn_remove_file)
        btn_bar.addWidget(self.btn_clear_all)
        btn_bar.addStretch()
        btn_bar.addWidget(self.lbl_file_summary)
        btn_bar.addWidget(self.lbl_lang)
        btn_bar.addWidget(self.cmb_language)

        file_layout.addLayout(btn_bar)

        # Bảng danh sách file
        self.table_files = QTableWidget()
        self.table_files.setColumnCount(5)
        self.table_files.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_files.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table_files.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_files.setMaximumHeight(160)
        file_layout.addWidget(self.table_files)

        main_layout.addWidget(self.file_group)

        # === 2. CENTER TAB WIDGET ===
        self.tabs = QTabWidget()
        
        # TAB 1: TÁCH TRANG
        self.tab_split = QWidget()
        self.setup_tab_split()
        self.tabs.addTab(self.tab_split, "")

        # TAB 2: GHÉP TRANG TÙY CHỌN
        self.tab_merge = QWidget()
        self.setup_tab_merge()
        self.tabs.addTab(self.tab_merge, "")

        main_layout.addWidget(self.tabs, stretch=1)

    def setup_tab_split(self):
        layout = QVBoxLayout(self.tab_split)
        layout.setSpacing(15)

        # Group Cấu hình thư mục lưu
        self.group_out = QGroupBox()
        out_layout = QVBoxLayout(self.group_out)

        h1 = QHBoxLayout()
        self.lbl_out_dir = QLabel()
        self.txt_split_outdir = QLineEdit(os.path.join(os.path.expanduser("~"), "Desktop", "PDF_Tach_Trang"))
        self.btn_browse_dir = QPushButton()
        self.btn_browse_dir.clicked.connect(self.on_browse_split_outdir)
        h1.addWidget(self.lbl_out_dir)
        h1.addWidget(self.txt_split_outdir, stretch=1)
        h1.addWidget(self.btn_browse_dir)
        out_layout.addLayout(h1)

        h2 = QHBoxLayout()
        self.lbl_pattern = QLabel()
        self.txt_split_pattern = QLineEdit("{name}_trang_{page}.pdf")
        h2.addWidget(self.lbl_pattern)
        h2.addWidget(self.txt_split_pattern, stretch=1)
        self.lbl_pattern_hint = QLabel()
        self.lbl_pattern_hint.setStyleSheet("color: #6b7280; font-size: 11px;")
        h2.addWidget(self.lbl_pattern_hint)
        out_layout.addLayout(h2)

        self.chk_create_subfolder = QCheckBox()
        self.chk_create_subfolder.setChecked(True)
        out_layout.addWidget(self.chk_create_subfolder)

        layout.addWidget(self.group_out)

        # Group Phạm vi trang
        self.group_range = QGroupBox()
        range_layout = QVBoxLayout(self.group_range)

        self.radio_split_all = QRadioButton()
        self.radio_split_all.setChecked(True)
        range_layout.addWidget(self.radio_split_all)

        h_range = QHBoxLayout()
        self.radio_split_custom = QRadioButton()
        self.txt_split_range = QLineEdit("1-5, 8, 10")
        h_range.addWidget(self.radio_split_custom)
        h_range.addWidget(self.txt_split_range, stretch=1)
        range_layout.addLayout(h_range)

        layout.addWidget(self.group_range)

        # Thanh Tiến Trình & Nút Thực Thi
        layout.addStretch()

        self.progress_split = QProgressBar()
        self.progress_split.setValue(0)
        self.progress_split.setTextVisible(True)
        layout.addWidget(self.progress_split)

        self.lbl_split_status = QLabel()
        self.lbl_split_status.setStyleSheet("font-weight: bold; color: #1f2937;")
        layout.addWidget(self.lbl_split_status)

        h_btn_act = QHBoxLayout()
        self.btn_run_split = QPushButton()
        self.btn_run_split.setObjectName("accentBtn")
        self.btn_run_split.setMinimumHeight(45)
        self.btn_run_split.clicked.connect(self.on_run_split)

        self.btn_open_split_dir = QPushButton()
        self.btn_open_split_dir.setMinimumHeight(45)
        self.btn_open_split_dir.setEnabled(False)
        self.btn_open_split_dir.clicked.connect(self.on_open_split_dir)

        h_btn_act.addWidget(self.btn_run_split, stretch=2)
        h_btn_act.addWidget(self.btn_open_split_dir, stretch=1)
        layout.addLayout(h_btn_act)

    def setup_tab_merge(self):
        layout = QVBoxLayout(self.tab_merge)
        layout.setContentsMargins(5, 10, 5, 5)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- PANEL BÊN TRÁI: DẠNG LƯỚI THUMBNAIL TẤT CẢ CÁC TRANG ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(5, 5, 5, 5)

        h_filter = QHBoxLayout()
        self.lbl_filter_file = QLabel()
        self.cmb_filter_pdf = QComboBox()
        self.cmb_filter_pdf.currentIndexChanged.connect(self.on_filter_pdf_changed)
        h_filter.addWidget(self.lbl_filter_file)
        h_filter.addWidget(self.cmb_filter_pdf, stretch=1)
        left_layout.addLayout(h_filter)

        # Quick Bar
        h_quick = QHBoxLayout()
        self.btn_sel_all = QPushButton()
        self.btn_sel_all.clicked.connect(self.on_select_all_thumbnails)

        self.btn_desel_all = QPushButton()
        self.btn_desel_all.clicked.connect(self.on_deselect_all_thumbnails)

        self.btn_add_to_merge = QPushButton()
        self.btn_add_to_merge.setObjectName("primaryBtn")
        self.btn_add_to_merge.clicked.connect(self.on_add_selected_thumbnails_to_queue)

        h_quick.addWidget(self.btn_sel_all)
        h_quick.addWidget(self.btn_desel_all)
        h_quick.addWidget(self.btn_add_to_merge)
        left_layout.addLayout(h_quick)

        self.lbl_grid_info = QLabel()
        self.lbl_grid_info.setStyleSheet("color: #6b7280; font-size: 11px;")
        left_layout.addWidget(self.lbl_grid_info)

        # Lưới chứa các trang
        self.list_thumbnails = QListWidget()
        self.list_thumbnails.setViewMode(QListWidget.ViewMode.IconMode)
        self.list_thumbnails.setIconSize(QSize(120, 150))
        self.list_thumbnails.setGridSize(QSize(150, 190))
        self.list_thumbnails.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list_thumbnails.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_thumbnails.itemDoubleClicked.connect(self.on_thumbnail_double_click)
        left_layout.addWidget(self.list_thumbnails)

        splitter.addWidget(left_widget)

        # --- PANEL BÊN PHẢI: DANH SÁCH THỨ TỰ TRANG SẼ GHÉP ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 5, 5, 5)

        self.lbl_target_header = QLabel()
        self.lbl_target_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #1e3a8a;")
        right_layout.addWidget(self.lbl_target_header)

        # Control buttons
        h_reorder = QHBoxLayout()
        self.btn_up = QPushButton()
        self.btn_up.clicked.connect(self.on_move_item_up)

        self.btn_down = QPushButton()
        self.btn_down.clicked.connect(self.on_move_item_down)

        self.btn_remove_item = QPushButton()
        self.btn_remove_item.clicked.connect(self.on_remove_merge_item)

        self.btn_clear_queue = QPushButton()
        self.btn_clear_queue.clicked.connect(self.on_clear_merge_queue)

        h_reorder.addWidget(self.btn_up)
        h_reorder.addWidget(self.btn_down)
        h_reorder.addWidget(self.btn_remove_item)
        h_reorder.addWidget(self.btn_clear_queue)
        right_layout.addLayout(h_reorder)

        # Quick Range Adding Input
        h_quick_range = QHBoxLayout()
        self.txt_quick_range = QLineEdit()
        self.btn_add_range = QPushButton()
        self.btn_add_range.clicked.connect(self.on_add_quick_range)
        h_quick_range.addWidget(self.txt_quick_range, stretch=1)
        h_quick_range.addWidget(self.btn_add_range)
        right_layout.addLayout(h_quick_range)

        # List Widget hiển thị danh sách trang theo thứ tự ghép
        self.list_merge_queue = QListWidget()
        self.list_merge_queue.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_merge_queue.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        right_layout.addWidget(self.list_merge_queue)

        # Group Cấu hình thư mục lưu & tên file đầu ra ghép
        self.group_merge_out = QGroupBox()
        group_merge_out_layout = QVBoxLayout(self.group_merge_out)

        h_merge_outdir = QHBoxLayout()
        self.lbl_merge_outdir = QLabel()
        self.txt_merge_outdir = QLineEdit(os.path.join(os.path.expanduser("~"), "Desktop", "PDF_Ghep"))
        self.btn_browse_merge_dir = QPushButton()
        self.btn_browse_merge_dir.clicked.connect(self.on_browse_merge_outdir)
        h_merge_outdir.addWidget(self.lbl_merge_outdir)
        h_merge_outdir.addWidget(self.txt_merge_outdir, stretch=1)
        h_merge_outdir.addWidget(self.btn_browse_merge_dir)
        group_merge_out_layout.addLayout(h_merge_outdir)

        h_merge_filename = QHBoxLayout()
        self.lbl_merge_filename = QLabel()
        self.txt_merge_filename = QLineEdit("PDF_Ghep_KetQua.pdf")
        h_merge_filename.addWidget(self.lbl_merge_filename)
        h_merge_filename.addWidget(self.txt_merge_filename, stretch=1)
        group_merge_out_layout.addLayout(h_merge_filename)

        right_layout.addWidget(self.group_merge_out)

        # Progress bar ghép
        self.progress_merge = QProgressBar()
        self.progress_merge.setValue(0)
        right_layout.addWidget(self.progress_merge)

        self.lbl_merge_status = QLabel()
        self.lbl_merge_status.setStyleSheet("font-weight: bold; color: #1f2937;")
        right_layout.addWidget(self.lbl_merge_status)

        h_btn_merge_act = QHBoxLayout()
        self.btn_run_merge = QPushButton()
        self.btn_run_merge.setObjectName("accentBtn")
        self.btn_run_merge.setMinimumHeight(45)
        self.btn_run_merge.clicked.connect(self.on_run_merge)

        self.btn_open_merge_dir = QPushButton()
        self.btn_open_merge_dir.setMinimumHeight(45)
        self.btn_open_merge_dir.setEnabled(False)
        self.btn_open_merge_dir.clicked.connect(self.on_open_merge_dir)

        h_btn_merge_act.addWidget(self.btn_run_merge, stretch=2)
        h_btn_merge_act.addWidget(self.btn_open_merge_dir, stretch=1)
        right_layout.addLayout(h_btn_merge_act)

        splitter.addWidget(right_widget)
        splitter.setSizes([650, 450])

        layout.addWidget(splitter)

    # --- CHUYỂN ĐỔI NGÔN NGỮ (I18N RETRANSLATION) ---
    def on_language_changed(self):
        selected_lang = self.cmb_language.currentData()
        if selected_lang and selected_lang != self.current_lang:
            self.current_lang = selected_lang
            self.retranslate_ui()

    def retranslate_ui(self):
        c = self.current_lang
        self.setWindowTitle(tr(c, "window_title"))
        self.lbl_lang.setText(tr(c, "lang_label"))
        self.file_group.setTitle(tr(c, "file_group_title"))
        self.btn_add_files.setText(tr(c, "btn_add_files"))
        self.btn_add_folder.setText(tr(c, "btn_add_folder"))
        self.btn_remove_file.setText(tr(c, "btn_remove_file"))
        self.btn_clear_all.setText(tr(c, "btn_clear_all"))

        headers = [
            tr(c, "col_stt"), tr(c, "col_filename"), tr(c, "col_pages"),
            tr(c, "col_size"), tr(c, "col_path")
        ]
        self.table_files.setHorizontalHeaderLabels(headers)

        self.tabs.setTabText(0, tr(c, "tab_split"))
        self.tabs.setTabText(1, tr(c, "tab_merge"))

        # Tab Split
        self.group_out.setTitle(tr(c, "split_config_group"))
        self.lbl_out_dir.setText(tr(c, "lbl_out_dir"))
        self.btn_browse_dir.setText(tr(c, "btn_browse"))
        self.lbl_pattern.setText(tr(c, "lbl_pattern"))
        self.lbl_pattern_hint.setText(tr(c, "lbl_pattern_hint"))
        self.chk_create_subfolder.setText(tr(c, "chk_subfolder"))

        self.group_range.setTitle(tr(c, "split_range_group"))
        self.radio_split_all.setText(tr(c, "radio_split_all"))
        self.radio_split_custom.setText(tr(c, "radio_split_custom"))
        self.txt_split_range.setPlaceholderText(tr(c, "placeholder_split_range"))

        self.lbl_split_status.setText(tr(c, "lbl_status_ready"))
        self.btn_run_split.setText(tr(c, "btn_run_split"))
        self.btn_open_split_dir.setText(tr(c, "btn_open_split_dir"))

        # Tab Merge
        self.lbl_filter_file.setText(tr(c, "lbl_filter_file"))
        self.btn_sel_all.setText(tr(c, "btn_sel_all"))
        self.btn_desel_all.setText(tr(c, "btn_desel_all"))
        self.btn_add_to_merge.setText(tr(c, "btn_add_to_merge"))
        self.lbl_grid_info.setText(tr(c, "lbl_grid_info"))

        self.lbl_target_header.setText(tr(c, "lbl_target_header"))
        self.btn_up.setText(tr(c, "btn_up"))
        self.btn_down.setText(tr(c, "btn_down"))
        self.btn_remove_item.setText(tr(c, "btn_remove_item"))
        self.btn_clear_queue.setText(tr(c, "btn_clear_queue"))
        self.txt_quick_range.setPlaceholderText(tr(c, "placeholder_quick_range"))
        self.btn_add_range.setText(tr(c, "btn_add_range"))
        self.group_merge_out.setTitle(tr(c, "merge_config_group"))
        self.lbl_merge_outdir.setText(tr(c, "lbl_merge_outdir"))
        self.btn_browse_merge_dir.setText(tr(c, "btn_browse"))
        self.lbl_merge_filename.setText(tr(c, "lbl_merge_filename"))
        self.lbl_merge_status.setText(tr(c, "lbl_status_merge_ready"))
        self.btn_run_merge.setText(tr(c, "btn_run_merge"))
        self.btn_open_merge_dir.setText(tr(c, "btn_open_merge_dir"))

        self.update_file_table()
        self.refresh_pdf_combobox()

    # --- DRAG & DROP HANDLERS ---
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        files_to_add = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path) and path.lower().endswith(".pdf"):
                files_to_add.append(path)
            elif os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for f in files:
                        if f.lower().endswith(".pdf"):
                            files_to_add.append(os.path.join(root, f))
        if files_to_add:
            self.load_pdf_files(files_to_add)

    # --- SỰ KIỆN NẠP FILE PDF ---
    def on_add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr(self.current_lang, "btn_add_files"), "", "File PDF (*.pdf)")
        if files:
            self.load_pdf_files(files)

    def on_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr(self.current_lang, "btn_add_folder"))
        if folder:
            pdf_files = []
            for root, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith(".pdf"):
                        pdf_files.append(os.path.join(root, f))
            if pdf_files:
                self.load_pdf_files(pdf_files)
            else:
                QMessageBox.information(self, tr(self.current_lang, "msg_info"), tr(self.current_lang, "msg_no_pdf_in_folder"))

    def load_pdf_files(self, file_paths):
        existing_paths = {f["path"] for f in self.loaded_files}
        new_added = 0

        for path in file_paths:
            if path in existing_paths:
                continue
            try:
                info = get_pdf_info(path)
                self.loaded_files.append(info)
                existing_paths.add(path)
                new_added += 1
            except Exception as e:
                print(f"Error loading file {path}: {e}")

        if new_added > 0:
            self.update_file_table()
            self.refresh_pdf_combobox()
            self.start_loading_thumbnails()

    def update_file_table(self):
        self.table_files.setRowCount(len(self.loaded_files))
        total_pages = sum(f["page_count"] for f in self.loaded_files)

        for row, info in enumerate(self.loaded_files):
            self.table_files.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self.table_files.setItem(row, 1, QTableWidgetItem(info["filename"]))
            self.table_files.setItem(row, 2, QTableWidgetItem(str(info["page_count"])))
            self.table_files.setItem(row, 3, QTableWidgetItem(info["size_str"]))
            self.table_files.setItem(row, 4, QTableWidgetItem(info["path"]))

        if self.loaded_files:
            summary = tr(self.current_lang, "file_summary", count=len(self.loaded_files), pages=total_pages)
        else:
            summary = tr(self.current_lang, "lbl_no_files")
        self.lbl_file_summary.setText(summary)

    def refresh_pdf_combobox(self):
        self.cmb_filter_pdf.blockSignals(True)
        self.cmb_filter_pdf.clear()
        self.cmb_filter_pdf.addItem(tr(self.current_lang, "filter_all"), None)
        for info in self.loaded_files:
            self.cmb_filter_pdf.addItem(info["filename"], info["path"])
        self.cmb_filter_pdf.blockSignals(False)

    def on_remove_selected_file(self):
        selected_rows = sorted(set(index.row() for index in self.table_files.selectedIndexes()), reverse=True)
        if not selected_rows:
            return
        for r in selected_rows:
            if r < len(self.loaded_files):
                del self.loaded_files[r]

        self.update_file_table()
        self.refresh_pdf_combobox()
        self.reload_thumbnails_grid()

    def on_clear_all_files(self):
        self.loaded_files.clear()
        self.thumbnail_cache.clear()
        self.update_file_table()
        self.refresh_pdf_combobox()
        self.list_thumbnails.clear()
        self.list_merge_queue.clear()

    # --- THUMBNAIL RENDERER LOGIC ---
    def start_loading_thumbnails(self):
        self.list_thumbnails.clear()
        c = self.current_lang
        page_str = tr(c, "page_str")

        for info in self.loaded_files:
            pdf_path = info["path"]
            filename = info["filename"]
            for idx in range(info["page_count"]):
                item = QListWidgetItem()
                item.setText(f"{filename}\n{page_str} {idx + 1}")
                item.setData(Qt.ItemDataRole.UserRole, (pdf_path, idx))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)

                if (pdf_path, idx) in self.thumbnail_cache:
                    item.setIcon(QIcon(self.thumbnail_cache[(pdf_path, idx)]))
                self.list_thumbnails.addItem(item)

        self.thumb_worker = ThumbnailWorker(self.loaded_files)
        self.thumb_worker.thumbnail_loaded.connect(self.on_thumbnail_single_loaded)
        self.thumb_worker.start()

    def on_thumbnail_single_loaded(self, pdf_path, page_idx, img_bytes):
        pixmap = QPixmap()
        pixmap.loadFromData(img_bytes)
        self.thumbnail_cache[(pdf_path, page_idx)] = pixmap

        for i in range(self.list_thumbnails.count()):
            item = self.list_thumbnails.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data == (pdf_path, page_idx):
                item.setIcon(QIcon(pixmap))
                break

    def reload_thumbnails_grid(self):
        selected_filter_path = self.cmb_filter_pdf.currentData()
        self.list_thumbnails.clear()
        page_str = tr(self.current_lang, "page_str")

        for info in self.loaded_files:
            pdf_path = info["path"]
            if selected_filter_path and pdf_path != selected_filter_path:
                continue

            filename = info["filename"]
            for idx in range(info["page_count"]):
                item = QListWidgetItem()
                item.setText(f"{filename}\n{page_str} {idx + 1}")
                item.setData(Qt.ItemDataRole.UserRole, (pdf_path, idx))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)

                if (pdf_path, idx) in self.thumbnail_cache:
                    item.setIcon(QIcon(self.thumbnail_cache[(pdf_path, idx)]))
                self.list_thumbnails.addItem(item)

    def on_filter_pdf_changed(self):
        self.reload_thumbnails_grid()

    # --- THAO TÁC LƯỚI THUMBNAIL ---
    def on_select_all_thumbnails(self):
        for i in range(self.list_thumbnails.count()):
            self.list_thumbnails.item(i).setCheckState(Qt.CheckState.Checked)

    def on_deselect_all_thumbnails(self):
        for i in range(self.list_thumbnails.count()):
            self.list_thumbnails.item(i).setCheckState(Qt.CheckState.Unchecked)

    def on_thumbnail_double_click(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            pdf_path, page_idx = data
            dlg = PagePreviewDialog(pdf_path, page_idx, lang_code=self.current_lang, parent=self)
            dlg.exec()

    def on_add_selected_thumbnails_to_queue(self):
        added_count = 0
        page_str = tr(self.current_lang, "page_str")

        for i in range(self.list_thumbnails.count()):
            item = self.list_thumbnails.item(i)
            if item.checkState() == Qt.CheckState.Checked or item.isSelected():
                pdf_path, page_idx = item.data(Qt.ItemDataRole.UserRole)
                filename = os.path.basename(pdf_path)

                q_item = QListWidgetItem()
                q_item.setText(f"📄 {filename} - {page_str} {page_idx + 1}")
                q_item.setData(Qt.ItemDataRole.UserRole, {"pdf_path": pdf_path, "page_index": page_idx})

                if (pdf_path, page_idx) in self.thumbnail_cache:
                    q_item.setIcon(QIcon(self.thumbnail_cache[(pdf_path, page_idx)]))

                self.list_merge_queue.addItem(q_item)
                added_count += 1

        if added_count == 0:
            QMessageBox.information(self, tr(self.current_lang, "msg_info"), tr(self.current_lang, "msg_merge_empty"))

    # --- THAO TÁC MERGE QUEUE ---
    def on_move_item_up(self):
        currentRow = self.list_merge_queue.currentRow()
        if currentRow > 0:
            currentItem = self.list_merge_queue.takeItem(currentRow)
            self.list_merge_queue.insertItem(currentRow - 1, currentItem)
            self.list_merge_queue.setCurrentRow(currentRow - 1)

    def on_move_item_down(self):
        currentRow = self.list_merge_queue.currentRow()
        if currentRow < self.list_merge_queue.count() - 1 and currentRow != -1:
            currentItem = self.list_merge_queue.takeItem(currentRow)
            self.list_merge_queue.insertItem(currentRow + 1, currentItem)
            self.list_merge_queue.setCurrentRow(currentRow + 1)

    def on_remove_merge_item(self):
        for item in self.list_merge_queue.selectedItems():
            self.list_merge_queue.takeItem(self.list_merge_queue.row(item))

    def on_clear_merge_queue(self):
        self.list_merge_queue.clear()

    def on_add_quick_range(self):
        range_text = self.txt_quick_range.text().strip()
        selected_pdf_path = self.cmb_filter_pdf.currentData()
        c = self.current_lang

        if not range_text:
            QMessageBox.warning(self, tr(c, "msg_warning"), "Vui lòng nhập phạm vi trang / Please enter a page range.")
            return

        target_file = None
        if selected_pdf_path:
            for f in self.loaded_files:
                if f["path"] == selected_pdf_path:
                    target_file = f
                    break
        elif self.loaded_files:
            target_file = self.loaded_files[0]

        if not target_file:
            QMessageBox.warning(self, tr(c, "msg_warning"), tr(c, "msg_select_pdf_split"))
            return

        pages = parse_page_range_string(range_text, target_file["page_count"])
        pdf_path = target_file["path"]
        filename = target_file["filename"]
        page_str = tr(c, "page_str")

        for p_idx in pages:
            q_item = QListWidgetItem()
            q_item.setText(f"📄 {filename} - {page_str} {p_idx + 1}")
            q_item.setData(Qt.ItemDataRole.UserRole, {"pdf_path": pdf_path, "page_index": p_idx})

            if (pdf_path, p_idx) in self.thumbnail_cache:
                q_item.setIcon(QIcon(self.thumbnail_cache[(pdf_path, p_idx)]))
            self.list_merge_queue.addItem(q_item)

        self.txt_quick_range.clear()

    # --- SỰ KIỆN TÁCH TRANG ---
    def on_browse_split_outdir(self):
        dir_path = QFileDialog.getExistingDirectory(self, tr(self.current_lang, "lbl_out_dir"))
        if dir_path:
            self.txt_split_outdir.setText(dir_path)

    def on_run_split(self):
        c = self.current_lang
        if not self.loaded_files:
            QMessageBox.warning(self, tr(c, "msg_warning"), tr(c, "msg_select_pdf_split"))
            return

        output_dir = self.txt_split_outdir.text().strip()
        if not output_dir:
            QMessageBox.warning(self, tr(c, "msg_warning"), tr(c, "msg_select_outdir"))
            return

        pattern = self.txt_split_pattern.text().strip()
        if not pattern:
            pattern = "{name}_trang_{page}.pdf"

        range_str = self.txt_split_range.text().strip() if self.radio_split_custom.isChecked() else ""
        create_subfolder = self.chk_create_subfolder.isChecked()

        self.btn_run_split.setEnabled(False)
        self.progress_split.setValue(0)
        self.lbl_split_status.setText(tr(c, "status_splitting"))

        self.split_worker = SplitWorker(
            pdf_files=self.loaded_files,
            output_dir=output_dir,
            file_pattern=pattern,
            range_str=range_str,
            create_subfolder=create_subfolder
        )
        self.split_worker.progress.connect(self.on_split_progress)
        self.split_worker.finished.connect(self.on_split_finished)
        self.split_worker.error.connect(self.on_split_error)
        self.split_worker.start()

    def on_split_progress(self, cur, total, name):
        percent = int((cur / total) * 100) if total > 0 else 0
        self.progress_split.setValue(percent)
        self.lbl_split_status.setText(f"Exporting: {name} ({cur}/{total})")

    def on_split_finished(self, created_files, out_dir):
        c = self.current_lang
        self.btn_run_split.setEnabled(True)
        self.btn_open_split_dir.setEnabled(True)
        self.progress_split.setValue(100)
        
        msg_str = tr(c, "msg_split_complete", count=len(created_files), dir=out_dir)
        self.lbl_split_status.setText(f"✅ {msg_str.splitlines()[0]}")

        QMessageBox.information(self, tr(c, "msg_success"), msg_str)

    def on_split_error(self, err_msg):
        c = self.current_lang
        self.btn_run_split.setEnabled(True)
        self.lbl_split_status.setText(f"❌ Error: {err_msg}")
        QMessageBox.critical(self, tr(c, "msg_error"), f"Split failed: {err_msg}")

    def on_open_split_dir(self):
        out_dir = self.txt_split_outdir.text().strip()
        if os.path.exists(out_dir):
            os.startfile(out_dir)
        else:
            QMessageBox.warning(self, tr(self.current_lang, "msg_warning"), "Thư mục đầu ra chưa được tạo!")

    # --- SỰ KIỆN GHÉP TRANG ---
    def on_browse_merge_outdir(self):
        dir_path = QFileDialog.getExistingDirectory(self, tr(self.current_lang, "lbl_out_dir"))
        if dir_path:
            self.txt_merge_outdir.setText(dir_path)

    def on_open_merge_dir(self):
        out_dir = self.txt_merge_outdir.text().strip()
        if os.path.exists(out_dir):
            os.startfile(out_dir)
        else:
            QMessageBox.warning(self, tr(self.current_lang, "msg_warning"), "Thư mục đầu ra chưa được tạo!")

    def on_run_merge(self):
        c = self.current_lang
        if self.list_merge_queue.count() == 0:
            QMessageBox.warning(self, tr(c, "msg_warning"), tr(c, "msg_merge_empty"))
            return

        out_dir = self.txt_merge_outdir.text().strip()
        if not out_dir:
            QMessageBox.warning(self, tr(c, "msg_warning"), tr(c, "msg_select_outdir"))
            return

        filename = self.txt_merge_filename.text().strip()
        if not filename:
            filename = "PDF_Ghep_KetQua.pdf"

        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        out_path = os.path.join(out_dir, filename)

        page_items = []
        for i in range(self.list_merge_queue.count()):
            data = self.list_merge_queue.item(i).data(Qt.ItemDataRole.UserRole)
            page_items.append(data)

        self.btn_run_merge.setEnabled(False)
        self.progress_merge.setValue(0)
        self.lbl_merge_status.setText(tr(c, "status_merging"))

        self.merge_worker = MergeWorker(page_items, out_path)
        self.merge_worker.progress.connect(self.on_merge_progress)
        self.merge_worker.finished.connect(self.on_merge_finished)
        self.merge_worker.error.connect(self.on_merge_error)
        self.merge_worker.start()

    def on_merge_progress(self, cur, total, msg):
        percent = int((cur / total) * 100) if total > 0 else 0
        self.progress_merge.setValue(percent)
        self.lbl_merge_status.setText(f"Merging ({cur}/{total}): {msg}")

    def on_merge_finished(self, out_path):
        c = self.current_lang
        self.btn_run_merge.setEnabled(True)
        self.btn_open_merge_dir.setEnabled(True)
        self.progress_merge.setValue(100)
        
        msg_str = tr(c, "msg_merge_complete", count=self.list_merge_queue.count(), path=out_path)
        self.lbl_merge_status.setText(f"✅ {msg_str.splitlines()[0]}")

        reply = QMessageBox.question(
            self, tr(c, "msg_success"), msg_str,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            os.startfile(out_path)

    def on_merge_error(self, err_msg):
        c = self.current_lang
        self.btn_run_merge.setEnabled(True)
        self.lbl_merge_status.setText(f"❌ Error: {err_msg}")
        QMessageBox.critical(self, tr(c, "msg_error"), f"Merge failed: {err_msg}")

    # --- GIAO DIỆN STYLESHEET ---
    def apply_stylesheet(self):
        style = """
        QMainWindow {
            background-color: #f8fafc;
        }
        QWidget {
            font-family: 'Segoe UI', Arial, sans-serif;
            font-size: 13px;
            color: #1e293b;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            margin-top: 8px;
            padding-top: 14px;
            background-color: #ffffff;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 5px;
            color: #2563eb;
        }
        QPushButton {
            background-color: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 6px 14px;
            font-weight: 500;
        }
        QPushButton:hover {
            background-color: #f1f5f9;
            border-color: #94a3b8;
        }
        QPushButton#primaryBtn {
            background-color: #2563eb;
            color: #ffffff;
            border: none;
            font-weight: bold;
        }
        QPushButton#primaryBtn:hover {
            background-color: #1d4ed8;
        }
        QPushButton#accentBtn {
            background-color: #059669;
            color: #ffffff;
            border: none;
            font-size: 14px;
            font-weight: bold;
            border-radius: 8px;
        }
        QPushButton#accentBtn:hover {
            background-color: #047857;
        }
        QTableWidget, QListWidget {
            background-color: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            gridline-color: #f1f5f9;
        }
        QHeaderView::section {
            background-color: #f1f5f9;
            padding: 6px;
            border: none;
            font-weight: bold;
            color: #475569;
        }
        QLineEdit {
            background-color: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 6px;
        }
        QLineEdit:focus {
            border-color: #2563eb;
        }
        QTabWidget::pane {
            border: 1px solid #cbd5e1;
            background-color: #ffffff;
            border-radius: 8px;
        }
        QTabBar::tab {
            background-color: #e2e8f0;
            padding: 10px 20px;
            font-weight: bold;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            margin-right: 2px;
            color: #475569;
        }
        QTabBar::tab:selected {
            background-color: #ffffff;
            color: #2563eb;
            border-bottom: 3px solid #2563eb;
        }
        QProgressBar {
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            text-align: center;
            height: 20px;
            background-color: #f1f5f9;
        }
        QProgressBar::chunk {
            background-color: #2563eb;
            border-radius: 5px;
        }
        /* Style thông báo QMessageBox rõ ràng, tương phản sắc nét */
        QDialog, QMessageBox {
            background-color: #ffffff;
            color: #0f172a;
        }
        QMessageBox QLabel {
            color: #0f172a;
            font-size: 13px;
            font-weight: 500;
            background-color: transparent;
        }
        QMessageBox QPushButton {
            background-color: #2563eb;
            color: #ffffff;
            border: none;
            border-radius: 6px;
            padding: 7px 20px;
            font-weight: bold;
            min-width: 75px;
        }
        QMessageBox QPushButton:hover {
            background-color: #1d4ed8;
        }
        /* Style QComboBox chung và Nút Switch Ngôn ngữ riêng biệt */
        QComboBox {
            background-color: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 5px 10px;
            color: #1e293b;
        }
        QComboBox:hover {
            border-color: #2563eb;
        }
        QComboBox QAbstractItemView {
            background-color: #ffffff;
            border: 1px solid #cbd5e1;
            selection-background-color: #2563eb;
            selection-color: #ffffff;
            color: #1e293b;
            padding: 4px;
        }
        QComboBox#langSwitcher {
            background-color: #f0f9ff;
            border: 2px solid #38bdf8;
            border-radius: 8px;
            padding: 4px 14px;
            font-weight: bold;
            color: #0369a1;
            min-width: 125px;
        }
        QComboBox#langSwitcher:hover {
            background-color: #e0f2fe;
            border-color: #0284c7;
        }
        QComboBox#langSwitcher QAbstractItemView {
            background-color: #ffffff;
            border: 2px solid #38bdf8;
            selection-background-color: #0284c7;
            selection-color: #ffffff;
            color: #0369a1;
            font-weight: bold;
        }
        """
        self.setStyleSheet(style)


