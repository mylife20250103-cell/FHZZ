from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.shipment_tracking.providers.nextsls import ShipmentDetail


class TrackingDetailDialog(QDialog):
    def __init__(self, detail: ShipmentDetail, parent=None):
        super().__init__(parent)
        self.setWindowTitle(detail.title)
        self.resize(980, 680)
        self._build(detail)

    def _build(self, detail: ShipmentDetail):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel(detail.title)
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(title)

        cards = QHBoxLayout()
        for label, value in (
            ("服务类型", detail.service_name),
            ("发往国家", detail.country),
            ("收费重量", detail.chargeable_weight),
            ("状态", detail.status_text),
        ):
            cards.addWidget(self._metric_card(label, value), 1)
        root.addLayout(cards)

        metrics = QHBoxLayout()
        for label, value in (
            ("收费重", detail.chargeable_weight),
            ("实重", detail.actual_weight),
            ("材积重", detail.volume_weight),
            ("计泡系数", detail.dim_factor),
            ("体积", detail.volume),
            ("箱数", detail.parcel_count),
        ):
            metrics.addWidget(self._metric_card(label, value), 1)
        root.addLayout(metrics)

        body = QHBoxLayout()
        body.addWidget(self._info_card(detail), 1)
        body.addWidget(self._trace_card(detail), 1)
        root.addLayout(body, 1)

        parcels_heading = QLabel("货箱信息")
        parcels_heading.setStyleSheet("font-weight: 700; font-size: 14px;")
        root.addWidget(parcels_heading)
        root.addWidget(self._parcel_table(detail))

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("SecondaryButton")
        close_btn.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

    def _metric_card(self, label: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        name = QLabel(label)
        name.setObjectName("SecondaryText")
        text = QLabel(value or "—")
        text.setWordWrap(True)
        text.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(name)
        layout.addWidget(text)
        return card

    def _info_card(self, detail: ShipmentDetail) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        heading = QLabel("基础信息")
        heading.setStyleSheet("font-weight: 700; font-size: 14px;")
        layout.addWidget(heading)
        grid = QGridLayout()
        rows = (
            ("收件人", detail.recipient),
            ("PO Number", detail.po_number),
            ("报关方式", detail.export_mode),
            ("成交方式", detail.tax_mode),
            ("币种", detail.currency),
            ("扩展单号", detail.ext_number),
            ("主品名", detail.product_name),
        )
        for index, (label, value) in enumerate(rows):
            key = QLabel(label)
            key.setObjectName("SecondaryText")
            val = QLabel(value or "—")
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(key, index, 0)
            grid.addWidget(val, index, 1)
        layout.addLayout(grid)
        layout.addStretch()
        return card

    def _trace_card(self, detail: ShipmentDetail) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        heading = QLabel("路由信息")
        heading.setStyleSheet("font-weight: 700; font-size: 14px;")
        layout.addWidget(heading)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        traces = QVBoxLayout(inner)
        traces.setSpacing(10)
        if not detail.traces:
            traces.addWidget(QLabel("暂无轨迹"))
        for item in detail.traces:
            block = QVBoxLayout()
            time = QLabel(item.time_text)
            time.setObjectName("SecondaryText")
            info = QLabel(item.info)
            info.setWordWrap(True)
            info.setTextInteractionFlags(Qt.TextSelectableByMouse)
            loc = QLabel(item.location)
            loc.setObjectName("SecondaryText")
            block.addWidget(time)
            block.addWidget(info)
            if item.location:
                block.addWidget(loc)
            traces.addLayout(block)
        traces.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        return card

    def _parcel_table(self, detail: ShipmentDetail) -> QTableWidget:
        table = QTableWidget(len(detail.parcels), 5)
        table.setHorizontalHeaderLabels(
            ["箱号", "客户数据", "拣货数据(实重/材积)", "申报价值", "状态"]
        )
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setMaximumHeight(140)
        for row, parcel in enumerate(detail.parcels):
            values = (
                parcel.carton_no,
                parcel.client_weight,
                parcel.picking,
                parcel.declared_value,
                parcel.status_text,
            )
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                table.setItem(row, col, cell)
        return table
