import sys
import os
from PyQt6.QtWidgets import QApplication
from ui_main_window import MainWindow

def main():
    # Khởi tạo ứng dụng Qt
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Tạo và hiển thị cửa sổ chính
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
