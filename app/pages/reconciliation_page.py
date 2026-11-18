"""独立货件核对页面，复用原面板的状态、异步任务及导出。"""
from pathlib import Path

from PySide6.QtWidgets import (
    QFrame, QLabel, QLayout, QScrollArea, QVBoxLayout, QWidget,
)

from app.pages.reconciliation_panel import ReconciliationPanel


class ReconciliationPage(QWidget):
    def __init__(self, parent=None, *, directory: Path | None = None):
        super().__init__(parent)
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(15)
        layout.setSizeConstraint(QLayout.SetMinAndMaxSize)
        title = QLabel('货件数据核对')
        title.setObjectName('PageTitle')
        layout.addWidget(title)
        subtitle = QLabel('读取合并结果，粘贴货代报数，核对整票重量并筛选需申请重测的货件。')
        subtitle.setObjectName('PageSubtitle')
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        self.panel = ReconciliationPanel(self, directory=directory)
        layout.addWidget(self.panel, 1)
        scroll.setWidget(content)
        page_layout.addWidget(scroll)

    def receive_merge(self, context):
        self.panel.receive_merge(context)

    def can_close(self):
        return self.panel.can_close()
