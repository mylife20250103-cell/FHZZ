import getpass
import socket

from PySide6.QtCore import Qt, QSize
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
from app.pages.customs_page import CustomsPage
from app.pages.batch_edit_page import BatchEditPage
from app.pages.sensitive_page import SensitivePage
from app.pages.maintain_page import MaintainPage
from app.pages.tracking_page import TrackingPage
from app.pages.watchlist_page import WatchlistPage
from app.version import APP_NAME, APP_VERSION_LABEL
from app.ui_icons import navigation_icon


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle(f"{APP_NAME} {APP_VERSION_LABEL}")
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
        sidebar_layout.setContentsMargins(14, 24, 14, 20)
        sidebar_layout.setSpacing(4)

        title = QLabel("发票合并系统")
        title.setObjectName("AppTitle")

        version = QLabel(APP_VERSION_LABEL)
        version.setObjectName("AppVersion")

        sidebar_layout.addWidget(title)
        sidebar_layout.addWidget(version)
        sidebar_layout.addSpacing(18)
        workspace_title = QLabel("工作空间")
        workspace_title.setObjectName("SidebarSection")
        sidebar_layout.addWidget(workspace_title)

        nav_items = [
            ("home", "首页"),
            ("inquiry", "询价中心"),
            ("invoice", "发票中心"),
            ("customs", "发票报关修改"),
            ("tracking", "发货追踪"),
            ("watchlist", "重点追踪"),
            ("batch_edit", "批量修改单元格值"),
            ("sensitive", "敏感词检查"),
            ("maintain", "维护"),
        ]

        for route, text in nav_items:

            button = QPushButton(text)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setIcon(navigation_icon(route))
            button.setIconSize(QSize(20, 20))

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

        system_title.setObjectName("SidebarSection")

        username = getpass.getuser()
        computer = socket.gethostname()

        system_info = QLabel(
            f"当前用户：{username}\n"
            f"计算机：{computer}\n"
            f"版本号：{APP_VERSION_LABEL}"
        )

        system_info.setObjectName("SidebarInfo")

        sidebar_layout.addWidget(system_title)
        sidebar_layout.addSpacing(8)
        sidebar_layout.addWidget(system_info)

        root.addWidget(sidebar)

        # ==========================================
        # 页面容器
        # ==========================================

        self.stack = QStackedWidget()
        self.stack.setObjectName("PageStack")

        # 首页：使用真正的 HomePage
        home_page = HomePage()

        home_page.navigate_requested.connect(
            self.go_to
        )

        self.pages["home"] = home_page

        # 后续模块暂时占位
        self.pages["inquiry"] = InquiryPage()

        self.pages["invoice"] = InvoicePage()
        self.pages["customs"] = CustomsPage()
        self.pages["invoice"].content_merge_succeeded.connect(
            self.pages["customs"].receive_merge
        )
        self.pages["tracking"] = TrackingPage()
        self.pages["watchlist"] = WatchlistPage()
        self.pages["batch_edit"] = BatchEditPage()
        batch_receiver = getattr(self.pages["batch_edit"], "receive_merge", None)
        if batch_receiver is not None:
            self.pages["invoice"].content_merge_succeeded.connect(batch_receiver)
        self.pages["sensitive"] = SensitivePage()
        self.pages["maintain"] = MaintainPage()

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

    def closeEvent(self, event):
        invoice = self.pages.get("invoice")
        invoice_can_close = getattr(invoice, "can_close", None)
        if invoice_can_close is not None and not invoice_can_close():
            event.ignore()
            return
        customs = self.pages.get("customs")
        if customs is not None and not customs.can_close():
            event.ignore()
            return
        batch_editor = self.pages.get("batch_edit")
        if batch_editor is not None and hasattr(batch_editor, "can_close") and not batch_editor.can_close():
            event.ignore()
            return
        super().closeEvent(event)
