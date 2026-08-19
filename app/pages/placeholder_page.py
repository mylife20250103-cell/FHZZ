from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
)


class PlaceholderPage(QWidget):
    """
    尚未正式开发的模块临时页面。
    后续询价中心、发票中心等完成后会逐个替换。
    """

    def __init__(
        self,
        title: str,
        description: str,
        parent=None,
    ):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        layout.setContentsMargins(
            50,
            50,
            50,
            50,
        )

        layout.addStretch()

        title_label = QLabel(title)

        title_label.setAlignment(
            Qt.AlignCenter
        )

        title_label.setStyleSheet(
            """
            font-size: 28px;
            font-weight: 700;
            color: #172033;
            """
        )

        description_label = QLabel(
            description
        )

        description_label.setAlignment(
            Qt.AlignCenter
        )

        description_label.setWordWrap(
            True
        )

        description_label.setStyleSheet(
            """
            font-size: 14px;
            color: #7B8496;
            margin-top: 10px;
            """
        )

        layout.addWidget(
            title_label
        )

        layout.addWidget(
            description_label
        )

        layout.addStretch()