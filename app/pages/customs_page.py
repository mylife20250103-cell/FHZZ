"""三步报关修订界面；文件操作全部交给独立服务及后台线程。"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.customs.models import CARRIERS, REGIONS
from app.customs.service import apply_revision, scan_batch
from app.invoice_config import SYSTEM_ROOT
from app.styles import PRIMARY_BUTTON_STYLE, style_table
from app.workers import TaskWorker


class CustomsPage(QWidget):
    def __init__(self, parent=None, *, state_path=None):
        super().__init__(parent)
        self.state_path = Path(state_path) if state_path else Path(
            os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        ) / "InvoiceMergeSystem" / "customs_modify.json"
        self.scan = None
        self.worker = None
        self.busy = False
        self.last_output = None
        self._pending_merge = None
        self._job_result = None
        self._job_error = None
        self._controls = []
        self.build_ui()
        self.load_state()
        for edit in (self.rule_edit, self.output_edit):
            edit.textChanged.connect(self.invalidate)
        self.source_edit.textChanged.connect(self.source_changed)
        self.threshold.valueChanged.connect(self.invalidate)
        self.carrier_combo.currentIndexChanged.connect(self.invalidate)
        self.region_combo.currentIndexChanged.connect(self.invalidate)

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 20)
        root.setSpacing(10)
        title = QLabel("发票报关修改")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        subtitle = QLabel("按国家规则预览四项申报内容，人工确认后另存整批；上传请使用新目录中的“上传发票”。")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(subtitle)

        rules_card = self.card(root, "1  选择替换规则")
        self.rule_edit = self.path_row(rules_card, "规则文件", str(SYSTEM_ROOT / "报关信息替换"), True)
        options = QHBoxLayout()
        options.addWidget(QLabel("最低相似度"))
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(1, 100)
        self.threshold.setDecimals(2)
        self.threshold.setValue(95)
        self.threshold.setSuffix(" %")
        options.addWidget(self.threshold)
        hint = QLabel(".xlsx：第1行“修改前/修改后”，第2行列名；支持英文材质、HS CODE。修改后全空跳过，部分填写须补齐四项。")
        hint.setWordWrap(True)
        hint.setObjectName("SecondaryText")
        options.addWidget(hint, 1)
        rules_card.addLayout(options)

        files_card = self.card(root, "2  选择已合并发票")
        self.source_edit = self.path_row(files_card, "批次目录", "")
        row = QHBoxLayout()
        row.addWidget(QLabel("物流商"))
        self.carrier_combo = QComboBox()
        self.carrier_combo.addItem("自动识别（按模板）", "AUTO")
        for code, label in CARRIERS.items():
            self.carrier_combo.addItem(label, code)
        row.addWidget(self.carrier_combo)
        row.addWidget(QLabel("规则区域"))
        self.region_combo = QComboBox()
        for code, label in REGIONS.items():
            self.region_combo.addItem(label, code)
        row.addWidget(self.region_combo)
        note = QLabel("请核对发票目的国；皓鹏选择外部生成的现成批次。")
        note.setWordWrap(True)
        note.setObjectName("SecondaryText")
        row.addWidget(note, 1)
        files_card.addLayout(row)
        self.output_edit = self.path_row(files_card, "另存根目录", str(SYSTEM_ROOT / "报关修改后目录"))

        preview_card = self.card(root, "3  扫描、选择候选并确认修改", stretch=1)
        buttons = QHBoxLayout()
        self.scan_button = QPushButton("扫描并生成预览")
        self.scan_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.scan_button.clicked.connect(self.start_scan)
        buttons.addWidget(self.scan_button)
        self.select_all_button = QPushButton("勾选已确定方案")
        self.select_all_button.clicked.connect(lambda: self.select_all(True))
        buttons.addWidget(self.select_all_button)
        self.clear_button = QPushButton("取消全部勾选")
        self.clear_button.clicked.connect(lambda: self.select_all(False))
        buttons.addWidget(self.clear_button)
        buttons.addStretch()
        self.confirm_button = QPushButton("确认修改并另存整批")
        self.confirm_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self.confirm)
        buttons.addWidget(self.confirm_button)
        self.open_button = QPushButton("打开修订目录")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_result)
        buttons.addWidget(self.open_button)
        preview_card.addLayout(buttons)
        self.status = QLabel("请选择规则和一批已合并发票。扫描仅预览，不改文件。")
        self.status.setWordWrap(True)
        preview_card.addWidget(self.status)
        self.table = QTableWidget(0, 13)
        self.table.setHorizontalHeaderLabels([
            "选择", "文件 / 工作表 / 行", "状态", "匹配度", "候选方案 / 规则行",
            "原中文品名", "新中文品名", "原英文品名", "新英文品名",
            "原材质", "新材质", "原海关编码", "新海关编码",
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(120)
        self.table.verticalHeader().hide()
        style_table(self.table)
        widths = [52, 240, 100, 80, 190, 150, 150, 170, 170, 110, 110, 125, 125]
        for col, width in enumerate(widths):
            self.table.setColumnWidth(col, width)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        preview_card.addWidget(self.table, 1)
        self._controls.extend([self.rule_edit, self.source_edit, self.output_edit,
                               self.threshold, self.carrier_combo, self.region_combo, self.scan_button,
                               self.select_all_button, self.clear_button, self.table])

    def card(self, root, title, stretch=0):
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("CardTitle")
        layout.addWidget(label)
        root.addWidget(frame, stretch)
        return layout

    def path_row(self, layout, label, default, is_file=False):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        edit = QLineEdit(default)
        edit.setPlaceholderText("选择或粘贴路径")
        row.addWidget(edit, 1)
        button = QPushButton("选择文件" if is_file else "选择目录")
        def choose():
            if is_file:
                selected, _ = QFileDialog.getOpenFileName(self, label, edit.text(), "替换规则 (*.xlsx)")
            else:
                selected = QFileDialog.getExistingDirectory(self, label, edit.text())
            if selected:
                edit.setText(selected)
        button.clicked.connect(choose)
        row.addWidget(button)
        self._controls.append(button)
        layout.addLayout(row)
        return edit

    def load_state(self):
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                return
            for key, edit in (("rules", self.rule_edit), ("source", self.source_edit), ("output", self.output_edit)):
                if isinstance(state.get(key), str):
                    edit.setText(state[key])
            for key, combo in (("carrier", self.carrier_combo), ("region", self.region_combo)):
                index = combo.findData(state.get(key))
                if index >= 0:
                    combo.setCurrentIndex(index)
            threshold = state.get("threshold", 95)
            if isinstance(threshold, (float, int)) and 1 <= threshold <= 100:
                self.threshold.setValue(threshold)
        except (OSError, ValueError, TypeError):
            pass  # 缺少本机偏好不创建配置，也不影响文件校验。

    def save_state(self):
        state = {"rules": self.rule_edit.text(), "source": self.source_edit.text(),
                 "output": self.output_edit.text(), "carrier": self.carrier_combo.currentData(),
                 "region": self.region_combo.currentData(), "threshold": self.threshold.value()}
        temp = self.state_path.with_name(self.state_path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, self.state_path)
        except OSError as exc:
            self.status.setText(self.status.text() + f"\n本机偏好未保存：{exc}")

    def receive_merge(self, context):
        if self.busy:
            self._pending_merge = dict(context)
            return
        directory = context.get("directory", "")
        if not directory or not Path(directory).is_dir():
            return
        self.source_edit.setText(directory)
        for key, combo in (("carrier", self.carrier_combo), ("country", self.region_combo)):
            index = combo.findData(context.get(key))
            if index >= 0:
                combo.setCurrentIndex(index)
        self.invalidate()
        self.save_state()

    def rule_path(self):
        path = Path(self.rule_edit.text().strip())
        if path.is_dir():
            files = sorted(p for p in path.glob("*.xlsx") if not p.name.startswith("~$"))
            if len(files) != 1:
                raise ValueError("规则目录中需有一份.xlsx；存在多份时，请明确选择具体规则文件")
            path = files[0]
        return path

    def invalidate(self, *_args):
        self.scan = None
        self.table.setRowCount(0)
        self.confirm_button.setEnabled(False)
        self.status.setText("输入已更新，请重新扫描生成预览。")

    def source_changed(self, *_args):
        # 新目录不能继续沿用上一批货代；成功合并通知随后会设置已知货代。
        self.carrier_combo.setCurrentIndex(self.carrier_combo.findData('AUTO'))
        self.invalidate()

    def set_busy(self, busy):
        self.busy = busy
        for control in self._controls:
            control.setEnabled(not busy)
        self.confirm_button.setEnabled(not busy and self.scan is not None)
        self.open_button.setEnabled(not busy and self.last_output is not None)

    def _run(self, task, done):
        if self.busy:
            return
        self._job_result = self._job_error = None
        self.set_busy(True)
        self.worker = TaskWorker(task, use_com=True, module="customs_modify", parent=self)
        self.worker.succeeded.connect(lambda result: setattr(self, "_job_result", result))
        self.worker.failed.connect(lambda message, details: setattr(self, "_job_error", message))
        def finished():
            self.set_busy(False)
            if self._job_error:
                self.status.setText("操作失败：" + self._job_error + "\n原发票未被本模块修改。")
                QMessageBox.warning(self, "报关修改未完成", self._job_error)
            else:
                done(self._job_result)
            if self._pending_merge:
                context, self._pending_merge = self._pending_merge, None
                self.receive_merge(context)
        self.worker.finished.connect(finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(lambda: setattr(self, "worker", None))
        self.worker.start()

    def start_scan(self):
        if self.busy:
            return
        try:
            rules = self.rule_path()
            if not self.source_edit.text().strip():
                raise ValueError("请选择已合并发票批次目录")
            source = Path(self.source_edit.text().strip())
            carrier, region, threshold = self.carrier_combo.currentData(), self.region_combo.currentData(), self.threshold.value()
        except ValueError as exc:
            QMessageBox.warning(self, "请核对输入", str(exc))
            return
        self.invalidate()
        self.status.setText("正在读取规则和整批发票，生成预览…")
        self._run(lambda: scan_batch(source, rules, carrier, region, threshold), self.accept_scan)

    def accept_scan(self, scan):
        self.scan = scan
        self.table.setRowCount(len(scan.rows))
        for r, preview in enumerate(scan.rows):
            check = QCheckBox()
            # 单一方案也需人工勾选；冲突必须先选候选。
            check.setEnabled(bool(preview.candidates))
            self.table.setCellWidget(r, 0, check)
            self.item(r, 1, f"{preview.relative}\n{preview.sheet} · 第{preview.line.row}行")
            self.item(r, 2, "待确认" if len(preview.candidates) == 1 else "待选候选" if preview.candidates else "未匹配")
            self.item(r, 3, "")
            combo = QComboBox()
            combo.addItem("请选择方案", None)
            for index, candidate in enumerate(preview.candidates):
                combo.addItem(f"第{candidate.rule.row}行 · {candidate.rule.after[0]} ({candidate.score:.2f}%)", index)
                combo.setItemData(combo.count() - 1, " | ".join(candidate.rule.after), Qt.ToolTipRole)
            self.table.setCellWidget(r, 4, combo)
            for col, value in zip((5, 7, 9, 11), preview.line.values):
                self.item(r, col, value)
            for col in (6, 8, 10, 12):
                self.item(r, col, "")
            combo.currentIndexChanged.connect(lambda _index, rr=r: self.choose_candidate(rr))
            if len(preview.candidates) == 1:
                combo.setCurrentIndex(1)
                check.setChecked(False)
        matches = sum(bool(r.candidates) for r in scan.rows)
        conflicts = sum(len(r.candidates) > 1 for r in scan.rows)
        self.status.setText(f"货代：{CARRIERS[scan.carrier]}；规则{len(scan.rules.rules)}条，未启用{scan.rules.skipped_empty_rows}行；"
                            f"{len(scan.invoices)}份发票 / {len(scan.rows)}行产品；命中{matches}行，冲突{conflicts}行。请核对四项并勾选；其余原样复制。")
        self.confirm_button.setEnabled(not self.busy)
        self.save_state()

    def item(self, row, column, value):
        item = QTableWidgetItem(str(value))
        item.setToolTip(str(value))
        self.table.setItem(row, column, item)

    def choose_candidate(self, row):
        if self.scan is None:
            return
        index = self.table.cellWidget(row, 4).currentData()
        preview = self.scan.rows[row]
        candidate = preview.candidates[index] if index is not None else None
        for col, value in zip((6, 8, 10, 12), candidate.rule.after if candidate else ("", "", "", "")):
            self.item(row, col, value)
        self.item(row, 3, f"{candidate.score:.2f}%" if candidate else "")
        self.item(row, 2, "待确认" if candidate else "待选候选" if preview.candidates else "未匹配")
        check = self.table.cellWidget(row, 0)
        check.setEnabled(candidate is not None)
        check.setChecked(candidate is not None)

    def select_all(self, checked):
        if self.scan:
            for row in range(len(self.scan.rows)):
                check = self.table.cellWidget(row, 0)
                if check.isEnabled():
                    check.setChecked(checked)

    def selections(self):
        result = {}
        if self.scan:
            for row, preview in enumerate(self.scan.rows):
                index = self.table.cellWidget(row, 4).currentData()
                if self.table.cellWidget(row, 0).isChecked() and index is not None:
                    result[preview.key] = index
        return result

    def confirm(self):
        if self.scan is None or self.busy:
            return
        if not self.output_edit.text().strip():
            QMessageBox.warning(self, "请核对输出", "请选择另存根目录")
            return
        selections, scan = self.selections(), self.scan
        message = (f"将修改{len(selections)}行产品的四项内容，另存整批{len(scan.invoices)}份发票。\n"
                   "未勾选内容原样复制；原发票保留。请确认申报内容符合实际商品。")
        if QMessageBox.question(self, "确认本次修订", message) != QMessageBox.Yes:
            return
        output = Path(self.output_edit.text().strip())
        self.status.setText("正在生成并校验完整修订批次…")
        self._run(lambda: apply_revision(scan, selections, output), self.accept_revision)

    def accept_revision(self, path):
        self.last_output = path
        self.invalidate()
        self.open_button.setEnabled(True)
        self.status.setText(f"修订已生成：{path}\n请上传“上传发票”子目录；记录在“修改记录”中。")
        self.save_state()

    def open_result(self):
        if self.last_output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output)))

    def can_close(self):
        if self.busy:
            QMessageBox.information(self, "任务尚未完成", "报关修改正在处理文件，请等待本次任务完成后退出。")
            return False
        return True

    def closeEvent(self, event):
        if self.can_close():
            super().closeEvent(event)
        else:
            event.ignore()
