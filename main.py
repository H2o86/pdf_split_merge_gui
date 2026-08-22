import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from ui_main_window import MainWindow, get_resource_path

def main():
    # Thiết lập AppUserModelID cho Windows để hiển thị icon chuẩn trên Taskbar
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("pdfsplittermerger.gui.1.0")
        except Exception:
            pass

    # Khởi tạo ứng dụng Qt
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    icon_path = get_resource_path(os.path.join("assets", "icon.ico"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # Tạo và hiển thị cửa sổ chính
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

