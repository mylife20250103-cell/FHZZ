from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
)
from app.styles import METRIC_STYLE, PRIMARY_BUTTON_STYLE, SECONDARY_BUTTON_STYLE
from app.ui_icons import navigation_icon


class ModuleCard(QFrame):
    """
    首页业务模块卡片

    保留原有文本图标和配色参数以兼容页面调用，外观统一由主题和线性图标提供。
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
        self.setMinimumHeight(208)

        if stats is None:
            stats = [
                ("今日", "—"),
                ("成功", "—"),
                ("异常", "—"),
                ("最近", "—"),
            ]

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(12)

        # =========================
        # 标题
        # =========================

        header = QHBoxLayout()
        header.setSpacing(12)

        icon = QLabel(icon_text)
        icon.setFixedSize(38, 38)
        icon.setAlignment(Qt.AlignCenter)
        icon.setAccessibleName(title)
        icon.setPixmap(navigation_icon(route).pixmap(QSize(24, 24)))

        icon.setStyleSheet(
            "background:#F0F3F7; border:none; border-radius:9px;"
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
            value_label.setStyleSheet(METRIC_STYLE)

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
            PRIMARY_BUTTON_STYLE if route == "invoice" else SECONDARY_BUTTON_STYLE
        )

        button.clicked.connect(
            lambda: self.clicked.emit(self.route)
        )

        root.addWidget(button)
