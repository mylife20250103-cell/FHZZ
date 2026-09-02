from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.shipment_tracking.indexing.shipping_file_indexer import (
    list_store_codes,
    list_store_periods,
    period_label,
)
from app.shipment_tracking.paths import PACKING_LIST_ROOT, TRACKING_STORE_PATH
from app.shipment_tracking.services.channel_binding import channel_for
from app.shipment_tracking.services.carrier_resolve import resolve_carrier
from app.shipment_tracking.services.forwarder_binding import binding_for
from app.shipment_tracking.services.shipping_load_service import (
    ShippingLoadResult,
    load_store_snapshots,
)
from app.pages.tracking_detail_dialog import TrackingDetailDialog
from app.shipment_tracking.providers.nextsls import load_shipment_detail
from app.shipment_tracking.services.tracking_overlay import (
    load_tracking_overlay,
    tracking_for,
    upsert_tracking,
)
from app.shipment_tracking.services.tracking_pull import pull_forwarder_tracking
from app.workers import TaskWorker

FBA_COL = 7
TRACKING_COL = 8
SKU_COL = 10
NAME_COL = 12
CONFIRMED_COL = 4
CHANNEL_COL = 5
CANDIDATE_COL = 6
ALL_STORES_LABEL = "全部店铺"


def row_matches(
    values: list[str],
    sku_query: str,
    name_query: str,
    tracking_query: str = "",
    fba_query: str = "",
) -> bool:
    sku_q = (sku_query or "").strip().casefold()
    name_q = (name_query or "").strip().casefold()
    tracking_q = (tracking_query or "").strip().casefold()
    fba_q = (fba_query or "").strip().casefold()
    if sku_q and sku_q not in (values[SKU_COL] or "").casefold():
        return False
    if name_q and name_q not in (values[NAME_COL] or "").casefold():
        return False
    if tracking_q and tracking_q not in (values[TRACKING_COL] or "").casefold():
        return False
    if fba_q and fba_q not in (values[FBA_COL] or "").casefold():
        return False
    return True


class TrackingPage(QWidget):
    """只读查看装箱明细：Batch → FBA → SKU → Qty。不写库、不接货代。"""

    HEADERS = (
        "店铺",
        "发货日期",
        "批次",
        "文件",
        "确认货代",
        "渠道",
        "候选货代",
        "FBA",
        "Tracking",
        "目的仓",
        "SKU",
        "数量",
        "产品中文品名",
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

        title = QLabel("发货追踪")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "按店铺、月份扫描装箱明细，读取发货规划中的 FBA / SKU / 数量。"
            "可选全部店铺，再按月份或日期范围扫描，然后用 FBA 号筛选对应行。"
            "默认只扫最近一个月，避免一次打开整店历史。"
            "确认货代来自发票扫描后的 CarrierCode；没有确认时按文件名候选货代（如迈创合德）查询。"
            "从货代拉取会查当前筛选结果里的全部 FBA；同物流商多个下单账号时，按文件名候选优先匹配（如迈创寻麓→寻麓者）。"
            "已有 Tracking 时，点击蓝色运单号可查看货代后台同款详情（状态、重量、路由、货箱）。"
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
        self.store_combo.currentTextChanged.connect(self.refresh_periods)
        controls.addWidget(self.store_combo)
        controls.addWidget(QLabel("月份："))
        self.period_combo = QComboBox()
        self.period_combo.setMinimumWidth(160)
        self.period_combo.currentIndexChanged.connect(self._toggle_custom_range)
        controls.addWidget(self.period_combo)
        self.range_from_label = QLabel("从")
        self.range_from = QDateEdit()
        self.range_from.setCalendarPopup(True)
        self.range_from.setDisplayFormat("yyyy-MM-dd")
        self.range_from.setDate(QDate.currentDate().addDays(-30))
        self.range_to_label = QLabel("到")
        self.range_to = QDateEdit()
        self.range_to.setCalendarPopup(True)
        self.range_to.setDisplayFormat("yyyy-MM-dd")
        self.range_to.setDate(QDate.currentDate())
        controls.addWidget(self.range_from_label)
        controls.addWidget(self.range_from)
        controls.addWidget(self.range_to_label)
        controls.addWidget(self.range_to)
        self.scan_btn = QPushButton("扫描发货规划")
        self.scan_btn.clicked.connect(self.start_scan)
        controls.addWidget(self.scan_btn)
        controls.addStretch()
        setup.addLayout(controls)
        self._toggle_custom_range()

        filters = QHBoxLayout()
        filters.addWidget(QLabel("FBA："))
        self.fba_edit = QLineEdit()
        self.fba_edit.setPlaceholderText("包含即可，例如 FBA19G251B4H")
        self.fba_edit.setClearButtonEnabled(True)
        self.fba_edit.setMinimumWidth(200)
        self.fba_edit.textChanged.connect(self._apply_filter)
        filters.addWidget(self.fba_edit)
        filters.addWidget(QLabel("SKU："))
        self.sku_edit = QLineEdit()
        self.sku_edit.setPlaceholderText("包含即可，例如 GP995")
        self.sku_edit.setClearButtonEnabled(True)
        self.sku_edit.setMinimumWidth(180)
        self.sku_edit.textChanged.connect(self._apply_filter)
        filters.addWidget(self.sku_edit)
        filters.addWidget(QLabel("产品中文品名："))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("包含即可")
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.setMinimumWidth(180)
        self.name_edit.textChanged.connect(self._apply_filter)
        filters.addWidget(self.name_edit)
        filters.addWidget(QLabel("运单号："))
        self.tracking_filter = QLineEdit()
        self.tracking_filter.setPlaceholderText("包含即可")
        self.tracking_filter.setClearButtonEnabled(True)
        self.tracking_filter.setMinimumWidth(140)
        self.tracking_filter.textChanged.connect(self._apply_filter)
        filters.addWidget(self.tracking_filter)
        clear_btn = QPushButton("清除筛选")
        clear_btn.setObjectName("SecondaryButton")
        clear_btn.clicked.connect(self._clear_filter)
        filters.addWidget(clear_btn)
        filters.addStretch()
        setup.addLayout(filters)

        register = QHBoxLayout()
        register.addWidget(QLabel("登记运单号："))
        self.tracking_edit = QLineEdit()
        self.tracking_edit.setPlaceholderText("选中表格行后填写，按 FBA 保存")
        self.tracking_edit.setMinimumWidth(220)
        register.addWidget(self.tracking_edit)
        save_btn = QPushButton("登记到所选 FBA")
        save_btn.setObjectName("SecondaryButton")
        save_btn.clicked.connect(self.register_tracking)
        register.addWidget(save_btn)
        pull_btn = QPushButton("从货代拉取")
        pull_btn.setObjectName("SecondaryButton")
        pull_btn.clicked.connect(self.pull_forwarder)
        self.pull_btn = pull_btn
        register.addWidget(pull_btn)
        register.addStretch()
        setup.addLayout(register)
        root.addWidget(card)

        self.status_label = QLabel(
            "选择店铺（或全部店铺）和月份/日期范围后扫描，再用 FBA 号筛选。"
            "默认最近一个月，不必一次打开整店 Excel。"
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

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self.refresh_stores()

    def refresh_stores(self):
        current = self.store_combo.currentText()
        self.store_combo.blockSignals(True)
        self.store_combo.clear()
        stores = list_store_codes(PACKING_LIST_ROOT)
        self.store_combo.addItem(ALL_STORES_LABEL)
        self.store_combo.addItems(stores)
        if current:
            index = self.store_combo.findText(current)
            if index >= 0:
                self.store_combo.setCurrentIndex(index)
        elif stores:
            self.store_combo.setCurrentIndex(1)
        self.store_combo.blockSignals(False)
        self.refresh_periods()
        if not PACKING_LIST_ROOT.exists():
            self.status_label.setText(f"找不到装箱明细目录：{PACKING_LIST_ROOT}")

    def _selected_store(self) -> str:
        text = self.store_combo.currentText().strip()
        if text == ALL_STORES_LABEL:
            return ""
        return text

    def refresh_periods(self):
        store = self._selected_store()
        current = self.period_combo.currentData()
        self.period_combo.blockSignals(True)
        self.period_combo.clear()
        self.period_combo.addItem("全部月份", ("all", None, None))
        for year, month in list_store_periods(PACKING_LIST_ROOT, store or None):
            self.period_combo.addItem(
                period_label(year, month),
                ("month", year, month),
            )
        self.period_combo.addItem("其他", ("custom", None, None))
        if current is not None:
            for index in range(self.period_combo.count()):
                if self.period_combo.itemData(index) == current:
                    self.period_combo.setCurrentIndex(index)
                    break
            else:
                if self.period_combo.count() > 1:
                    self.period_combo.setCurrentIndex(1)
        elif self.period_combo.count() > 1:
            self.period_combo.setCurrentIndex(1)
        self.period_combo.blockSignals(False)
        self._toggle_custom_range()

    def _toggle_custom_range(self):
        period = self.period_combo.currentData()
        visible = bool(period and period[0] == "custom")
        for widget in (
            self.range_from_label,
            self.range_from,
            self.range_to_label,
            self.range_to,
        ):
            widget.setVisible(visible)

    def _custom_range(self) -> tuple[date, date]:
        start = self.range_from.date().toPython()
        end = self.range_to.date().toPython()
        if start > end:
            start, end = end, start
        return start, end

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
        store = self._selected_store()
        store_text = ALL_STORES_LABEL if not store else store
        if self._worker is not None and self._worker.isRunning():
            return
        period = self.period_combo.currentData()
        all_periods = True
        year = month = None
        start_date = end_date = None
        period_text = "全部月份"
        if period and period[0] == "custom":
            all_periods = False
            start_date, end_date = self._custom_range()
            period_text = f"{start_date.isoformat()} ~ {end_date.isoformat()}"
        elif period and period[0] != "all":
            all_periods = False
            year, month = period[1], period[2]
            period_text = period_label(year, month)
        if not store and all_periods:
            QMessageBox.warning(
                self,
                "扫描发货规划",
                "全部店铺请选择月份或日期范围，扫描后再用 FBA 号筛选。",
            )
            return
        self._set_scan_controls(False)
        self.status_label.setText(f"正在读取 {store_text} / {period_text} 的发货规划…")
        self._worker = TaskWorker(
            lambda: load_store_snapshots(
                PACKING_LIST_ROOT,
                store or None,
                year=year,
                month=month,
                all_periods=all_periods,
                start_date=start_date,
                end_date=end_date,
            ),
            module="shipping_tracking",
            stage="scan",
            parent=self,
        )
        self._worker.succeeded.connect(self._on_scan_ok)
        self._worker.failed.connect(self._on_scan_fail)
        self._worker.start()

    def _set_scan_controls(self, enabled: bool):
        self.scan_btn.setEnabled(enabled)
        self.store_combo.setEnabled(enabled)
        self.period_combo.setEnabled(enabled)
        self.range_from.setEnabled(enabled)
        self.range_to.setEnabled(enabled)
        self.pull_btn.setEnabled(enabled)

    def _on_scan_ok(self, result: ShippingLoadResult):
        self._set_scan_controls(True)
        overlay = load_tracking_overlay()
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
                for item in fba.items:
                    rows.append(
                        [
                            source.store_code,
                            ship_date,
                            str(source.batch_no),
                            source.path.name,
                            confirmed,
                            channel_text,
                            source.candidate_forwarder or "",
                            fba.fba_id,
                            tracking,
                            fba.destination_fc or "",
                            item.sku,
                            str(item.quantity),
                            item.product_name or "",
                        ]
                    )
        confirmed_n = sum(
            1 for item in result.forwarders.values() if item.state == "confirmed"
        )
        channel_n = sum(
            1 for item in result.channels.values() if item.state == "confirmed"
        )
        missing_n = sum(
            1
            for snap in result.snapshots
            for fba in snap.aggregated
            if binding_for(fba.fba_id, result.forwarders).state == "missing"
        )
        message = (
            f"完成：{len(result.snapshots)} 个发货单，"
            f"{len(rows)} 行 FBA/SKU。"
            f" 确认货代 {confirmed_n} 个 FBA，确认渠道 {channel_n} 个，"
            f"未绑定货代 {missing_n} 个。"
            f" 已有运单号 {sum(1 for row in rows if row[TRACKING_COL])} 行。"
        )
        if result.errors:
            message += " 失败 " + "；".join(result.errors[:8])
            if len(result.errors) > 8:
                message += f" 等 {len(result.errors)} 条"
        self._all_rows = rows
        self._scan_status = message
        self._apply_filter()

    def _on_scan_fail(self, message: str, _detail: str):
        self._set_scan_controls(True)
        self.status_label.setText(f"扫描失败：{message}")
        QMessageBox.critical(self, "扫描失败", message)

    def register_tracking(self):
        number = self.tracking_edit.text().strip()
        if not number:
            QMessageBox.warning(self, "登记运单号", "请填写运单号。")
            return
        selected = {index.row() for index in self.table.selectedIndexes()}
        if not selected:
            QMessageBox.warning(self, "登记运单号", "请先在表格里选中要登记的行。")
            return
        fba_ids: list[str] = []
        seen: set[str] = set()
        for row in sorted(selected):
            cell = self.table.item(row, FBA_COL)
            fba_id = cell.text().strip().upper() if cell else ""
            if fba_id and fba_id not in seen:
                seen.add(fba_id)
                fba_ids.append(fba_id)
        if not fba_ids:
            QMessageBox.warning(self, "登记运单号", "选中行没有 FBA。")
            return
        if len(fba_ids) > 1:
            answer = QMessageBox.question(
                self,
                "登记运单号",
                f"选中了 {len(fba_ids)} 个 FBA，将登记同一运单号。是否继续？",
            )
            if answer != QMessageBox.Yes:
                return
        try:
            for fba_id in fba_ids:
                upsert_tracking(fba_id, number, path=TRACKING_STORE_PATH)
        except Exception as exc:
            QMessageBox.critical(self, "登记失败", str(exc))
            return
        for row in self._all_rows:
            if row[FBA_COL].strip().upper() in seen:
                row[TRACKING_COL] = number
        self._apply_filter()
        extra = f"已登记运单号到 {len(fba_ids)} 个 FBA。"
        if self._scan_status:
            self.status_label.setText(f"{self._scan_status} {extra}")
        else:
            self.status_label.setText(extra)

    def pull_forwarder(self):
        if not self._all_rows:
            QMessageBox.warning(self, "从货代拉取", "请先扫描发货规划。")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        items: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        sku_q = self.sku_edit.text()
        name_q = self.name_edit.text()
        tracking_q = self.tracking_filter.text()
        for row in self._all_rows:
            if not row_matches(row, sku_q, name_q, tracking_q):
                continue
            fba_id = row[FBA_COL].strip().upper()
            if fba_id and fba_id not in seen:
                seen.add(fba_id)
                items.append(
                    (
                        fba_id,
                        resolve_carrier(row[CONFIRMED_COL], row[CANDIDATE_COL]),
                        row[CANDIDATE_COL].strip(),
                    )
                )
        if not items:
            QMessageBox.warning(self, "从货代拉取", "当前没有可查询的 FBA。")
            return
        self.scan_btn.setEnabled(False)
        self.pull_btn.setEnabled(False)
        self.status_label.setText(f"正在查询 {len(items)} 个 FBA 的货代运单…")
        self._worker = TaskWorker(
            lambda: pull_forwarder_tracking(
                items, overlay_path=TRACKING_STORE_PATH
            ),
            module="shipping_tracking",
            stage="forwarder_pull",
            parent=self,
        )
        self._worker.succeeded.connect(self._on_pull_ok)
        self._worker.failed.connect(self._on_pull_fail)
        self._worker.start()

    def _on_pull_ok(self, result):
        self.scan_btn.setEnabled(True)
        self.pull_btn.setEnabled(True)
        overlay = load_tracking_overlay()
        for row in self._all_rows:
            row[TRACKING_COL] = tracking_for(row[FBA_COL], overlay)
        self._apply_filter()
        message = (
            f"货代拉取完成：找到 {result.found}，"
            f"未找到 {result.missing}，"
            f"保留人工登记 {result.skipped_manual}，"
            f"无接口 {result.skipped_no_api}。"
        )
        if result.errors:
            message += " " + "；".join(result.errors[:6])
        if self._scan_status:
            self.status_label.setText(f"{self._scan_status} {message}")
        else:
            self.status_label.setText(message)
        if result.errors:
            QMessageBox.warning(self, "从货代拉取", message)

    def _on_pull_fail(self, message: str, _detail: str):
        self.scan_btn.setEnabled(True)
        self.pull_btn.setEnabled(True)
        self.status_label.setText(f"货代拉取失败：{message}")
        QMessageBox.critical(self, "从货代拉取", message)

    def _clear_filter(self):
        self.fba_edit.blockSignals(True)
        self.sku_edit.blockSignals(True)
        self.name_edit.blockSignals(True)
        self.tracking_filter.blockSignals(True)
        self.fba_edit.clear()
        self.sku_edit.clear()
        self.name_edit.clear()
        self.tracking_filter.clear()
        self.fba_edit.blockSignals(False)
        self.sku_edit.blockSignals(False)
        self.name_edit.blockSignals(False)
        self.tracking_filter.blockSignals(False)
        self._apply_filter()

    def _apply_filter(self):
        sku_q = self.sku_edit.text()
        name_q = self.name_edit.text()
        tracking_q = self.tracking_filter.text()
        fba_q = self.fba_edit.text()
        shown = [
            row
            for row in self._all_rows
            if row_matches(row, sku_q, name_q, tracking_q, fba_q)
        ]
        self._fill_table(shown)
        if not self._scan_status:
            return
        if sku_q.strip() or name_q.strip() or tracking_q.strip() or fba_q.strip():
            self.status_label.setText(
                f"{self._scan_status} 筛选后 {len(shown)} / {len(self._all_rows)} 行。"
            )
        else:
            self.status_label.setText(self._scan_status)

    def _fill_table(self, rows: list[list[str]]):
        self.table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                if col == TRACKING_COL and value.strip():
                    font = cell.font()
                    font.setUnderline(True)
                    cell.setFont(font)
                    cell.setForeground(QColor("#1565C0"))
                    cell.setToolTip("点击查看货代详情")
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
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "运单详情", "正在处理其他任务，请稍后再点。")
            return
        fba_cell = self.table.item(row, FBA_COL)
        carrier_cell = self.table.item(row, CONFIRMED_COL)
        channel_cell = self.table.item(row, CHANNEL_COL)
        candidate_cell = self.table.item(row, CANDIDATE_COL)
        fba_id = fba_cell.text().strip() if fba_cell else ""
        carrier = resolve_carrier(
            carrier_cell.text().strip() if carrier_cell else "",
            candidate_cell.text().strip() if candidate_cell else "",
        )
        channel = channel_cell.text().strip() if channel_cell else ""
        tracking = tracking_cell.text().strip()
        overlay = load_tracking_overlay()
        record = overlay.get(fba_id.strip().upper())
        source = record.source if record else ""
        self.scan_btn.setEnabled(False)
        self.pull_btn.setEnabled(False)
        self.status_label.setText(f"正在查询 {tracking} 详情…")
        self._worker = TaskWorker(
            lambda: load_shipment_detail(
                fba_id,
                carrier,
                channel_name=channel,
                source=source,
                account_hint=candidate_cell.text().strip() if candidate_cell else "",
            ),
            module="shipping_tracking",
            stage="tracking_detail",
            parent=self,
        )
        self._worker.succeeded.connect(self._on_detail_ok)
        self._worker.failed.connect(self._on_detail_fail)
        self._worker.start()

    def _on_detail_ok(self, detail):
        self.scan_btn.setEnabled(True)
        self.pull_btn.setEnabled(True)
        if self._scan_status:
            self.status_label.setText(self._scan_status)
        TrackingDetailDialog(detail, self).exec()

    def _on_detail_fail(self, message: str, _detail: str):
        self.scan_btn.setEnabled(True)
        self.pull_btn.setEnabled(True)
        if self._scan_status:
            self.status_label.setText(self._scan_status)
        else:
            self.status_label.setText(f"查询详情失败：{message}")
        QMessageBox.warning(self, "运单详情", message)
