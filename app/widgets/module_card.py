from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
)


class ModuleCard(QFrame):
    """
    首页业务模块卡片
    """

    clicked = Signal(str)

    def __init__(
        self,
        route: str,
        icon_text: str,
        title: str,
        description: str,
        button_text: str,
        main_color: str,
        light_color: str,
        stats=None,
        parent=None,
    ):
        super().__init__(parent)

        self.route = route

        self.setObjectName("ModuleCard")
        self.setMinimumHeight(225)

        if stats is None:
            stats = [
                ("今日", "—"),
                ("成功", "—"),
                ("异常", "—"),
                ("最近", "—"),
            ]

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(14)

        # =========================
        # 标题
        # =========================

        header = QHBoxLayout()
        header.setSpacing(12)

        icon = QLabel(icon_text)
        icon.setFixedSize(48, 48)
        icon.setAlignment(Qt.AlignCenter)

        icon.setStyleSheet(
            f"""
            QLabel {{
                background: {light_color};
                color: {main_color};
                border-radius: 10px;
                font-size: 20px;
                font-weight: 700;
            }}
            """
        )

        title_box = QVBoxLayout()
        title_box.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")

        description_label = QLabel(description)
        description_label.setObjectName("SecondaryText")
        description_label.setWordWrap(True)

        title_box.addWidget(title_label)
        title_box.addWidget(description_label)

        header.addWidget(icon)
        header.addLayout(title_box, 1)

        root.addLayout(header)

        # =========================
        # 统计数据
        # =========================

        stat_row = QHBoxLayout()
        stat_row.setSpacing(8)

        for name, value in stats:
            box = QVBoxLayout()
            box.setSpacing(3)

            name_label = QLabel(name)
            name_label.setObjectName("SecondaryText")

            value_label = QLabel(value)
            value_label.setStyleSheet(
                """
                font-size: 17px;
                font-weight: 700;
                color: #172033;
                """
            )

            box.addWidget(name_label)
            box.addWidget(value_label)

            stat_row.addLayout(box)

        root.addLayout(stat_row)

        root.addStretch()

        # =========================
        # 主按钮
        # =========================

        button = QPushButton(f"{button_text}  →")

        button.setCursor(Qt.PointingHandCursor)

        button.setStyleSheet(
            f"""
            QPushButton {{
                background: {main_color};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px;
                font-size: 14px;
                font-weight: 600;
            }}

            QPushButton:hover {{
                background: {main_color};
                border: 1px solid rgba(255,255,255,80);
            }}

            QPushButton:pressed {{
                padding-top: 11px;
            }}
            """
        )

        button.clicked.connect(
            lambda: self.clicked.emit(self.route)
        )

        root.addWidget(button)