from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.invoice_config import CENTRAL_ADDRESS_PATH


class MaintainPage(QWidget):
    """
    需要人工维护的中央文件入口，方便新手找到路径。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.build_ui()

    def build_ui(self):

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 25, 30, 25)
        root.setSpacing(15)

        title = QLabel("维护")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "这里列出需要人工维护的中央文件。"
            "点「打开文件」会用系统默认程序打开对应路径。"
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        root.addWidget(
            self._item_card(
                title_text="各物流地址库",
                description=(
                    "快越达、迈创合并时按仓编码读取这份表。"
                    "新增或修改仓库地址只改这里，不要改官方发票模板。"
                    "工作表：快越达地址库、迈创地址库。"
                ),
                path=CENTRAL_ADDRESS_PATH,
            )
        )

        root.addStretch()

    def _item_card(
        self,
        title_text: str,
        description: str,
        path: Path,
    ) -> QFrame:

        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        name = QLabel(title_text)
        name.setObjectName("CardTitle")
        header.addWidget(name)
        header.addStretch()

        exists = QLabel()
        if path.exists():
            exists.setText("文件存在")
            exists.setStyleSheet("color:#16A765; font-size:12px; font-weight:600;")
        else:
            exists.setText("文件不存在")
            exists.setStyleSheet("color:#D64B6A; font-size:12px; font-weight:600;")
        header.addWidget(exists)
        layout.addLayout(header)

        desc = QLabel(description)
        desc.setObjectName("SecondaryText")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        path_label = QLabel(str(path))
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_label.setStyleSheet(
            "font-size:12px; color:#39435A; background:#F8FAFD;"
            "border:1px solid #E9EDF3; border-radius:6px; padding:8px 10px;"
        )
        layout.addWidget(path_label)

        buttons = QHBoxLayout()
        open_btn = QPushButton("打开文件")
        open_btn.setObjectName("SecondaryButton")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.clicked.connect(lambda: self.open_file(path))
        buttons.addWidget(open_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

        return card

    def open_file(self, path: Path) -> None:

        if not path.exists():
            QMessageBox.warning(
                self,
                "找不到文件",
                "文件不存在，请确认路径是否还能访问：\n\n"
                f"{path}",
            )
            return

        try:
            os.startfile(str(path))
        except OSError as exc:
            QMessageBox.critical(
                self,
                "打开失败",
                f"无法打开文件：\n\n{path}\n\n{exc}",
            )
