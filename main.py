import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.app_logging import setup_logging
from app.main_window import MainWindow
from app.styles import APP_STYLE
from app.version import APP_NAME, APP_VERSION


def main():
    setup_logging()
    app = QApplication(sys.argv)

    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(APP_STYLE)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()