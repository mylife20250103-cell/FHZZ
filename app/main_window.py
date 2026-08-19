import getpass
import socket

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QStackedWidget,
)

from app.pages.home_page import HomePage
from app.pages.inquiry_page import InquiryPage
from app.pages.invoice_page import InvoicePage
from app.pages.batch_edit_page import BatchEditPage
from app.pages.sensitive_page import SensitivePage


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("发票合并系统 v1.0.0")
        self.resize(1550, 920)
        self.setMinimumSize(1250, 760)

        self.nav_buttons = {}
        self.pages = {}

        self.build_ui()
        self.go_to("home")

    def build_ui(self):

        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ==========================================
        # 左侧导航
        # ==========================================

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(215)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 18)
        sidebar_layout.setSpacing(5)

        title = QLabel("发票合并系统")
        title.setObjectName("AppTitle")

        version = QLabel("v1.0.0")
        version.setObjectName("AppVersion")

        sidebar_layout.addWidget(title)
        sidebar_layout.addWidget(version)
        sidebar_layout.addSpacing(20)

        nav_items = [
            ("home", "⌂  首页"),
            ("inquiry", "▤  询价中心"),
            ("invoice", "▧  发票中心"),
            ("batch_edit", "✎  批量修改单元格值"),
            ("sensitive", "⚠  敏感词检查"),
        ]

        for route, text in nav_items:

            button = QPushButton(text)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)

            button.clicked.connect(
                lambda checked=False, r=route: self.go_to(r)
            )

            sidebar_layout.addWidget(button)
            self.nav_buttons[route] = button

        sidebar_layout.addStretch()

        # ==========================================
        # 系统信息
        # ==========================================

        system_title = QLabel("系统信息")

        system_title.setStyleSheet(
            """
            font-size: 12px;
            font-weight: 700;
            color: #556070;
            """
        )

        username = getpass.getuser()
        computer = socket.gethostname()

        system_info = QLabel(
            f"当前用户：{username}\n"
            f"计算机：{computer}\n"
            f"版本号：v1.0.0"
        )

        system_info.setStyleSheet(
            """
            color: #7B8496;
            font-size: 11px;
            """
        )

        sidebar_layout.addWidget(system_title)
        sidebar_layout.addSpacing(8)
        sidebar_layout.addWidget(system_info)

        root.addWidget(sidebar)

        # ==========================================
        # 页面容器
        # ==========================================

        self.stack = QStackedWidget()

        # 首页：使用真正的 HomePage
        home_page = HomePage()

        home_page.navigate_requested.connect(
            self.go_to
        )

        self.pages["home"] = home_page

        # 后续模块暂时占位
        self.pages["inquiry"] = InquiryPage()

        self.pages["invoice"] = InvoicePage()
        self.pages["batch_edit"] = BatchEditPage()
        self.pages["sensitive"] = SensitivePage()

        for page in self.pages.values():
            self.stack.addWidget(page)

        root.addWidget(self.stack, 1)

    def go_to(self, route: str):

        page = self.pages.get(route)

        if page is None:
            return

        self.stack.setCurrentWidget(page)

        for name, button in self.nav_buttons.items():
            button.setChecked(name == route)