import getpass
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

from app.widgets.module_card import ModuleCard


class HomePage(QWidget):

    navigate_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.build_ui()

    def build_ui(self):

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)

        # =========================
        # 滚动区域
        # =========================

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()

        root = QVBoxLayout(container)

        root.setContentsMargins(
            28,
            24,
            28,
            24,
        )

        root.setSpacing(16)

        # =========================
        # 顶部欢迎区
        # =========================

        header = QHBoxLayout()

        title_box = QVBoxLayout()
        title_box.setSpacing(4)

        username = getpass.getuser()

        hour = datetime.now().hour

        if hour < 12:
            greeting = "上午好"
        elif hour < 18:
            greeting = "下午好"
        else:
            greeting = "晚上好"

        title = QLabel(
            f"{greeting}，{username}！"
        )

        title.setObjectName("PageTitle")

        today = datetime.now().strftime(
            "%Y-%m-%d"
        )

        subtitle = QLabel(
            f"今天是 {today}，请选择需要处理的工作"
        )

        subtitle.setObjectName("PageSubtitle")

        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        header.addLayout(title_box)
        header.addStretch()

        root.addLayout(header)

        # =========================
        # 主业务卡片
        # =========================

        cards = QGridLayout()

        cards.setHorizontalSpacing(14)
        cards.setVerticalSpacing(14)

        inquiry_card = ModuleCard(
            route="inquiry",
            icon_text="询",
            title="询价中心",
            description="扫描询价明细，生成物流询价汇总表",
            button_text="进入询价中心",
            main_color="#16A765",
            light_color="#E7F7EF",
            stats=[
                ("今日扫描", "—"),
                ("文件", "—"),
                ("仓库", "—"),
                ("上次", "—"),
            ],
        )

        invoice_card = ModuleCard(
            route="invoice",
            icon_text="票",
            title="发票中心",
            description="处理当前 Batch，完成扫描与发票合并",
            button_text="进入发票中心",
            main_color="#1677FF",
            light_color="#EAF2FF",
            stats=[
                ("进行中", "—"),
                ("今日完成", "—"),
                ("异常", "—"),
                ("待处理", "—"),
            ],
        )

        edit_card = ModuleCard(
            route="batch_edit",
            icon_text="改",
            title="批量修改单元格值",
            description="批量修改 Excel 指定单元格，主要用于更改发货渠道",
            button_text="打开批量修改",
            main_color="#F58A07",
            light_color="#FFF3E3",
            stats=[
                ("今日修改", "—"),
                ("成功", "—"),
                ("失败", "—"),
                ("最近", "—"),
            ],
        )

        sensitive_card = ModuleCard(
            route="sensitive",
            icon_text="检",
            title="敏感词检查",
            description="检查产品品名及材质中的物流敏感词",
            button_text="开始敏感词检查",
            main_color="#D64B6A",
            light_color="#FCECF1",
            stats=[
                ("今日扫描", "—"),
                ("命中", "—"),
                ("文件", "—"),
                ("词库", "CURRENT"),
            ],
        )

        maintain_card = ModuleCard(
            route="maintain",
            icon_text="维",
            title="维护",
            description="打开需要人工维护的中央文件，例如各物流地址库",
            button_text="进入维护",
            main_color="#5B6B8A",
            light_color="#EEF1F6",
            stats=[
                ("地址库", "1"),
                ("模板", "—"),
                ("词库", "—"),
                ("其他", "—"),
            ],
        )

        module_cards = [
            inquiry_card,
            invoice_card,
            edit_card,
            sensitive_card,
            maintain_card,
        ]

        for card in module_cards:
            card.clicked.connect(
                self.navigate_requested
            )

        cards.addWidget(
            inquiry_card,
            0,
            0,
        )

        cards.addWidget(
            invoice_card,
            0,
            1,
        )

        cards.addWidget(
            edit_card,
            0,
            2,
        )

        cards.addWidget(
            sensitive_card,
            0,
            3,
        )

        cards.addWidget(
            maintain_card,
            1,
            0,
        )

        for column in range(4):
            cards.setColumnStretch(
                column,
                1,
            )

        root.addLayout(cards)

        # =========================
        # 下方区域
        # =========================

        lower = QHBoxLayout()
        lower.setSpacing(14)

        current_task = (
            self.build_current_task()
        )

        recent_actions = (
            self.build_recent_actions()
        )

        quick_start = (
            self.build_quick_start()
        )

        lower.addWidget(
            current_task,
            4,
        )

        lower.addWidget(
            recent_actions,
            5,
        )

        lower.addWidget(
            quick_start,
            3,
        )

        root.addLayout(lower)

        # =========================
        # 提示区
        # =========================

        tips = QFrame()
        tips.setObjectName("Card")

        tips_layout = QHBoxLayout(tips)

        tips_layout.setContentsMargins(
            16,
            11,
            16,
            11,
        )

        tips_icon = QLabel("💡")

        tips_text = QLabel(
            "正常工作时直接进入对应模块即可。"
            "系统会根据当前处理状态提示下一步操作，"
            "只有出现异常时才需要查看详细信息。"
        )

        tips_text.setObjectName(
            "SecondaryText"
        )

        tips_layout.addWidget(
            tips_icon
        )

        tips_layout.addWidget(
            tips_text,
            1,
        )

        root.addWidget(tips)

        root.addStretch()

        scroll.setWidget(container)

        page_layout.addWidget(scroll)

    # =========================================================
    # 当前任务
    # =========================================================

    def build_current_task(self):

        frame = QFrame()
        frame.setObjectName("Card")

        layout = QVBoxLayout(frame)

        layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )

        layout.setSpacing(11)

        title = QLabel("当前正在处理")
        title.setObjectName("CardTitle")

        layout.addWidget(title)

        divider = QFrame()
        divider.setFrameShape(
            QFrame.HLine
        )

        divider.setStyleSheet(
            "color:#EEF1F5;"
        )

        layout.addWidget(divider)

        empty_title = QLabel(
            "当前没有正在处理的 Batch"
        )

        empty_title.setStyleSheet(
            """
            font-size: 15px;
            font-weight: 600;
            color: #374151;
            """
        )

        description = QLabel(
            "进入发票中心后，系统会自动识别"
            "当天未完成的 Batch；如果没有，"
            "可以开始新的处理批次。"
        )

        description.setWordWrap(True)

        description.setObjectName(
            "SecondaryText"
        )

        layout.addWidget(empty_title)
        layout.addWidget(description)

        layout.addStretch()

        button = QPushButton(
            "进入发票中心"
        )

        button.setObjectName(
            "SecondaryButton"
        )

        button.clicked.connect(
            lambda:
            self.navigate_requested.emit(
                "invoice"
            )
        )

        layout.addWidget(button)

        return frame

    # =========================================================
    # 最近操作
    # =========================================================

    def build_recent_actions(self):

        frame = QFrame()
        frame.setObjectName("Card")

        layout = QVBoxLayout(frame)

        layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )

        layout.setSpacing(10)

        title_row = QHBoxLayout()

        title = QLabel(
            "最近操作记录"
        )

        title.setObjectName(
            "CardTitle"
        )

        title_row.addWidget(title)
        title_row.addStretch()

        layout.addLayout(title_row)

        table = QTableWidget()

        table.setColumnCount(4)

        table.setHorizontalHeaderLabels(
            [
                "时间",
                "模块",
                "操作内容",
                "状态",
            ]
        )

        table.setRowCount(1)

        table.setItem(
            0,
            0,
            QTableWidgetItem("—"),
        )

        table.setItem(
            0,
            1,
            QTableWidgetItem("—"),
        )

        table.setItem(
            0,
            2,
            QTableWidgetItem(
                "暂无操作记录"
            ),
        )

        table.setItem(
            0,
            3,
            QTableWidgetItem("—"),
        )

        table.setEditTriggers(
            QTableWidget.NoEditTriggers
        )

        table.setSelectionBehavior(
            QTableWidget.SelectRows
        )

        table.verticalHeader().setVisible(
            False
        )

        table.horizontalHeader().setSectionResizeMode(
            2,
            QHeaderView.Stretch,
        )

        table.setMinimumHeight(215)

        layout.addWidget(table)

        return frame

    # =========================================================
    # 快速开始
    # =========================================================

    def build_quick_start(self):

        frame = QFrame()
        frame.setObjectName("Card")

        layout = QVBoxLayout(frame)

        layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )

        layout.setSpacing(0)

        title = QLabel(
            "快速开始"
        )

        title.setObjectName(
            "CardTitle"
        )

        layout.addWidget(title)

        layout.addSpacing(8)

        actions = [
            (
                "生成今天的询价汇总",
                "inquiry",
            ),
            (
                "继续当前发票 Batch",
                "invoice",
            ),
            (
                "批量更改发货渠道",
                "batch_edit",
            ),
            (
                "检查敏感词",
                "sensitive",
            ),
            (
                "维护各物流地址库",
                "maintain",
            ),
        ]

        for text, route in actions:

            button = QPushButton(
                f"{text}   ›"
            )

            button.setCursor(
                Qt.PointingHandCursor
            )

            button.setStyleSheet(
                """
                QPushButton {
                    text-align: left;
                    background: white;
                    border: none;
                    border-bottom:
                        1px solid #EEF1F5;
                    padding: 14px 5px;
                    font-size: 13px;
                    color: #374151;
                }

                QPushButton:hover {
                    background: #F7FAFF;
                    color: #1677FF;
                }
                """
            )

            button.clicked.connect(
                lambda checked=False, r=route:
                self.navigate_requested.emit(r)
            )

            layout.addWidget(button)

        layout.addStretch()

        return frame