"""渠道规则模式；使用独立的副本发布服务，保留旧手工修改模式。"""
from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app.channel_rules.catalog import load_catalog, refresh_catalog, save_catalog
from app.channel_rules.invoices import CHANNEL_CELLS
from app.channel_rules.models import CARRIERS, Catalog
from app.channel_rules.rules import export_catalog, export_rule_template, read_rules
from app.channel_rules.service import apply_revision, choose_rule, scan_batch, suggest_edit, validate_edit
from app.invoice_config import MERGE_RESULT_ROOT, SYSTEM_ROOT
from app.pages.channel_service_dialog import ChannelServiceDialog
from app.shipment_tracking.providers.nextsls import load_nextsls_providers
from app.styles import PRIMARY_BUTTON_STYLE, style_table
from app.workers import TaskWorker


class ChannelBatchPanel(QWidget):
    def __init__(self, parent=None, *, state_path=None, catalog_path=None):
        super().__init__(parent)
        local = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'InvoiceMergeSystem'
        self.state_path = Path(state_path) if state_path else local / 'channel_modify.json'
        self.catalog_path = Path(catalog_path) if catalog_path else local / 'channel_catalog.json'
        self.catalog, self.scan, self.edits = Catalog(), None, []
        self.worker, self.busy, self._pending_merge = None, False, None
        self.last_output, self._rendering = None, False
        self._controls = []
        self.build_ui()
        self.load_state()
        if not self.cell_edit.text() and self.carrier_combo.currentData() in CHANNEL_CELLS:
            self.cell_edit.setText(CHANNEL_CELLS[self.carrier_combo.currentData()][0])
        try:
            self.catalog = load_catalog(self.catalog_path)
            self.show_catalog_status()
        except (OSError, ValueError) as exc:
            self.catalog_status.setText(str(exc))
        for edit in (self.rule_edit, self.cell_edit, self.output_edit):
            edit.textChanged.connect(self.invalidate)
        self.source_edit.textChanged.connect(self.source_changed)
        self.carrier_combo.currentIndexChanged.connect(self.carrier_changed)
        self.category_combo.currentTextChanged.connect(self.invalidate)
        self.tax_combo.currentIndexChanged.connect(self.invalidate)
        self.delivery_combo.currentIndexChanged.connect(self.invalidate)

    def button(self, label, callback):
        button = QPushButton(label)
        button.clicked.connect(callback)
        self._controls.append(button)
        return button

    def card(self, root, title):
        frame = QFrame()
        frame.setObjectName('Card')
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.addWidget(QLabel(title))
        root.addWidget(frame)
        return layout

    def path_row(self, layout, label, initial, callback, button_text='选择目录'):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        edit = QLineEdit(initial)
        row.addWidget(edit, 1)
        row.addWidget(self.button(button_text, callback))
        self._controls.append(edit)
        layout.addLayout(row)
        return edit

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        first = self.card(root, '1  官方服务目录与内部渠道规则')
        tools = QHBoxLayout()
        self.sync_button = self.button('同步官方服务目录', self.sync_catalog)
        tools.addWidget(self.sync_button)
        tools.addWidget(self.button('查看目录', self.view_catalog))
        tools.addWidget(self.button('导出服务汇总', self.export_services))
        tools.addWidget(self.button('创建空白规则表', self.create_rules))
        tools.addStretch()
        first.addLayout(tools)
        self.catalog_status = QLabel('尚无目录，请先同步；内部分类和仓库适用关系由你们补充。')
        self.catalog_status.setWordWrap(True)
        first.addWidget(self.catalog_status)
        self.rule_edit = self.path_row(first, '规则文件', str(SYSTEM_ROOT / '公共配置' / '渠道规则.xlsx'), self.choose_rules, '选择并读取规则')
        first.addWidget(self.button('读取规则中的内部渠道', self.load_categories))

        second = self.card(root, '2  选择发票批次与本批默认条件')
        self.source_edit = self.path_row(second, '批次目录', str(MERGE_RESULT_ROOT), self.choose_source)
        row = QHBoxLayout()
        row.addWidget(QLabel('物流商'))
        self.carrier_combo = QComboBox()
        self.carrier_combo.addItem('自动识别', 'AUTO')
        for code, name in CARRIERS.items():
            self.carrier_combo.addItem(name, code)
        row.addWidget(self.carrier_combo)
        row.addWidget(QLabel('内部渠道'))
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.setMinimumWidth(150)
        self.category_combo.setPlaceholderText('先读取规则或输入分类')
        row.addWidget(self.category_combo, 1)
        row.addWidget(QLabel('税费'))
        self.tax_combo = QComboBox()
        for name, code in [('请选择', ''), ('包税', '包税'), ('递延（不包税）', '递延')]:
            self.tax_combo.addItem(name, code)
        row.addWidget(self.tax_combo)
        row.addWidget(QLabel('派送'))
        self.delivery_combo = QComboBox()
        for name in ('请选择', '卡派', '快递派'):
            self.delivery_combo.addItem(name, '' if name == '请选择' else name)
        row.addWidget(self.delivery_combo)
        row.addWidget(QLabel('服务单元格'))
        self.cell_edit = QLineEdit()
        self.cell_edit.setPlaceholderText('自动：B1 / B2 / B4')
        self.cell_edit.setMaximumWidth(160)
        row.addWidget(self.cell_edit)
        second.addLayout(row)
        self._controls.extend((self.carrier_combo, self.category_combo, self.tax_combo, self.delivery_combo, self.cell_edit))
        self.output_edit = self.path_row(second, '另存根目录', str(SYSTEM_ROOT / '渠道修改后目录'), self.choose_output)
        note = QLabel('国家和仓库从发票、中央地址库核对。仅修改服务格；税号、交税方式等其他字段需人工核对。')
        note.setWordWrap(True)
        second.addWidget(note)

        third = self.card(root, '3  逐份预览，人工勾选后另存整批')
        actions = QHBoxLayout()
        self.scan_button = self.button('生成匹配预览', self.start_scan)
        self.scan_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        actions.addWidget(self.scan_button)
        actions.addWidget(self.button('勾选已确定项', self.select_ready))
        actions.addWidget(self.button('取消全部勾选', self.clear_selected))
        actions.addStretch()
        self.confirm_button = self.button('确认并另存整批', self.confirm_revision)
        self.confirm_button.setEnabled(False)
        actions.addWidget(self.confirm_button)
        self.open_button = self.button('打开修订目录', self.open_output)
        self.open_button.setEnabled(False)
        actions.addWidget(self.open_button)
        third.addLayout(actions)
        self.status = QLabel('请先准备服务目录和人工渠道规则；不会自动生成未经确认的业务映射。')
        self.status.setWordWrap(True)
        third.addWidget(self.status)
        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels(['选择', '文件', '仓库', '国家', '目标位置', '当前服务', '内部渠道', '税费', '派送', '规则候选 / 人工选择', '拟写入服务（可编辑）', '状态'])
        style_table(self.table)
        self.table.verticalHeader().setVisible(False)
        for col, width in enumerate((48, 190, 110, 65, 170, 190, 140, 130, 110, 390, 240, 240)):
            self.table.setColumnWidth(col, width)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        # 先展示修改前后与状态；候选和逐行条件仍可横向滚动操作。
        self.table.horizontalHeader().moveSection(self.table.horizontalHeader().visualIndex(10), 6)
        self.table.horizontalHeader().moveSection(self.table.horizontalHeader().visualIndex(11), 7)
        self.table.itemChanged.connect(self.item_changed)
        root.addWidget(self.table, 1)

    def invalidate(self, *_):
        if self.busy:
            return
        self.scan, self.edits = None, []
        self.table.setRowCount(0)
        self.confirm_button.setEnabled(False)
        self.status.setText('条件已改变，请重新生成预览。')

    def source_changed(self, *_):
        if not self.busy:
            self.carrier_combo.setCurrentIndex(0)
            self.cell_edit.clear()
            self.invalidate()

    def carrier_changed(self, *_):
        if not self.busy:
            profile = CHANNEL_CELLS.get(self.carrier_combo.currentData())
            self.cell_edit.setText(profile[0] if profile else '')
            self.invalidate()

    def set_busy(self, busy):
        self.busy = busy
        for control in self._controls:
            control.setEnabled(not busy)
        self.table.setEnabled(not busy)
        self.confirm_button.setEnabled(not busy and self.scan is not None and any(e.selected for e in self.edits))
        self.open_button.setEnabled(not busy and self.last_output is not None)
        if not busy and self._pending_merge is not None:
            context, self._pending_merge = self._pending_merge, None
            self.receive_merge(context)

    def run_job(self, job, done, message, *, use_com=False):
        if self.busy:
            return
        self.set_busy(True)
        self.status.setText(message)
        result, failure = [], []
        worker = TaskWorker(job, use_com=use_com, module='channel_rules', parent=self)
        self.worker = worker
        worker.succeeded.connect(lambda value: result.append(value))
        worker.failed.connect(lambda msg, detail: failure.append(msg))

        def finished():
            # 等COM清理和线程退出后才允许新任务，避免“任务已完成但线程仍运行”的竞争。
            pending, self._pending_merge = self._pending_merge, None
            self.set_busy(False)
            try:
                if failure:
                    self.status.setText('操作失败：' + failure[0] + '。源发票未被本功能修改。')
                    QMessageBox.warning(self, '操作未完成', failure[0])
                elif result:
                    done(result[0])
            finally:
                worker.deleteLater()
                if self.worker is worker:
                    self.worker = None
                # 旧任务结果处理完后再接收新批次，确保旧预览不会留在新路径下。
                if pending is not None:
                    self.receive_merge(pending)
        worker.finished.connect(finished)
        worker.start()

    def show_catalog_status(self):
        count = len(self.catalog.services)
        failed = [a.label for a in self.catalog.accounts if a.error]
        times = [a.updated_at for a in self.catalog.accounts if a.updated_at]
        status = f'{len(self.catalog.accounts)} 个账号，{count} 项服务（账号间分别计数）'
        if times:
            status += f'；上次成功同步范围 {min(times)} 至 {max(times)}'
        if failed:
            status += '；本次失败、沿用历史目录：' + '、'.join(failed)
        self.catalog_status.setText(status if count or self.catalog.accounts else '尚无目录，请先同步官方服务目录。')

    def sync_catalog(self):
        previous = self.catalog
        self.invalidate()
        def job():
            configs = load_nextsls_providers()
            if not configs:
                raise ValueError('未找到有效物流账号配置，请核对现有公共配置')
            updated = refresh_catalog(configs, previous)
            save_catalog(self.catalog_path, updated)
            return updated
        def done(updated):
            self.catalog = updated
            self.show_catalog_status()
            self.status.setText('同步结束，请查看各账号结果。人工渠道规则未被同步覆盖。')
        self.run_job(job, done, '正在逐账号读取官方服务目录，不执行下单或运单修改…')

    def choose_rules(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择渠道规则', self.rule_edit.text(), 'Excel (*.xlsx)')
        if path:
            self.rule_edit.setText(path)
            self.load_categories()

    def load_categories(self):
        path = Path(self.rule_edit.text().strip())
        self.invalidate()
        def done(rules):
            self.populate_categories(rules)
            self.status.setText(f'已读取{len(rules.rules)}条启用规则，请选择内部渠道、税费和派送方式。')
        self.run_job(lambda: read_rules(path), done, '正在读取人工渠道规则…')

    def populate_categories(self, rules):
        current = self.category_combo.currentText()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItems(sorted({r.category for r in rules.rules}))
        self.category_combo.setCurrentIndex(-1)
        self.category_combo.setEditText(current)
        self.category_combo.blockSignals(False)

    def new_xlsx_path(self, title, filename):
        path, _ = QFileDialog.getSaveFileName(self, title, filename, 'Excel (*.xlsx)')
        return Path(path if path.lower().endswith('.xlsx') else path + '.xlsx') if path else None

    def create_rules(self):
        path = self.new_xlsx_path('创建空白渠道规则表（不覆盖已有文件）', self.rule_edit.text())
        if path:
            def done(_):
                self.rule_edit.setText(str(path))
                self.status.setText('规则表已创建，请用Excel补充真实映射后保存，再读取规则。')
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            self.run_job(lambda: (export_rule_template(path), path)[1], done, '正在创建规则表…')

    def export_services(self):
        if not self.catalog.accounts:
            QMessageBox.information(self, '尚无目录', '请先同步官方服务目录。')
            return
        path = self.new_xlsx_path('导出官方服务汇总（不覆盖已有文件）', '物流商官方服务汇总.xlsx')
        if path:
            catalog = self.catalog
            self.run_job(lambda: (export_catalog(path, catalog), path)[1],
                         lambda p: self.status.setText('服务目录已导出：' + str(p)), '正在导出服务目录…')

    def view_catalog(self):
        ChannelServiceDialog(self.catalog, parent=self, selection=False).exec()

    def choose_source(self):
        path = QFileDialog.getExistingDirectory(self, '选择一个合并批次或修订后的上传发票目录', self.source_edit.text())
        if path:
            self.source_edit.setText(path)

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, '选择渠道修改另存根目录', self.output_edit.text())
        if path:
            self.output_edit.setText(path)

    def start_scan(self):
        if not self.category_combo.currentText().strip() or not self.tax_combo.currentData() or not self.delivery_combo.currentData():
            QMessageBox.warning(self, '缺少匹配条件', '请先选择内部渠道、税费方式和派送方式。')
            return
        root, rules_path = Path(self.source_edit.text().strip()), Path(self.rule_edit.text().strip())
        carrier, cell = self.carrier_combo.currentData(), self.cell_edit.text().strip()
        catalog = self.catalog
        self.invalidate()
        def job():
            current = {(c.provider_id, c.carrier_code) for c in load_nextsls_providers()}
            if any((a.provider_id, a.carrier_code) not in current for a in catalog.accounts):
                raise ValueError('账号配置与缓存目录不一致，请重新同步服务目录')
            if not catalog.services:
                raise ValueError('尚无有效官方服务目录，请先同步')
            return scan_batch(root, rules_path, catalog, carrier, cell)
        self.run_job(job, self.accept_scan, '正在只读核对模板、仓库国家和匹配规则…')

    def accept_scan(self, scan):
        self.scan, self.catalog = scan, scan.catalog
        self.carrier_combo.blockSignals(True)
        self.carrier_combo.setCurrentIndex(self.carrier_combo.findData(scan.heads[0].carrier))
        self.carrier_combo.blockSignals(False)
        self.cell_edit.blockSignals(True)
        self.cell_edit.setText(scan.heads[0].cell)
        self.cell_edit.blockSignals(False)
        self.populate_categories(scan.rules)
        self.edits = [suggest_edit(scan, head, self.category_combo.currentText(), self.tax_combo.currentData(), self.delivery_combo.currentData()) for head in scan.heads]
        self.render_rows()
        self.status.setText(f'已预览 {len(self.edits)} 份发票，国家 {scan.heads[0].country}；建议尚未勾选，请人工确认。可横向滚动调整逐行条件或选择候选。')
        self.save_state()

    def render_rows(self):
        self._rendering = True
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.edits))
        for index, edit in enumerate(self.edits):
            check = QCheckBox()
            check.setChecked(edit.selected)
            check.toggled.connect(lambda checked, i=index: self.set_selected(i, checked))
            self.table.setCellWidget(index, 0, check)
            values = {1: edit.head.relative, 2: edit.head.warehouse, 3: edit.head.country,
                      4: edit.head.sheet + '!' + edit.head.cell, 5: edit.head.current_value,
                      6: edit.category, 10: edit.new_value, 11: edit.status}
            for col, value in values.items():
                item = QTableWidgetItem(value)
                if col not in (6, 10):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setToolTip(value)
                self.table.setItem(index, col, item)
            for column, name, options, current in [
                (7, 'tax', [('包税', '包税'), ('递延（不包税）', '递延')], edit.tax),
                (8, 'delivery', [('卡派', '卡派'), ('快递派', '快递派')], edit.delivery),
            ]:
                combo = QComboBox()
                for label, data in options:
                    combo.addItem(label, data)
                combo.setCurrentIndex(combo.findData(current))
                combo.currentIndexChanged.connect(lambda _, box=combo, key=name, i=index: self.change_condition(i, **{key: box.currentData()}))
                self.table.setCellWidget(index, column, combo)
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            candidates = QComboBox()
            candidates.addItem('请选择候选' if edit.candidates else '未配置规则', None)
            for rule in edit.candidates:
                candidates.addItem(f'规则{rule.row}：{rule.invoice_value}｜{rule.provider_id}', rule)
                if rule == edit.chosen:
                    candidates.setCurrentIndex(candidates.count() - 1)
            candidates.currentIndexChanged.connect(lambda _, box=candidates, i=index: self.select_candidate(i, box.currentData()))
            layout.addWidget(candidates, 1)
            manual = QPushButton('人工选服务')
            manual.clicked.connect(lambda _, i=index: self.manual_dialog(i))
            layout.addWidget(manual)
            self.table.setCellWidget(index, 9, container)
        self.table.blockSignals(False)
        self._rendering = False
        self.confirm_button.setEnabled(not self.busy and self.scan is not None and any(e.selected for e in self.edits))

    def set_selected(self, index, checked):
        self.edits[index].selected = checked
        self.confirm_button.setEnabled(not self.busy and any(e.selected for e in self.edits))

    def change_condition(self, index, **changes):
        if self.scan is None or self.busy:
            return
        old = self.edits[index]
        self.edits[index] = suggest_edit(self.scan, old.head, changes.get('category', old.category), changes.get('tax', old.tax), changes.get('delivery', old.delivery))
        self.render_rows()

    def select_candidate(self, index, rule):
        if self.scan is None or self.busy:
            return
        if rule is None:
            self.change_condition(index)
            return
        try:
            choose_rule(self.edits[index], rule, self.scan.catalog)
            self.edits[index].selected = False
        except ValueError as exc:
            self.edits[index].new_value = ''
            self.edits[index].selected = False
            self.edits[index].status = str(exc)
        self.render_rows()

    def manual_dialog(self, index):
        edit = self.edits[index]
        dialog = ChannelServiceDialog(self.catalog, edit.head.carrier, self)
        if dialog.exec() == QDialog.Accepted and dialog.selected_service() is not None:
            self.select_manual_service(index, dialog.selected_service())

    def select_manual_service(self, index, service):
        edit = self.edits[index]
        if service is None or service.carrier_code != edit.head.carrier:
            return
        edit.provider_id, edit.service_code, edit.new_value = service.provider_id, service.code, service.name
        edit.chosen, edit.manual, edit.selected = None, True, False
        edit.status = '人工选择，请核对适用性'
        self.render_rows()

    def item_changed(self, item):
        if self._rendering or self.busy or self.scan is None:
            return
        index = item.row()
        if item.column() == 6:
            self.change_condition(index, category=item.text().strip())
        elif item.column() == 10:
            edit = self.edits[index]
            edit.new_value, edit.manual, edit.selected = item.text().strip(), True, False
            edit.status = '人工调整填写值，请核对服务与适用性'
            self.render_rows()

    def select_ready(self):
        if self.scan is None:
            return
        for edit in self.edits:
            try:
                validate_edit(self.scan, edit)
                edit.selected = True
            except ValueError:
                edit.selected = False
        self.render_rows()

    def clear_selected(self):
        for edit in self.edits:
            edit.selected = False
        self.render_rows()

    def confirm_revision(self):
        if self.scan is None or self.busy:
            return
        selected = [e for e in self.edits if e.selected]
        try:
            for edit in selected:
                validate_edit(self.scan, edit)
            if not selected:
                raise ValueError('请先勾选要修改的发票')
        except ValueError as exc:
            QMessageBox.warning(self, '预览尚未确认', str(exc))
            return
        manual = sum(e.manual for e in selected)
        answer = QMessageBox.question(self, '确认另存整批',
            f'修改 {len(selected)} 份，其中人工调整 {manual} 份。其他发票原样复制，保留全部原件。\n'
            '仅修改服务格，税号及其他交税字段不会自动修改。请确认仓库、税费、派送及账号要求已核对。',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        scan, edits, output = self.scan, deepcopy(self.edits), Path(self.output_edit.text().strip())
        def job():
            active = {(c.provider_id, c.carrier_code) for c in load_nextsls_providers()}
            if any((e.provider_id, e.head.carrier) not in active for e in edits if e.selected):
                raise ValueError('所选账号配置已变化，请重新同步并扫描')
            return apply_revision(scan, edits, output, catalog_path=self.catalog_path)
        def done(path):
            self.last_output = path
            self.open_button.setEnabled(True)
            self.status.setText('整批已另存，请上传新目录中的“上传发票”：' + str(path))
            self.save_state()
        self.run_job(job, done, '正在校验预览快照并另存整批，原件保持不变…', use_com=True)

    def open_output(self):
        if self.last_output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output)))

    def receive_merge(self, context):
        if self.busy:
            self._pending_merge = context
            return
        if not isinstance(context, dict) or not isinstance(context.get('directory'), str):
            return
        self.source_edit.setText(context['directory'])
        index = self.carrier_combo.findData(context.get('carrier'))
        self.carrier_combo.setCurrentIndex(max(0, index))
        self.invalidate()
        self.save_state()

    def load_state(self):
        try:
            body = json.loads(self.state_path.read_text(encoding='utf-8'))
            if not isinstance(body, dict):
                return
            for name, widget in [('source', self.source_edit), ('rules', self.rule_edit), ('output', self.output_edit), ('cell', self.cell_edit)]:
                if isinstance(body.get(name), str):
                    widget.setText(body[name])
            for name, widget in [('carrier', self.carrier_combo), ('tax', self.tax_combo), ('delivery', self.delivery_combo)]:
                if isinstance(body.get(name), str) and widget.findData(body[name]) >= 0:
                    widget.setCurrentIndex(widget.findData(body[name]))
            if isinstance(body.get('category'), str):
                self.category_combo.setCurrentText(body['category'])
        except (OSError, ValueError):
            pass

    def save_state(self):
        body = {'source': self.source_edit.text(), 'rules': self.rule_edit.text(), 'output': self.output_edit.text(),
                'cell': self.cell_edit.text(), 'carrier': self.carrier_combo.currentData(),
                'category': self.category_combo.currentText(), 'tax': self.tax_combo.currentData(), 'delivery': self.delivery_combo.currentData()}
        temp = self.state_path.with_name(self.state_path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temp, self.state_path)
        except OSError:
            self.status.setText(self.status.text() + '；本机默认路径保存失败。')
        finally:
            temp.unlink(missing_ok=True)

    def can_close(self):
        if self.busy or self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(self, '任务正在执行', '请等待服务同步、扫描或另存任务结束后再关闭。')
            return False
        return True
