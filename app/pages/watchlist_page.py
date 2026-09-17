from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.pages.tracking_detail_dialog import TrackingDetailDialog
from app.shipment_tracking.indexing.shipping_file_indexer import list_store_codes
from app.shipment_tracking.paths import PACKING_LIST_ROOT, TRACKING_STORE_PATH
from app.shipment_tracking.providers.nextsls import (
    format_latest_trace,
    load_shipment_detail,
)
from app.shipment_tracking.services.carrier_resolve import resolve_carrier
from app.shipment_tracking.services.channel_binding import channel_for
from app.shipment_tracking.services.forwarder_binding import binding_for
from app.shipment_tracking.services.shipping_load_service import (
    ShippingLoadResult,
    load_store_snapshots,
)
from app.shipment_tracking.services.tracking_overlay import (
    latest_event_for,
    load_tracking_overlay,
    tracking_for,
    upsert_tracking,
)
from app.shipment_tracking.services.tracking_pull import pull_forwarder_tracking
from app.shipment_tracking.services.watchlist import (
    DEFAULT_LOOKBACK_DAYS,
    WatchItem,
    add_watch_item,
    classify_shipment,
    load_watchlist,
    lookback_range,
    matches_any_watch_item,
    remove_watch_item,
    watch_result_sort_key,
)
from app.workers import TaskWorker

STORE_COL = 0
DATE_COL = 1
SKU_COL = 4
NAME_COL = 6
FBA_COL = 7
TRACKING_COL = 8
LATEST_COL = 10
HIDDEN_CONFIRMED = 11
HIDDEN_CANDIDATE = 12
HIDDEN_CHANNEL = 13


class WatchlistPage(QWidget):
    """按保存的店铺 + 品名（包含）查看最近 60 天重点产品运输情况。"""

    HEADERS = (
        "店铺",
        "发货日期",
        "批次",
        "文件",
        "SKU",
        "数量",
        "产品中文品名",
        "FBA",
        "Tracking",
        "目的仓",
        "最新物流信息",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._all_rows: list[list[str]] = []
        self._scan_status = ""
        self.build_ui()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 25, 30, 25)
        root.setSpacing(15)

        title = QLabel("重点追踪")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "保存店铺和产品中文品名（包含即可），进入本页即扫描最近 60 天装箱明细，"
            "马上看到这些重点货的 Tracking 和最新物流。"
            "可选再填 SKU，避免同店其它相近品名混进来。"
            "默认不显示已签收；需要给货代对账时再勾选。"
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("Card")
        setup = QVBoxLayout(card)
        setup.setContentsMargins(18, 16, 18, 16)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("店铺："))
        self.store_combo = QComboBox()
        self.store_combo.setMinimumWidth(120)
        add_row.addWidget(self.store_combo)
        add_row.addWidget(QLabel("品名包含："))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如 盖片")
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.setMinimumWidth(140)
        add_row.addWidget(self.name_edit)
        add_row.addWidget(QLabel("SKU 包含："))
        self.sku_edit = QLineEdit()
        self.sku_edit.setPlaceholderText("可选")
        self.sku_edit.setClearButtonEnabled(True)
        self.sku_edit.setMinimumWidth(120)
        add_row.addWidget(self.sku_edit)
        add_btn = QPushButton("加入重点")
        add_btn.clicked.connect(self.add_item)
        add_row.addWidget(add_btn)
        add_row.addStretch()
        setup.addLayout(add_row)

        list_row = QHBoxLayout()
        self.watch_list = QListWidget()
        self.watch_list.setMaximumHeight(110)
        list_row.addWidget(self.watch_list, 1)
        remove_btn = QPushButton("删除选中")
        remove_btn.setObjectName("SecondaryButton")
        remove_btn.clicked.connect(self.remove_selected)
        list_row.addWidget(remove_btn)
        setup.addLayout(list_row)

        actions = QHBoxLayout()
        self.include_delivered = QCheckBox("含已签收")
        self.include_delivered.stateChanged.connect(self._apply_view)
        actions.addWidget(self.include_delivered)
        self.refresh_btn = QPushButton("刷新最近 60 天")
        self.refresh_btn.clicked.connect(self.start_scan)
        actions.addWidget(self.refresh_btn)
        self.pull_btn = QPushButton("刷新物流")
        self.pull_btn.setObjectName("SecondaryButton")
        self.pull_btn.clicked.connect(self.pull_forwarder)
        actions.addWidget(self.pull_btn)
        actions.addStretch()
        setup.addLayout(actions)
        root.addWidget(card)

        self.status_label = QLabel(
            "先加入重点产品，例如美8 + 盖片。进入本页会自动扫描最近 60 天。"
        )
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(60)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setMouseTracking(True)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.cellEntered.connect(self._on_cell_entered)
        root.addWidget(self.table, 1)

        self.refresh_stores()
        self.reload_watch_list()

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self.refresh_stores()
        self.reload_watch_list()
        self.start_scan()

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

    def current_items(self) -> list[WatchItem]:
        return load_watchlist()

    def reload_watch_list(self):
        self.watch_list.clear()
        for item in self.current_items():
            row = QListWidgetItem(item.label())
            row.setData(Qt.UserRole, item)
            self.watch_list.addItem(row)

    def add_item(self):
        try:
            item, created = add_watch_item(
                self.store_combo.currentText(),
                self.name_edit.text(),
                self.sku_edit.text(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "加入重点", str(exc))
            return
        self.reload_watch_list()
        if not created:
            QMessageBox.information(self, "加入重点", f"已在清单里：{item.label()}")
            return
        self.name_edit.clear()
        self.sku_edit.clear()
        self.start_scan()

    def remove_selected(self):
        row = self.watch_list.currentItem()
        if row is None:
            QMessageBox.information(self, "删除重点", "请先选中一条重点。")
            return
        item = row.data(Qt.UserRole)
        if not isinstance(item, WatchItem):
            return
        remove_watch_item(item)
        self.reload_watch_list()
        self.start_scan()

    def _busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _set_busy(self, busy: bool):
        self.refresh_btn.setEnabled(not busy)
        self.pull_btn.setEnabled(not busy)

    def start_scan(self):
        if self._busy():
            return
        items = self.current_items()
        if not items:
            self._all_rows = []
            self._scan_status = "还没有重点产品。先加入店铺和品名，例如美8 + 盖片。"
            self._apply_view()
            return
        start, end = lookback_range()
        stores = sorted({item.store_code for item in items})
        self._set_busy(True)
        self.status_label.setText(
            f"正在扫描 { '、'.join(stores) } 最近 {DEFAULT_LOOKBACK_DAYS} 天"
            f"（{start.isoformat()} ~ {end.isoformat()}）…"
        )

        def job():
            snapshots = []
            errors: list[str] = []
            forwarders = {}
            channels = {}
            for store in stores:
                result = load_store_snapshots(
                    PACKING_LIST_ROOT,
                    store,
                    all_periods=False,
                    start_date=start,
                    end_date=end,
                )
                snapshots.extend(result.snapshots)
                errors.extend(result.errors)
                forwarders.update(result.forwarders)
                channels.update(result.channels)
            return ShippingLoadResult(
                snapshots=tuple(snapshots),
                errors=tuple(errors),
                forwarders=forwarders,
                channels=channels,
            )

        self._worker = TaskWorker(
            job,
            module="watchlist",
            stage="scan",
            parent=self,
        )
        self._worker.succeeded.connect(self._on_scan_ok)
        self._worker.failed.connect(self._on_scan_fail)
        self._worker.start()

    def _on_scan_ok(self, result: ShippingLoadResult):
        self._set_busy(False)
        overlay = load_tracking_overlay()
        items = self.current_items()
        rows: list[list[str]] = []
        for snap in result.snapshots:
            source = snap.source
            ship_date = (
                source.ship_date.isoformat() if source.ship_date else ""
            )
            for fba in snap.aggregated:
                bound = binding_for(fba.fba_id, result.forwarders)
                channel = channel_for(fba.fba_id, result.channels)
                if bound.state == "confirmed":
                    confirmed = bound.carrier_code
                elif bound.state == "conflict":
                    confirmed = f"冲突 {bound.carrier_code}"
                else:
                    confirmed = ""
                if channel.state == "confirmed":
                    channel_text = channel.channel_text
                elif channel.state == "conflict":
                    channel_text = f"冲突 {channel.channel_text}"
                else:
                    channel_text = ""
                tracking = tracking_for(fba.fba_id, overlay)
                latest = latest_event_for(fba.fba_id, overlay)
                for item in fba.items:
                    if not matches_any_watch_item(
                        source.store_code,
                        item.sku,
                        item.product_name or "",
                        items,
                    ):
                        continue
                    rows.append(
                        [
                            source.store_code,
                            ship_date,
                            str(source.batch_no),
                            source.path.name,
                            item.sku,
                            str(item.quantity),
                            item.product_name or "",
                            fba.fba_id,
                            tracking,
                            fba.destination_fc or "",
                            latest,
                            confirmed,
                            source.candidate_forwarder or "",
                            channel_text,
                        ]
                    )
        rows.sort(
            key=lambda row: watch_result_sort_key(
                row[STORE_COL],
                row[NAME_COL],
                row[DATE_COL],
            )
        )
        start, end = lookback_range()
        counts = _count_buckets(rows)
        self._scan_status = (
            f"最近 {DEFAULT_LOOKBACK_DAYS} 天"
            f"（{start.isoformat()} ~ {end.isoformat()}）："
            f"{len(rows)} 行。"
            f" 在途 {counts['在途']}，无运单 {counts['无运单']}，已签收 {counts['已签收']}。"
        )
        if result.errors:
            self._scan_status += " 失败 " + "；".join(result.errors[:6])
        self._all_rows = rows
        self._apply_view()

    def _on_scan_fail(self, message: str, _detail: str):
        self._set_busy(False)
        self.status_label.setText(f"扫描失败：{message}")
        QMessageBox.critical(self, "重点追踪", message)

    def pull_forwarder(self):
        shown = self._visible_rows()
        if not shown:
            QMessageBox.warning(self, "刷新物流", "当前没有可查询的行，请先加入重点并刷新。")
            return
        if self._busy():
            return
        items: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for row in shown:
            fba_id = row[FBA_COL].strip().upper()
            if fba_id and fba_id not in seen:
                seen.add(fba_id)
                items.append(
                    (
                        fba_id,
                        resolve_carrier(
                            row[HIDDEN_CONFIRMED],
                            row[HIDDEN_CANDIDATE],
                        ),
                        row[HIDDEN_CANDIDATE].strip(),
                    )
                )
        if not items:
            QMessageBox.warning(self, "刷新物流", "当前没有可查询的 FBA。")
            return
        self._set_busy(True)
        self.status_label.setText(f"正在查询 {len(items)} 个 FBA 的货代运单…")
        self._worker = TaskWorker(
            lambda: pull_forwarder_tracking(
                items, overlay_path=TRACKING_STORE_PATH
            ),
            module="watchlist",
            stage="forwarder_pull",
            parent=self,
        )
        self._worker.succeeded.connect(self._on_pull_ok)
        self._worker.failed.connect(self._on_pull_fail)
        self._worker.start()

    def _on_pull_ok(self, result):
        self._set_busy(False)
        overlay = load_tracking_overlay()
        for row in self._all_rows:
            while len(row) <= LATEST_COL:
                row.append("")
            row[TRACKING_COL] = tracking_for(row[FBA_COL], overlay)
            row[LATEST_COL] = latest_event_for(row[FBA_COL], overlay)
        counts = _count_buckets(self._all_rows)
        extra = (
            f"货代拉取完成：找到 {result.found}，未找到 {result.missing}，"
            f"保留人工登记 {result.skipped_manual}，无接口 {result.skipped_no_api}。"
            f" 在途 {counts['在途']}，无运单 {counts['无运单']}，已签收 {counts['已签收']}。"
        )
        if result.errors:
            extra += " " + "；".join(result.errors[:6])
        if self._scan_status:
            self.status_label.setText(f"{self._scan_status} {extra}")
        else:
            self.status_label.setText(extra)
        self._apply_view()
        if result.errors:
            QMessageBox.warning(self, "刷新物流", extra)

    def _on_pull_fail(self, message: str, _detail: str):
        self._set_busy(False)
        self.status_label.setText(f"货代拉取失败：{message}")
        QMessageBox.critical(self, "刷新物流", message)

    def _visible_rows(self) -> list[list[str]]:
        include_delivered = self.include_delivered.isChecked()
        shown = []
        for row in self._all_rows:
            bucket = classify_shipment(row[TRACKING_COL], row[LATEST_COL])
            if bucket == "已签收" and not include_delivered:
                continue
            shown.append(row)
        return shown

    def _apply_view(self):
        shown = self._visible_rows()
        self._fill_table(shown)
        if not self._scan_status:
            return
        hidden = len(self._all_rows) - len(shown)
        if hidden:
            self.status_label.setText(
                f"{self._scan_status} 已隐藏 {hidden} 行已签收。"
            )
        else:
            self.status_label.setText(self._scan_status)

    def _fill_table(self, rows: list[list[str]]):
        self.table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            bucket = classify_shipment(
                values[TRACKING_COL] if len(values) > TRACKING_COL else "",
                values[LATEST_COL] if len(values) > LATEST_COL else "",
            )
            for col, value in enumerate(values[: len(self.HEADERS)]):
                cell = QTableWidgetItem(value)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                if col == TRACKING_COL and value.strip():
                    font = cell.font()
                    font.setUnderline(True)
                    cell.setFont(font)
                    cell.setForeground(QColor("#1565C0"))
                    cell.setToolTip("点击查看货代详情")
                if col == LATEST_COL and value.strip():
                    cell.setToolTip(value)
                if bucket == "无运单":
                    cell.setForeground(QColor("#8A93A6"))
                self.table.setItem(row, col, cell)

    def _on_cell_entered(self, row: int, col: int):
        cell = self.table.item(row, col)
        if col == TRACKING_COL and cell and cell.text().strip():
            self.table.viewport().setCursor(Qt.PointingHandCursor)
        else:
            self.table.viewport().unsetCursor()

    def _on_cell_clicked(self, row: int, col: int):
        if col != TRACKING_COL:
            return
        tracking_cell = self.table.item(row, TRACKING_COL)
        if not tracking_cell or not tracking_cell.text().strip():
            return
        if self._busy():
            QMessageBox.information(self, "运单详情", "正在处理其他任务，请稍后再点。")
            return
        shown = self._visible_rows()
        if row < 0 or row >= len(shown):
            return
        data = shown[row]
        fba_id = data[FBA_COL].strip()
        carrier = resolve_carrier(
            data[HIDDEN_CONFIRMED],
            data[HIDDEN_CANDIDATE],
        )
        channel = data[HIDDEN_CHANNEL].strip()
        tracking = tracking_cell.text().strip()
        overlay = load_tracking_overlay()
        record = overlay.get(fba_id.strip().upper())
        source = record.source if record else ""
        self._set_busy(True)
        self.status_label.setText(f"正在查询 {tracking} 详情…")
        self._worker = TaskWorker(
            lambda: load_shipment_detail(
                fba_id,
                carrier,
                channel_name=channel,
                source=source,
                account_hint=data[HIDDEN_CANDIDATE].strip(),
            ),
            module="watchlist",
            stage="tracking_detail",
            parent=self,
        )
        self._worker.succeeded.connect(self._on_detail_ok)
        self._worker.failed.connect(self._on_detail_fail)
        self._worker.start()

    def _on_detail_ok(self, detail):
        self._set_busy(False)
        latest = format_latest_trace(detail.traces)
        fba_id = (detail.ext_number or "").strip().upper()
        if fba_id and fba_id != "—" and latest:
            overlay = load_tracking_overlay()
            record = overlay.get(fba_id)
            tracking = detail.title.split("/")[0].replace("#", "").strip()
            if record:
                tracking = record.tracking_number or tracking
                upsert_tracking(
                    fba_id,
                    tracking,
                    source=record.source,
                    latest_event=latest,
                    path=TRACKING_STORE_PATH,
                )
            for row in self._all_rows:
                if row[FBA_COL].strip().upper() == fba_id:
                    row[LATEST_COL] = latest
            self._apply_view()
        if self._scan_status:
            self.status_label.setText(self._scan_status)
        TrackingDetailDialog(detail, self).exec()

    def _on_detail_fail(self, message: str, _detail: str):
        self._set_busy(False)
        if self._scan_status:
            self.status_label.setText(self._scan_status)
        else:
            self.status_label.setText(f"查询详情失败：{message}")
        QMessageBox.warning(self, "运单详情", message)


def _count_buckets(rows: list[list[str]]) -> dict[str, int]:
    counts = {"在途": 0, "已签收": 0, "无运单": 0}
    for row in rows:
        bucket = classify_shipment(row[TRACKING_COL], row[LATEST_COL])
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts
