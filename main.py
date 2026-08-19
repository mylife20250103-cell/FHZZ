import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.app_logging import setup_logging
from app.main_window import MainWindow
from app.styles import APP_STYLE


def main():
    setup_logging()
    app = QApplication(sys.argv)

    app.setApplicationName("发票合并系统")
    app.setApplicationVersion("1.0.0")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(APP_STYLE)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()