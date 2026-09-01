from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.shipment_tracking.indexing.shipping_file_indexer import list_store_codes
from app.shipment_tracking.paths import PACKING_LIST_ROOT
from app.shipment_tracking.services.shipping_load_service import (
    ShippingLoadResult,
    load_store_snapshots,
)
from app.workers import TaskWorker


class TrackingPage(QWidget):
    """只读查看装箱明细：Batch → FBA → SKU → Qty。不写库、不接货代。"""

    HEADERS = (
        "店铺",
        "发货日期",
        "批次",
        "文件",
        "FBA",
        "目的仓",
        "SKU",
        "数量",
        "品名",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self.build_ui()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 25, 30, 25)
        root.setSpacing(15)

        title = QLabel("发货追踪")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "按店铺扫描装箱明细，读取发货规划中的 FBA / SKU / 数量。"
            "文件名里的物流商只是候选，货代仍以发票扫描后的 CarrierCode 为准。"
            "暂无 Tracking。"
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("Card")
        setup = QVBoxLayout(card)
        setup.setContentsMargins(18, 16, 18, 16)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("装箱明细："))
        self.path_label = QLabel(str(PACKING_LIST_ROOT))
        self.path_label.setObjectName("SecondaryText")
        self.path_label.setWordWrap(True)
        path_row.addWidget(self.path_label, 1)
        open_btn = QPushButton("打开目录")
        open_btn.setObjectName("SecondaryButton")
        open_btn.clicked.connect(self.open_root)
        path_row.addWidget(open_btn)
        setup.addLayout(path_row)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("店铺："))
        self.store_combo = QComboBox()
        self.store_combo.setMinimumWidth(160)
        controls.addWidget(self.store_combo)
        self.scan_btn = QPushButton("扫描发货规划")
        self.scan_btn.clicked.connect(self.start_scan)
        controls.addWidget(self.scan_btn)
        controls.addStretch()
        setup.addLayout(controls)
        root.addWidget(card)

        self.status_label = QLabel("选择店铺后扫描。一次只读一个店，避免整库打开 Excel。")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        root.addWidget(self.table, 1)

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self.refresh_stores()

    def refresh_stores(self):
        current = self.store_combo.currentText()
        self.store_combo.blockSignals(True)
        self.store_combo.clear()
        stores = list_store_codes(PACKING_LIST_ROOT)
        self.store_combo.addItems(stores)
        if current:
            index = self.store_combo.findText(current)
            if index >= 0:
                self.store_combo.setCurrentIndex(index)
        self.store_combo.blockSignals(False)
        if not PACKING_LIST_ROOT.exists():
            self.status_label.setText(f"找不到装箱明细目录：{PACKING_LIST_ROOT}")

    def open_root(self):
        if not PACKING_LIST_ROOT.exists():
            QMessageBox.warning(
                self,
                "打不开目录",
                f"路径不存在：\n{PACKING_LIST_ROOT}",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(PACKING_LIST_ROOT)))

    def start_scan(self):
        store = self.store_combo.currentText().strip()
        if not store:
            QMessageBox.warning(self, "扫描发货规划", "请先选择店铺。")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self.scan_btn.setEnabled(False)
        self.store_combo.setEnabled(False)
        self.status_label.setText(f"正在读取 {store} 的发货规划…")
        self._worker = TaskWorker(
            lambda: load_store_snapshots(PACKING_LIST_ROOT, store),
            module="shipping_tracking",
            stage="scan",
            parent=self,
        )
        self._worker.succeeded.connect(self._on_scan_ok)
        self._worker.failed.connect(self._on_scan_fail)
        self._worker.start()

    def _on_scan_ok(self, result: ShippingLoadResult):
        self.scan_btn.setEnabled(True)
        self.store_combo.setEnabled(True)
        rows: list[list[str]] = []
        for snap in result.snapshots:
            source = snap.source
            ship_date = (
                source.ship_date.isoformat() if source.ship_date else ""
            )
            for fba in snap.aggregated:
                for item in fba.items:
                    rows.append(
                        [
                            source.store_code,
                            ship_date,
                            str(source.batch_no),
                            source.path.name,
                            fba.fba_id,
                            fba.destination_fc or "",
                            item.sku,
                            str(item.quantity),
                            item.product_name or "",
                        ]
                    )
        self.table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, cell)

        message = (
            f"完成：{len(result.snapshots)} 个发货单，"
            f"{len(rows)} 行 FBA/SKU。"
        )
        if result.errors:
            message += " 失败 " + "；".join(result.errors[:8])
            if len(result.errors) > 8:
                message += f" 等 {len(result.errors)} 条"
        self.status_label.setText(message)

    def _on_scan_fail(self, message: str, _detail: str):
        self.scan_btn.setEnabled(True)
        self.store_combo.setEnabled(True)
        self.status_label.setText(f"扫描失败：{message}")
        QMessageBox.critical(self, "扫描失败", message)
