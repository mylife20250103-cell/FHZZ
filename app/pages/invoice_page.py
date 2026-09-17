from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import (
    QDate,
    QUrl,
)
from PySide6.QtGui import QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)

from app.date_ids import (
    format_date_id_range,
    iter_date_ids,
    today_date_id,
)
from app.app_logging import log_event
from app.services.batch_service import (
    STAGE_LABELS,
    STATUS_CHECK_PASSED,
    STATUS_COMPLETED,
    STATUS_CONTENT_MERGED,
    STATUS_FIRST_SCAN_PASSED,
    STATUS_MERGE_PLAN_READY,
    STATUS_QUICK_MERGED,
    STATUS_SECOND_SCAN_PASSED,
    BatchRecord,
    complete_batch,
    enforce_single_active,
    ensure_batch_after_first_scan,
    load_batch,
    missing_official_outputs,
    official_output_dir,
    scan_result_from_snapshot,
)
from app.invoice_config import INVOICE_MANUAL_SCAN_ROOT
from app.services.invoice_content_merge_service import run_content_merge
from app.services.invoice_prepare_service import run_prepare_merge
from app.services.invoice_result_check_service import run_result_check
from app.services.invoice_scan_service import (
    load_source_entries,
    resolve_invoice_scan_directories,
    scan_original_invoices,
)
from app.shipment_tracking.providers.nextsls import (
    ForwarderPortal,
    carrier_portal_label,
    is_browser_url,
    portals_grouped_by_carrier,
    portals_share_same_host,
)
from app.workers import TaskWorker


class InvoicePage(QWidget):

    def __init__(
        self,
        parent=None,
    ):

        super().__init__(parent)

        self.extra_directories = []

        self.scan_result = None

        self.current_batch: BatchRecord | None = None

        self.current_batch_id = None

        self._worker: TaskWorker | None = None
        self._primary_action = "scan"
        self._skip_restore = False
        self._order_portals: dict[str, tuple[ForwarderPortal, ...]] = {}

        self.build_ui()

        self.restore_active_batch()

    def showEvent(self, event: QShowEvent):

        super().showEvent(event)
        self.refresh_source_combo()
        self.refresh_paths()
        self.refresh_order_portals()

    # =====================================================
    # UI
    # =====================================================

    def build_ui(self):

        root = QVBoxLayout(self)

        root.setContentsMargins(
            30,
            25,
            30,
            25,
        )

        root.setSpacing(15)

        # =================================================
        # 标题
        # =================================================

        title = QLabel(
            "发票中心"
        )

        title.setObjectName(
            "PageTitle"
        )

        subtitle = QLabel(
            "按日期范围扫描一个物流商的原始发票，"
            "批次和合并结果始终写到今天。"
            "与询价中心互不依赖。"
            "合并后可在本页打开货代下单后台。"
        )

        subtitle.setObjectName(
            "PageSubtitle"
        )

        root.addWidget(title)
        root.addWidget(subtitle)

        # =================================================
        # Stepper
        # =================================================

        step_card = QFrame()
        step_card.setObjectName("Card")

        step_layout = QHBoxLayout(
            step_card
        )

        step_layout.setContentsMargins(
            18,
            13,
            18,
            13,
        )

        self.step_labels = []

        steps = [
            "① 原始扫描",
            "② 快速合并",
            "③ 二次扫描",
            "④ MergePlan",
            "⑤ 内容合并",
            "⑥ 结果检查",
            "⑦ 完成",
        ]

        for index, text in enumerate(
            steps
        ):

            label = QLabel(text)

            if index == 0:

                label.setStyleSheet(
                    """
                    color:#1677FF;
                    font-weight:700;
                    """
                )

            else:

                label.setStyleSheet(
                    "color:#98A1B2;"
                )

            self.step_labels.append(
                label
            )

            step_layout.addWidget(
                label
            )

            if index < len(
                steps
            ) - 1:

                step_layout.addStretch()

        root.addWidget(step_card)

        # =================================================
        # 扫描设置
        # =================================================

        setting_card = QFrame()
        setting_card.setObjectName("Card")

        setting_layout = QVBoxLayout(
            setting_card
        )

        setting_layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )

        section_title = QLabel(
            "1  原始发票扫描"
        )

        section_title.setObjectName(
            "CardTitle"
        )

        setting_layout.addWidget(
            section_title
        )

        controls = QHBoxLayout()

        controls.addWidget(
            QLabel("从")
        )

        self.range_from = QDateEdit()
        self.range_from.setCalendarPopup(True)
        self.range_from.setDisplayFormat("yyyy-MM-dd")
        self.range_from.setDate(QDate.currentDate())
        self.range_from.dateChanged.connect(
            self.refresh_paths
        )
        controls.addWidget(self.range_from)

        controls.addWidget(
            QLabel("到")
        )

        self.range_to = QDateEdit()
        self.range_to.setCalendarPopup(True)
        self.range_to.setDisplayFormat("yyyy-MM-dd")
        self.range_to.setDate(QDate.currentDate())
        self.range_to.dateChanged.connect(
            self.refresh_paths
        )
        controls.addWidget(self.range_to)

        self.output_date_label = QLabel()
        self.output_date_label.setObjectName(
            "SecondaryText"
        )
        controls.addWidget(
            self.output_date_label
        )

        controls.addSpacing(16)

        controls.addWidget(
            QLabel("扫描源：")
        )

        self.source_combo = QComboBox()

        self.source_combo.setMinimumWidth(
            240
        )

        self.source_combo.currentIndexChanged.connect(
            self.refresh_paths
        )

        controls.addWidget(
            self.source_combo
        )

        self.source_info = QLabel()

        self.source_info.setObjectName(
            "SecondaryText"
        )

        controls.addWidget(
            self.source_info,
            1,
        )

        setting_layout.addLayout(
            controls
        )

        actions = QHBoxLayout()

        add_button = QPushButton(
            "＋ 临时追加目录"
        )

        add_button.setObjectName(
            "SecondaryButton"
        )

        add_button.clicked.connect(
            self.add_directory
        )

        actions.addWidget(
            add_button
        )

        self.extra_scan_button = QPushButton(
            "扫描临时追加目录"
        )

        self.extra_scan_button.setObjectName(
            "SecondaryButton"
        )

        self.extra_scan_button.setEnabled(
            False
        )

        self.extra_scan_button.clicked.connect(
            self.start_extra_scan
        )

        actions.addWidget(
            self.extra_scan_button
        )

        self.rescan_button = QPushButton(
            "重新扫描"
        )

        self.rescan_button.setObjectName(
            "SecondaryButton"
        )

        self.rescan_button.clicked.connect(
            self.start_scan
        )

        actions.addWidget(
            self.rescan_button
        )

        self.reset_button = QPushButton(
            "返回到原始扫描"
        )

        self.reset_button.setObjectName(
            "SecondaryButton"
        )

        self.reset_button.clicked.connect(
            self.reset_to_initial
        )

        actions.addWidget(
            self.reset_button
        )

        actions.addStretch()

        self.open_merged_button = QPushButton(
            "打开已合并发票"
        )
        self.open_merged_button.setObjectName(
            "SecondaryButton"
        )
        self.open_merged_button.clicked.connect(
            self.open_merged_invoices
        )
        self.open_merged_button.setVisible(False)
        actions.addWidget(
            self.open_merged_button
        )

        self.primary_button = QPushButton(
            "开始原始扫描"
        )

        self.primary_button.setStyleSheet(
            """
            QPushButton {
                background:#1677FF;
                color:white;
                border:none;
                border-radius:6px;
                padding:9px 20px;
                font-weight:600;
            }

            QPushButton:hover {
                background:#1269DD;
            }

            QPushButton:disabled {
                background:#C8D0D9;
            }
            """
        )

        self.primary_button.clicked.connect(
            self.on_primary_clicked
        )

        actions.addWidget(
            self.primary_button
        )

        setting_layout.addLayout(
            actions
        )

        self.path_list = QListWidget()

        self.path_list.setMaximumHeight(
            80
        )

        setting_layout.addWidget(
            self.path_list
        )

        root.addWidget(
            setting_card
        )

        # =================================================
        # Overview
        # =================================================

        overview = QFrame()
        overview.setObjectName("Card")

        overview_layout = QVBoxLayout(
            overview
        )

        overview_layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )

        overview_title = QLabel(
            "2  扫描结果"
        )

        overview_title.setObjectName(
            "CardTitle"
        )

        overview_layout.addWidget(
            overview_title
        )

        stats = QHBoxLayout()

        self.date_id_value = QLabel("—")
        self.invoice_value = QLabel("—")
        self.carton_value = QLabel("—")
        self.source_value = QLabel("—")
        self.warehouse_value = QLabel("—")
        self.carrier_value = QLabel("—")
        self.batch_value = QLabel("—")
        self.stage_value = QLabel("—")
        self.error_value = QLabel("—")

        items = [
            (
                "DateID",
                self.date_id_value,
            ),
            (
                "BatchID",
                self.batch_value,
            ),
            (
                "当前阶段",
                self.stage_value,
            ),
            (
                "发票文件",
                self.invoice_value,
            ),
            (
                "总箱数",
                self.carton_value,
            ),
            (
                "SourceID",
                self.source_value,
            ),
            (
                "仓库数",
                self.warehouse_value,
            ),
            (
                "物流商",
                self.carrier_value,
            ),
            (
                "异常数",
                self.error_value,
            ),
        ]

        for name, label in items:

            box = QVBoxLayout()

            title_label = QLabel(name)

            title_label.setObjectName(
                "SecondaryText"
            )

            label.setStyleSheet(
                """
                font-size:16px;
                font-weight:700;
                """
            )

            box.addWidget(
                title_label
            )

            box.addWidget(label)

            stats.addLayout(box)

        overview_layout.addLayout(
            stats
        )

        self.status_label = QLabel(
            "等待扫描"
        )

        self.status_label.setStyleSheet(
            """
            padding:9px;
            background:#F5F7FB;
            border-radius:5px;
            """
        )

        overview_layout.addWidget(
            self.status_label
        )

        root.addWidget(overview)

        # =================================================
        # 仓库汇总
        # =================================================

        detail_card = QFrame()
        detail_card.setObjectName("Card")

        detail_layout = QVBoxLayout(
            detail_card
        )

        detail_layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )

        detail_title = QLabel(
            "3  仓库 / 物流商汇总"
        )

        detail_title.setObjectName(
            "CardTitle"
        )

        detail_layout.addWidget(
            detail_title
        )

        self.table = QTableWidget()

        self.table.setColumnCount(4)

        self.table.setHorizontalHeaderLabels(
            [
                "CarrierCode",
                "WarehouseCode",
                "箱数",
                "SourceID 数",
            ]
        )

        self.table.setEditTriggers(
            QTableWidget.NoEditTriggers
        )

        self.table.verticalHeader().setVisible(
            False
        )

        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )

        detail_layout.addWidget(
            self.table
        )

        root.addWidget(
            detail_card,
            1,
        )

        order_card = QFrame()
        order_card.setObjectName("Card")
        order_layout = QVBoxLayout(order_card)
        order_layout.setContentsMargins(18, 16, 18, 16)
        order_layout.setSpacing(10)

        order_title = QLabel("4  货代下单")
        order_title.setObjectName("CardTitle")
        order_layout.addWidget(order_title)

        self.order_hint = QLabel(
            "选择货代和下单账号后，用系统默认浏览器打开登录页。"
            "不会自动登录，也不会自动下单。"
        )
        self.order_hint.setObjectName("SecondaryText")
        self.order_hint.setWordWrap(True)
        order_layout.addWidget(self.order_hint)

        order_row = QHBoxLayout()
        order_row.addWidget(QLabel("货代："))
        self.order_carrier_combo = QComboBox()
        self.order_carrier_combo.setMinimumWidth(160)
        self.order_carrier_combo.currentIndexChanged.connect(
            self.refresh_order_accounts
        )
        order_row.addWidget(self.order_carrier_combo)

        order_row.addSpacing(12)
        order_row.addWidget(QLabel("下单账号："))
        self.order_account_combo = QComboBox()
        self.order_account_combo.setMinimumWidth(220)
        order_row.addWidget(self.order_account_combo, 1)

        self.open_portal_button = QPushButton("打开下单后台")
        self.open_portal_button.setObjectName("SecondaryButton")
        self.open_portal_button.clicked.connect(self.open_forwarder_portal)
        order_row.addWidget(self.open_portal_button)
        order_layout.addLayout(order_row)

        root.addWidget(order_card)

        self.refresh_source_combo()
        self.refresh_paths()
        self.refresh_order_portals()

    # =====================================================
    # Date
    # =====================================================

    def scan_range(self) -> tuple[str, str]:
        start = self.range_from.date().toString("yyyyMMdd")
        end = self.range_to.date().toString("yyyyMMdd")
        if start > end:
            start, end = end, start
        return start, end

    def date_id(self):
        return today_date_id()

    # =====================================================
    # Path
    # =====================================================

    def refresh_source_combo(self):

        if not hasattr(self, "source_combo"):
            return

        entries = load_source_entries()
        current_key = self.source_combo.currentData()

        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem(
            "请选择物流商扫描源",
            "",
        )

        for entry in entries:

            carrier = entry.carrier_code or "—"
            label = f"{carrier}｜{entry.source_key}"
            self.source_combo.addItem(
                label,
                entry.source_key,
            )

        if current_key:

            index = self.source_combo.findData(
                current_key
            )

            if index >= 0:
                self.source_combo.setCurrentIndex(
                    index
                )

        self.source_combo.blockSignals(False)

    def selected_source(self):

        key = self.source_combo.currentData()

        if not key:
            return None

        for entry in load_source_entries():

            if entry.source_key == key:
                return entry

        return None

    def _select_source_from_records(self, records):

        carriers = {
            record.carrier_code
            for record in records
            if record.carrier_code
        }

        if len(carriers) != 1:
            return

        carrier = next(iter(carriers))

        for entry in load_source_entries():

            if entry.carrier_code != carrier:
                continue

            index = self.source_combo.findData(
                entry.source_key
            )

            if index < 0:
                return

            self.source_combo.blockSignals(True)
            self.source_combo.setCurrentIndex(index)
            self.source_combo.blockSignals(False)
            self.refresh_paths()
            return

    def refresh_paths(self):

        if not hasattr(self, "path_list"):
            return

        if hasattr(self, "output_date_label"):
            start, end = self.scan_range()
            self.output_date_label.setText(
                f"输出 DateID：{self.date_id()}（今天）｜"
                f"扫描 {format_date_id_range(start, end)}"
            )

        entry = self.selected_source()

        self.path_list.clear()

        if entry:

            self.path_list.addItem(
                f"[中央·{entry.carrier_code}] "
                f"{entry.path}"
            )

            extra_count = len(
                self.extra_directories
            )

            extra_text = (
                f"，已追加 {extra_count} 个临时目录"
                if extra_count
                else ""
            )

            self.source_info.setText(
                f"本次只扫 {entry.carrier_code}"
                f"{extra_text}"
            )

        else:

            if load_source_entries():

                self.source_info.setText(
                    "请先选择一个物流商，再开始扫描"
                )

            else:

                self.source_info.setText(
                    "尚未配置中央扫描源"
                )

        for path in self.extra_directories:

            self.path_list.addItem(
                f"[临时] {path}"
            )

        self._refresh_extra_scan_button()

    def _refresh_extra_scan_button(self, busy: bool = False):

        if not hasattr(self, "extra_scan_button"):
            return

        self.extra_scan_button.setEnabled(
            (not busy) and bool(self.extra_directories)
        )

    def add_directory(self):

        start_dir = (
            str(INVOICE_MANUAL_SCAN_ROOT)
            if INVOICE_MANUAL_SCAN_ROOT.exists()
            else ""
        )

        directory = (
            QFileDialog
            .getExistingDirectory(
                self,
                "临时追加原始发票目录",
                start_dir,
            )
        )

        if not directory:
            return

        path = Path(directory)

        if (
            path
            not in self.extra_directories
        ):

            self.extra_directories.append(
                path
            )

        self.refresh_paths()

    # =====================================================
    # 主按钮
    # =====================================================

    def _action_for_status(self, status: str | None) -> tuple[str, str]:

        mapping = {
            None: ("开始原始扫描", "scan"),
            STATUS_FIRST_SCAN_PASSED: ("准备合并", "prepare_merge"),
            STATUS_QUICK_MERGED: ("准备合并", "prepare_merge"),
            STATUS_SECOND_SCAN_PASSED: ("准备合并", "prepare_merge"),
            STATUS_MERGE_PLAN_READY: ("开始内容合并", "content_merge"),
            STATUS_CONTENT_MERGED: ("检查结果", "result_check"),
            STATUS_CHECK_PASSED: ("完成 Batch", "complete"),
            STATUS_COMPLETED: ("已完成", ""),
        }

        text, action = mapping.get(
            status,
            ("开始原始扫描", "scan"),
        )

        if (
            self.current_batch is not None
            and status in {
                STATUS_CONTENT_MERGED,
                STATUS_CHECK_PASSED,
            }
            and missing_official_outputs(self.current_batch)
        ):
            return "开始内容合并", "content_merge"

        return text, action

    def _next_step_hint(self, status: str | None) -> str:

        if (
            self.current_batch is not None
            and status in {
                STATUS_CONTENT_MERGED,
                STATUS_CHECK_PASSED,
            }
            and missing_official_outputs(self.current_batch)
        ):
            return (
                "最终发票已不在合并结果目录，"
                "下一步请重新点「开始内容合并」。"
            )

        text, action = self._action_for_status(status)

        hints = {
            "prepare_merge": (
                "下一步请点「准备合并」，"
                "将连续完成快速合并、二次扫描和 MergePlan。"
            ),
            "content_merge": "下一步请点「开始内容合并」。",
            "result_check": "下一步请点「检查结果」。",
            "complete": (
                "该 Batch 已经做过结果检查，"
                "下一步请点「完成 Batch」。"
            ),
            "": "该 Batch 已完成，不能再修改。",
            "scan": "下一步请先完成原始扫描。",
        }

        return hints.get(
            action,
            f"下一步请点「{text}」。",
        )

    def refresh_primary_button(self):

        status = (
            self.current_batch.status
            if self.current_batch
            else None
        )

        text, action = self._action_for_status(status)

        self._primary_action = action
        self.primary_button.setText(text)

        enabled = bool(action) and (
            self._worker is None
            or not self._worker.isRunning()
        )

        self.primary_button.setEnabled(enabled)
        self.rescan_button.setVisible(
            self.current_batch is not None
        )
        self.open_merged_button.setVisible(
            self.merged_invoice_dir() is not None
        )

    def on_primary_clicked(self):

        action = getattr(
            self,
            "_primary_action",
            "scan",
        )

        if action == "scan":
            self.start_scan()
        elif action == "prepare_merge":
            self.start_prepare_merge()
        elif action == "content_merge":
            self.start_content_merge()
        elif action == "result_check":
            self.start_result_check()
        elif action == "complete":
            self.start_complete_batch()

    def _set_busy(self, busy: bool, text: str = ""):

        self.primary_button.setEnabled(not busy)
        self.rescan_button.setEnabled(not busy)
        self.reset_button.setEnabled(not busy)
        self.open_merged_button.setEnabled(not busy)
        self.source_combo.setEnabled(not busy)
        if hasattr(self, "order_carrier_combo"):
            self.order_carrier_combo.setEnabled(not busy)
            self.order_account_combo.setEnabled(not busy)
            if busy:
                self.open_portal_button.setEnabled(False)
            else:
                self.refresh_order_accounts()
        if hasattr(self, "range_from"):
            self.range_from.setEnabled(not busy)
            self.range_to.setEnabled(not busy)
        self._refresh_extra_scan_button(busy=busy)

        if busy and text:
            self.status_label.setText(text)
            self.status_label.setStyleSheet(
                """
                padding:9px;
                background:#F5F7FB;
                border-radius:5px;
                """
            )

    def _busy_running(self) -> bool:

        if self._worker is not None and self._worker.isRunning():

            QMessageBox.warning(
                self,
                "请等待",
                "当前已有任务正在执行。",
            )

            return True

        return False

    def _reload_current_batch(self):

        if self.current_batch is None:
            return None

        record = load_batch(self.current_batch.directory)

        if record is not None:
            self.apply_batch(record)

        return record

    def _show_pass(self, message: str):

        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            """
            padding:9px;
            color:#087A45;
            background:#E8F7EF;
            border-radius:5px;
            """
        )

    def _show_fail(self, message: str, errors: list[str] | None = None):

        preview = message

        if errors:
            preview += "\n\n" + "\n".join(errors[:10])

            if len(errors) > 10:
                preview += f"\n……还有 {len(errors)-10} 条异常"

        self.status_label.setText(preview)
        self.status_label.setStyleSheet(
            """
            padding:9px;
            color:#B42318;
            background:#FFF0F0;
            border-radius:5px;
            """
        )

    def _run_job(self, job, stage: str, on_success, busy_text: str, use_com=False):

        if self._busy_running():
            return

        batch_id = self.current_batch_id or ""

        self._set_busy(True, busy_text)

        self._worker = TaskWorker(
            job,
            use_com=use_com,
            module="invoice",
            batch_id=batch_id,
            stage=stage,
            parent=self,
        )

        self._worker.succeeded.connect(on_success)
        self._worker.failed.connect(self._on_task_failed)
        self._worker.start()

    # =====================================================
    # Scan
    # =====================================================

    def start_scan(self):

        entry = self.selected_source()
        self._start_scan_directories(
            resolve_invoice_scan_directories(
                source_directory=entry.path if entry else None,
                extra_directories=self.extra_directories,
                extra_only=False,
            ),
            empty_message=(
                "请先选择一个物流商扫描源。"
            ),
        )

    def start_extra_scan(self):

        if not self.extra_directories:

            QMessageBox.warning(
                self,
                "扫描临时追加目录",
                "请先点击「＋ 临时追加目录」，"
                "选择要扫描的发票路径。",
            )
            return

        self._start_scan_directories(
            resolve_invoice_scan_directories(
                source_directory=None,
                extra_directories=self.extra_directories,
                extra_only=True,
            ),
            empty_message="请先临时追加目录。",
        )

    def _start_scan_directories(
        self,
        directories: list[Path],
        empty_message: str,
    ):

        if self._worker is not None and self._worker.isRunning():

            QMessageBox.warning(
                self,
                "请等待",
                "当前已有任务正在执行。",
            )

            return

        if not directories:

            QMessageBox.warning(
                self,
                "没有扫描目录",
                empty_message,
            )

            return

        date_id = self.date_id()
        start, end = self.scan_range()
        allowed_date_ids = iter_date_ids(start, end)

        self._set_busy(True, "正在扫描原始发票...")

        def job():

            result = scan_original_invoices(
                date_id=date_id,
                directories=directories,
                allowed_date_ids=allowed_date_ids,
            )

            batch_info = None

            if result.passed:

                record, action = (
                    ensure_batch_after_first_scan(
                        date_id,
                        result,
                    )
                )

                batch_info = (record, action)

            return result, batch_info

        self._worker = TaskWorker(
            job,
            module="invoice",
            stage="1",
            parent=self,
        )

        self._worker.succeeded.connect(
            self._on_scan_finished
        )

        self._worker.failed.connect(
            self._on_task_failed
        )

        self._worker.start()

    def _on_scan_finished(self, payload):

        self._set_busy(False)

        result, batch_info = payload

        self.scan_result = result

        self.render_result(result)

        if not result.passed:
            self.current_batch = None
            self.current_batch_id = None
            self.batch_value.setText("—")
            self.stage_value.setText("① 原始扫描")
            self.update_stepper(1)
            self.refresh_primary_button()
            return

        record, action = batch_info

        self._skip_restore = False
        self.apply_batch(record)

        next_hint = self._next_step_hint(record.status)
        stage_name = STAGE_LABELS.get(
            record.stage,
            record.status,
        )

        if action == "reused":

            message = (
                "PASS｜发票未变化，"
                f"复用 Batch：{record.batch_id}｜"
                f"当前：{stage_name}"
            )

            dialog_text = (
                "扫描结果与当前未完成 Batch 完全一致，"
                "已复用原 BatchID：\n\n"
                f"{record.batch_id}\n\n"
                "没有创建新的 B000x。\n"
                f"当前进度：{stage_name}\n"
                f"{next_hint}"
            )

        else:

            message = (
                "PASS｜原始扫描通过，"
                f"已创建 Batch：{record.batch_id}"
            )

            dialog_text = (
                "Batch 已创建：\n\n"
                f"{record.batch_id}\n\n"
                f"{next_hint}"
            )

        self.status_label.setText(message)

        self.status_label.setStyleSheet(
            """
            padding:9px;
            color:#087A45;
            background:#E8F7EF;
            border-radius:5px;
            """
        )

        log_event(
            "invoice",
            message,
            batch_id=record.batch_id,
            stage="1",
        )

        QMessageBox.information(
            self,
            "原始扫描通过",
            dialog_text,
        )

    def _on_task_failed(self, message: str, detail: str):

        self._set_busy(False)
        self.refresh_primary_button()

        self.status_label.setText(
            "任务失败：\n" + message
        )

        self.status_label.setStyleSheet(
            """
            padding:9px;
            color:#B42318;
            background:#FFF0F0;
            border-radius:5px;
            """
        )

        QMessageBox.critical(
            self,
            "任务失败",
            message,
        )

    def start_prepare_merge(self):

        if self.current_batch is None:
            return

        batch = self.current_batch

        self._run_job(
            lambda: run_prepare_merge(batch),
            "2-4",
            self._on_prepare_merge_finished,
            "正在准备合并：快速合并 → 二次扫描 → MergePlan...",
        )

    def _on_prepare_merge_finished(self, result):

        self._set_busy(False)
        record = self._reload_current_batch()

        if result.passed:
            self._show_pass(
                "PASS｜准备合并完成，"
                f"{result.group_count} 个合并分组"
            )
            QMessageBox.information(
                self,
                "准备合并完成",
                (
                    f"Batch：{result.batch_id}\n"
                    f"已连续完成快速合并、二次扫描、MergePlan。\n"
                    f"将生成 {result.group_count} 个最终发票文件。\n\n"
                    "下一步是内容合并。"
                ),
            )
        else:
            stage_name = {
                "quick_merge": "快速合并",
                "second_scan": "二次扫描",
                "merge_plan": "MergePlan",
            }.get(result.stopped_at, "准备合并")

            self._show_fail(
                f"FAILED｜{stage_name}失败",
                result.errors,
            )
            QMessageBox.critical(
                self,
                f"{stage_name}失败",
                "\n".join(result.errors[:12]) or "未知错误",
            )

        if record:
            self.apply_batch(record)

    def start_content_merge(self):

        if self.current_batch is None:
            return

        batch = self.current_batch

        self._run_job(
            lambda: run_content_merge(batch),
            "5",
            self._on_content_merge_finished,
            "正在用 Excel COM 合并发票内容...",
            use_com=True,
        )

    def _on_content_merge_finished(self, result):

        self._set_busy(False)
        record = self._reload_current_batch()

        if result.passed:
            self._show_pass(
                "PASS｜内容合并完成，"
                f"{len(result.output_files)} 个最终文件"
            )
            QMessageBox.information(
                self,
                "内容合并完成",
                "\n".join(result.output_files),
            )
        else:
            self._show_fail("FAILED｜内容合并失败", result.errors)
            self._show_content_merge_fail_dialog(result)

        if record:
            self.apply_batch(record)

    def _show_content_merge_fail_dialog(self, result):

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("内容合并失败")
        box.setText("内容合并失败。已按源发票做自检，方便排查。")
        report = getattr(result, "diagnose_report_path", "") or ""
        preview = "\n".join(result.errors[:10]) or "未知错误"
        if report:
            preview += f"\n\n自检报告：{report}"
        box.setInformativeText(preview)
        box.setDetailedText("\n".join(result.errors))
        open_btn = None
        if report:
            open_btn = box.addButton("打开自检报告", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if open_btn is not None and box.clickedButton() == open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(report))

    def start_result_check(self):

        if self.current_batch is None:
            return

        batch = self.current_batch

        self._run_job(
            lambda: run_result_check(batch),
            "6",
            self._on_result_check_finished,
            "正在检查合并结果...",
        )

    def _on_result_check_finished(self, result):

        self._set_busy(False)
        record = self._reload_current_batch()

        if result.passed:
            message = "PASS｜结果检查通过"
            if result.warning_count:
                message += f"｜发现敏感词警告：{result.warning_count} 条"
            self._show_pass(message)
            QMessageBox.information(
                self,
                "结果检查通过",
                message,
            )
        else:
            self._show_fail("FAILED｜结果检查失败", result.errors)
            QMessageBox.critical(
                self,
                "结果检查失败",
                "\n".join(result.errors[:12]) or "未知错误",
            )

        if record:
            self.apply_batch(record)

    def start_complete_batch(self):

        if self.current_batch is None:
            return

        try:
            record = complete_batch(self.current_batch)
        except Exception as exc:
            self._show_fail("完成 Batch 失败", [str(exc)])
            QMessageBox.critical(self, "完成失败", str(exc))
            return

        self.apply_batch(record)
        warning = record.status_payload.get("CleanupWarning", "")
        self._notify_batch_completed(record, extra=warning)

    def merged_invoice_dir(self) -> Path | None:

        if self.current_batch is None:
            return None
        directory = official_output_dir(self.current_batch)
        if directory.exists():
            return directory
        return None

    def open_merged_invoices(self):

        directory = self.merged_invoice_dir()
        if directory is None:
            QMessageBox.warning(
                self,
                "找不到目录",
                "还没有合并结果目录。请确认内容合并已经完成。",
            )
            return
        try:
            os.startfile(str(directory))
        except Exception as exc:
            QMessageBox.critical(self, "打开失败", str(exc))

    def _preferred_order_carrier(self) -> str:
        records = []
        if self.scan_result is not None:
            records = list(self.scan_result.records)
        carriers = {
            record.carrier_code
            for record in records
            if record.carrier_code
        }
        if len(carriers) == 1:
            return next(iter(carriers))
        source = self.selected_source()
        if source and source.carrier_code:
            return source.carrier_code
        return ""

    def refresh_order_portals(self, force_carrier: str = ""):
        if not hasattr(self, "order_carrier_combo"):
            return
        grouped = portals_grouped_by_carrier()
        self._order_portals = grouped
        wanted = (
            force_carrier
            or self.order_carrier_combo.currentData()
            or self._preferred_order_carrier()
        )
        self.order_carrier_combo.blockSignals(True)
        self.order_carrier_combo.clear()
        if not grouped:
            self.order_carrier_combo.addItem("未配置货代账号", "")
        else:
            for code, items in grouped.items():
                self.order_carrier_combo.addItem(
                    carrier_portal_label(code, items),
                    code,
                )
            index = self.order_carrier_combo.findData(wanted)
            if index >= 0:
                self.order_carrier_combo.setCurrentIndex(index)
        self.order_carrier_combo.blockSignals(False)
        self.refresh_order_accounts()

    def refresh_order_accounts(self):
        if not hasattr(self, "order_account_combo"):
            return
        current = self.order_account_combo.currentData()
        code = self.order_carrier_combo.currentData() or ""
        accounts = self._order_portals.get(code, ())
        self.order_account_combo.blockSignals(True)
        self.order_account_combo.clear()
        if not accounts:
            self.order_account_combo.addItem("请先选择货代", "")
        else:
            for item in accounts:
                self.order_account_combo.addItem(item.name, item.provider_id)
            index = self.order_account_combo.findData(current)
            if index >= 0:
                self.order_account_combo.setCurrentIndex(index)
        self.order_account_combo.blockSignals(False)
        if not accounts:
            self.order_hint.setText(
                "未读到货代下单网址。请确认 OneDrive 里有"
                "「发票系统\\公共配置\\forwarder_api.ini」。"
            )
        elif portals_share_same_host(accounts):
            self.order_hint.setText(
                "只打开浏览器登录页，不会自动登录或下单。"
                "该货代多家账号共用同一网站，打开后请登录所选账号。"
            )
        else:
            self.order_hint.setText(
                "只打开浏览器登录页，不会自动登录，也不会自动下单。"
            )
        worker_busy = (
            self._worker is not None and self._worker.isRunning()
        )
        self.open_portal_button.setEnabled(
            bool(accounts) and not worker_busy
        )

    def _selected_order_portal(self) -> ForwarderPortal | None:
        code = self.order_carrier_combo.currentData() or ""
        provider_id = self.order_account_combo.currentData() or ""
        for item in self._order_portals.get(code, ()):
            if item.provider_id == provider_id:
                return item
        return None

    def open_forwarder_portal(self):
        if self._busy_running():
            return
        portal = self._selected_order_portal()
        if portal is None:
            QMessageBox.warning(
                self,
                "请选择账号",
                "请先选择货代和下单账号。",
            )
            return
        url = portal.portal_url
        if not is_browser_url(url):
            QMessageBox.warning(
                self,
                "网址无效",
                "该账号没有可用的下单网址。",
            )
            return
        opened = QDesktopServices.openUrl(QUrl(url))
        if not opened:
            QMessageBox.critical(
                self,
                "打开失败",
                f"无法用默认浏览器打开：\n{url}",
            )
            return
        log_event(
            "invoice",
            f"打开货代下单后台 {portal.name} {url}",
            batch_id=self.current_batch_id or "",
        )

    def _notify_batch_completed(self, record: BatchRecord, extra: str = ""):

        if extra:
            self._show_pass(
                f"COMPLETED｜{record.batch_id} 已完成。"
                "最终发票已保留；快速合并临时目录未完全删掉。"
            )
            body = (
                f"{record.batch_id} 已锁定，不可再修改。\n\n"
                "最终发票在「合并结果」目录。\n"
                "快速合并临时目录可能被 Excel 或 OneDrive 占用，"
                "稍后可手动删除：\n\n"
                f"{extra}"
                "\n\n下一步可在本页「货代下单」选择账号，"
                "打开浏览器登录下单。"
            )
        else:
            self._show_pass(
                f"COMPLETED｜{record.batch_id} 已完成，"
                "快速合并临时目录已清理"
            )
            body = (
                f"{record.batch_id} 已锁定，不可再修改。\n\n"
                "下一步可在本页「货代下单」选择账号，"
                "打开浏览器登录下单。"
            )

        box = QMessageBox(self)
        box.setWindowTitle("Batch 已完成")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(body)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def clear_scan_view(self):

        self.scan_result = None
        self.current_batch = None
        self.current_batch_id = None

        self.date_id_value.setText(
            self.date_id()
        )
        self.invoice_value.setText("—")
        self.carton_value.setText("—")
        self.source_value.setText("—")
        self.warehouse_value.setText("—")
        self.carrier_value.setText("—")
        self.batch_value.setText("—")
        self.stage_value.setText("① 原始扫描")
        self.error_value.setText("—")
        self.table.setRowCount(0)

        self.update_stepper(1)
        self.refresh_primary_button()
        self.refresh_order_portals()

    def reset_to_initial(self):

        if self._busy_running():
            return

        reply = QMessageBox.question(
            self,
            "回到扫描前",
            "将清空当前页面的扫描结果和进度显示，"
            "回到「开始原始扫描」。\n\n"
            "不会删除已完成的 Batch，"
            "也不会改磁盘上的未完成 Batch。\n"
            "本页在重新扫描前不再自动恢复未完成 Batch。",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self._skip_restore = True
        self.clear_scan_view()

        self.status_label.setText(
            "已回到扫描前初始状态。"
            "请选择一个物流商扫描源后开始扫描。"
        )

        self.status_label.setStyleSheet(
            """
            padding:9px;
            color:#1677FF;
            background:#EAF2FF;
            border-radius:5px;
            """
        )

        log_event(
            "invoice",
            "用户回到扫描前初始状态",
            stage="reset",
        )

    def restore_active_batch(self):

        date_id = self.date_id()

        self.date_id_value.setText(date_id)

        if self._skip_restore:
            return

        try:
            record = enforce_single_active(date_id)

        except Exception as exc:

            self.status_label.setText(
                "读取 Batch 失败："
                f"{exc}"
            )

            return

        if record is None:

            self.current_batch = None
            self.current_batch_id = None
            self.batch_value.setText("—")
            self.stage_value.setText("① 原始扫描")
            self.error_value.setText("—")
            self.update_stepper(1)
            self.refresh_primary_button()
            return

        result = scan_result_from_snapshot(
            record.snapshot
        )

        self.scan_result = result
        self.render_result(result)
        self.apply_batch(record)
        self._select_source_from_records(result.records)

        self.status_label.setText(
            "已恢复未完成 Batch："
            f"{record.batch_id}｜"
            f"{record.status}"
        )

        self.status_label.setStyleSheet(
            """
            padding:9px;
            color:#1677FF;
            background:#EAF2FF;
            border-radius:5px;
            """
        )

    def apply_batch(self, record: BatchRecord):

        self.current_batch = record
        self.current_batch_id = record.batch_id
        self.batch_value.setText(record.batch_id)

        stage = record.stage or 1

        self.stage_value.setText(
            STAGE_LABELS.get(stage, record.status)
        )

        self.update_stepper_for_batch(record)
        self.refresh_primary_button()

    def update_stepper_for_batch(self, record: BatchRecord):

        stage = record.stage or 1

        if record.status in {
            STATUS_FIRST_SCAN_PASSED,
            STATUS_QUICK_MERGED,
            STATUS_SECOND_SCAN_PASSED,
        }:
            self.update_stepper(
                stage + 1,
                linked_until=4,
            )
            return

        self.update_stepper(
            stage + 1 if stage < 7 else 7
        )

    def update_stepper(
        self,
        active_stage: int,
        linked_until: int | None = None,
    ):

        end_stage = (
            linked_until
            if linked_until is not None
            else active_stage
        )

        for index, label in enumerate(
            self.step_labels,
            start=1,
        ):

            if index < active_stage:

                label.setStyleSheet(
                    """
                    color:#087A45;
                    font-weight:700;
                    """
                )

            elif active_stage <= index <= end_stage:

                label.setStyleSheet(
                    """
                    color:#1677FF;
                    font-weight:700;
                    """
                )

            else:

                label.setStyleSheet(
                    "color:#98A1B2;"
                )

    # =====================================================
    # Render
    # =====================================================

    def render_result(
        self,
        result,
    ):

        self.date_id_value.setText(
            self.date_id()
        )

        self.invoice_value.setText(
            str(
                result.invoice_count
            )
        )

        self.carton_value.setText(
            str(
                result.carton_count
            )
        )

        self.source_value.setText(
            str(
                result.source_count
            )
        )

        self.warehouse_value.setText(
            str(
                result.warehouse_count
            )
        )

        self.carrier_value.setText(
            str(
                result.carrier_count
            )
        )

        self.error_value.setText(
            str(len(result.errors))
        )

        self.carton_value.setText(
            str(
                result.carton_count
            )
        )

        self.source_value.setText(
            str(
                result.source_count
            )
        )

        self.warehouse_value.setText(
            str(
                result.warehouse_count
            )
        )

        self.carrier_value.setText(
            str(
                result.carrier_count
            )
        )

        # ======================================
        # 汇总
        # ======================================

        groups = {}

        for record in result.records:

            key = (
                record.carrier_code,
                record.warehouse_code,
            )

            if key not in groups:

                groups[key] = {
                    "cartons": set(),
                    "sources": set(),
                }

            groups[key][
                "cartons"
            ].add(
                record.carton_number
            )

            groups[key][
                "sources"
            ].add(
                record.source_id
            )

        self.table.setRowCount(
            len(groups)
        )

        for row_index, (
            key,
            value,
        ) in enumerate(
            sorted(groups.items())
        ):

            carrier, warehouse = key

            self.table.setItem(
                row_index,
                0,
                QTableWidgetItem(
                    carrier
                ),
            )

            self.table.setItem(
                row_index,
                1,
                QTableWidgetItem(
                    warehouse
                ),
            )

            self.table.setItem(
                row_index,
                2,
                QTableWidgetItem(
                    str(
                        len(
                            value[
                                "cartons"
                            ]
                        )
                    )
                ),
            )

            self.table.setItem(
                row_index,
                3,
                QTableWidgetItem(
                    str(
                        len(
                            value[
                                "sources"
                            ]
                        )
                    )
                ),
            )

        if result.passed:

            text = "PASS｜原始发票校验通过"
            if result.warnings:
                text += "\n\n" + "\n".join(result.warnings[:8])
            self.status_label.setText(text)

            if result.warnings:
                self.status_label.setStyleSheet(
                    """
                    padding:9px;
                    color:#8A5A00;
                    background:#FFF7E6;
                    border-radius:5px;
                    """
                )
            else:
                self.status_label.setStyleSheet(
                    """
                    padding:9px;
                    color:#087A45;
                    background:#E8F7EF;
                    border-radius:5px;
                    """
                )

        else:

            preview = "\n".join(
                result.errors[:10]
            )

            if len(
                result.errors
            ) > 10:

                preview += (
                    f"\n……还有 "
                    f"{len(result.errors)-10}"
                    " 条异常"
                )

            self.status_label.setText(
                "FAILED｜存在关键异常，"
                "禁止进入下一步\n\n"
                + preview
            )

            self.status_label.setStyleSheet(
                """
                padding:9px;
                color:#B42318;
                background:#FFF0F0;
                border-radius:5px;
                """
            )

        self.refresh_order_portals(
            force_carrier=self._preferred_order_carrier()
        )