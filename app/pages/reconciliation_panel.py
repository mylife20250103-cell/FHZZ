"""发票中心第5块：独立的只读预估、货代文字核对及导出。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from app.invoice_config import LOCAL_TEMP_ROOT
from app.reconciliation.export import HEADERS, export_results, row_values
from app.reconciliation.invoices import scan_directory, suggest_directory
from app.reconciliation.parser import parse_reports
from app.reconciliation.service import reconcile
from app.styles import style_table
from app.workers import TaskWorker


class ReconciliationPanel(QFrame):
    def __init__(self, parent=None, *, directory: Path | None = None):
        super().__init__(parent)
        self.setObjectName('Card')
        self.scan = None
        self.rows = []
        self.result_text = ''
        self.worker = None
        self.busy = False
        self._pending_merge = None
        root = QVBoxLayout(self)
        root.setContentsMargins(18,16,18,16)
        root.setSpacing(10)
        title = QLabel('5  货件数据核对')
        title.setObjectName('CardTitle')
        root.addWidget(title)
        hint = QLabel('每箱(长+2)×(宽+2)×(高+2)÷6000，整票体积重合计与实重合计取大，再向上取整到1kg。'
                      '货代最终计费重超过核准上限时申请重测。原发票只读。')
        hint.setObjectName('SecondaryText'); hint.setWordWrap(True)
        root.addWidget(hint)
        source = QHBoxLayout()
        source.addWidget(QLabel('合并结果：'))
        self.source_edit = QLineEdit(str(directory if directory is not None else suggest_directory()))
        source.addWidget(self.source_edit,1)
        self.browse_button = QPushButton('选择历史目录')
        self.scan_button = QPushButton('读取合并结果')
        for button in (self.browse_button,self.scan_button): button.setObjectName('SecondaryButton')
        source.addWidget(self.browse_button); source.addWidget(self.scan_button)
        root.addLayout(source)
        self.report_edit = QPlainTextEdit()
        self.report_edit.setPlaceholderText('粘贴迈创报数，例如：\n'
            'MC010295345(FBA19W1Y2BQ0，FBA19W236CYF) 美速达快提卡派 39kg\n'
            '支持多行，结尾通知会单独忽略。快越达文件可先读取预估。')
        self.report_edit.setMinimumHeight(100); self.report_edit.setMaximumHeight(155)
        root.addWidget(self.report_edit)
        actions = QHBoxLayout()
        self.compare_button = QPushButton('开始核对')
        self.compare_button.setObjectName('PrimaryButton')
        self.only_remeasure = QCheckBox('只看需重测')
        self.export_button = QPushButton('导出当前结果')
        self.export_button.setObjectName('SecondaryButton')
        actions.addWidget(self.compare_button); actions.addWidget(self.only_remeasure)
        actions.addStretch(); actions.addWidget(self.export_button)
        root.addLayout(actions)
        self.status = QLabel('合并成功后自动带入本次目录，也可读取历史目录；双击结果查看货箱明细。')
        self.status.setWordWrap(True); self.status.setObjectName('SecondaryText')
        root.addWidget(self.status)
        self.table = QTableWidget(0,len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(310)
        style_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for c,width in enumerate([155,220,85,70,190,190,55,100,115,130,110,110,130,110,145,310,280]):
            self.table.setColumnWidth(c,width)
        # 正常桌面宽度先展示做判断所需的列，支持数据仍可横向展开。
        header = self.table.horizontalHeader()
        for visual, logical in enumerate([0,2,1,11,12,13,14,6,5,4,7,8,9,10,15,16,3]):
            header.moveSection(header.visualIndex(logical),visual)
        root.addWidget(self.table)
        self._controls = [self.source_edit,self.browse_button,self.scan_button,
                          self.report_edit,self.only_remeasure,self.table]
        self.source_edit.textChanged.connect(self.invalidate_source)
        self.report_edit.textChanged.connect(self.invalidate_comparison)
        self.browse_button.clicked.connect(self.choose_directory)
        self.scan_button.clicked.connect(self.start_scan)
        self.compare_button.clicked.connect(self.start_comparison)
        self.only_remeasure.toggled.connect(self.render_rows)
        self.export_button.clicked.connect(self.export_current)
        self.table.cellDoubleClicked.connect(self.show_boxes)
        self.update_buttons()

    def update_buttons(self):
        self.compare_button.setEnabled(not self.busy and self.scan is not None and bool(self.scan.invoices))
        self.export_button.setEnabled(not self.busy and bool(self.visible_rows()))

    def invalidate_source(self, *_):
        if self.busy:
            return
        self.scan = None
        self.invalidate_comparison()
        self.status.setText('目录已改变，请读取合并结果。')

    def invalidate_comparison(self, *_):
        if self.busy:
            return
        self.rows, self.result_text = [], ''
        self.render_rows()
        self.status.setText('报数已改变，请重新开始核对。')

    def visible_rows(self):
        return [r for r in self.rows if not self.only_remeasure.isChecked() or r.needs_remeasure]

    def render_rows(self, *_):
        rows = self.visible_rows()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row_values(row)):
                text = '' if value is None else (f'{value:.3f}' if isinstance(value,Decimal) else str(value))
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if isinstance(value,(Decimal,int)):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r,c,item)
            if row.needs_remeasure:
                self.table.item(r,14).setForeground(Qt.darkRed)
        self.table.resizeRowsToContents()
        self.update_buttons()

    def set_busy(self, value):
        self.busy = value
        for control in self._controls:
            control.setEnabled(not value)
        self.update_buttons()
        if not value and self._pending_merge is not None:
            context,self._pending_merge = self._pending_merge,None
            self.receive_merge(context)

    def run_job(self, job, done, message):
        if self.busy:
            return
        self.set_busy(True); self.status.setText(message)
        successes, failures = [], []
        worker = TaskWorker(job,module='shipment_reconciliation',parent=self)
        self.worker = worker
        worker.succeeded.connect(lambda value:successes.append(value))
        worker.failed.connect(lambda message,detail:failures.append(message))
        def finished():
            pending,self._pending_merge = self._pending_merge,None
            self.worker = None
            self.set_busy(False)
            try:
                if failures:
                    self.status.setText('操作未完成：'+failures[0])
                elif successes:
                    done(successes[0])
            finally:
                worker.deleteLater()
                if pending is not None:
                    self.receive_merge(pending)
        worker.finished.connect(finished)
        worker.start()

    def receive_merge(self, context):
        directory = str(context.get('directory',''))
        if not directory:
            return
        if self.busy:
            self._pending_merge = dict(context)
            return
        # 即使路径相同也重读：同一批次重新合并后文件内容可能已替换。
        self.source_edit.setText(directory)
        self.report_edit.clear()
        self.only_remeasure.setChecked(False)
        self.start_scan()

    def choose_directory(self):
        directory = QFileDialog.getExistingDirectory(self,'选择合并结果目录',self.source_edit.text())
        if directory:
            self.source_edit.setText(directory)

    def start_scan(self):
        if self.busy:
            return
        directory = Path(self.source_edit.text().strip())
        self.invalidate_source()
        self.run_job(lambda:scan_directory(directory),self.accept_scan,'正在只读统计合并结果中的货箱…')

    def accept_scan(self, scan):
        self.scan = scan
        self.rows = reconcile(scan,parse_reports(''))
        self.result_text = ''
        self.render_rows()
        errors = sum(bool(i.issues) for i in scan.invoices)
        self.status.setText(f'已读取 {len(scan.invoices)} 份发票，{errors} 份源数据异常。'
            '粘贴货代报数后开始核对。' if scan.invoices else '未找到MC/KYD合并发票，请核对目录。')

    def start_comparison(self):
        if self.busy or self.scan is None:
            return
        scan, text = self.scan, self.report_edit.toPlainText()
        self.invalidate_comparison()
        def job():
            parsed = parse_reports(text)
            return reconcile(scan,parsed), parsed, text
        self.run_job(job,self.accept_comparison,'正在按货代和完整FBA集合核对…')

    def accept_comparison(self, result):
        self.rows, parsed, self.result_text = result
        self.render_rows()
        remeasure = sum(r.needs_remeasure for r in self.rows)
        attention = sum(r.status not in {'重量在允许范围','待货代报数'} for r in self.rows)
        pending = sum(r.status=='待货代报数' for r in self.rows)
        self.status.setText(f'识别报数 {len(parsed.reports)} 条，忽略通知/其他文字 {len(parsed.ignored_lines)} 行；'
                            f'需重测 {remeasure} 票，待核对/异常 {attention} 行，待报数 {pending} 票。')

    def export_current(self):
        if self.busy or self.scan is None or not self.visible_rows():
            return
        rows, scan, text = list(self.visible_rows()), self.scan, self.result_text
        default = LOCAL_TEMP_ROOT / f'货件核对_{datetime.now():%Y%m%d_%H%M%S}.xlsx'
        # 文件对话框也会处理Qt事件：先冻结快照并让新批次排队，避免切到另一批导出。
        self.set_busy(True)
        try:
            name,_ = QFileDialog.getSaveFileName(self,'导出当前筛选结果',str(default),'Excel (*.xlsx)')
        except Exception:
            self.set_busy(False)
            raise
        if not name:
            self.set_busy(False)
            return
        # 不在交接瞬间消费pending；后台导出finished后再切到新批次。
        self.busy = False
        self.run_job(lambda:export_results(rows,Path(name),raw_text=text,source_directory=scan.directory,
                     scanned_at=scan.scanned_at,protected_paths=[i.path for i in scan.invoices]),
                     lambda path:self.status.setText(f'已导出 {len(rows)} 行核对结果及关联货箱明细：{path}'),
                     '正在导出当前结果、货箱明细和报数原文…')

    def show_boxes(self, row_number, _column):
        rows = self.visible_rows()
        if self.busy or row_number >= len(rows):
            return
        invoice = rows[row_number].invoice
        if invoice is None:
            self.status.setText('此报数尚未唯一匹配源文件，没有可展开的货箱。')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('货箱明细 — '+invoice.path.name)
        dialog.resize(1150,450)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(invoice.cartons),9)
        table.setHorizontalHeaderLabels(['完整箱号','FBA','实重(kg)','长(cm)','宽(cm)','高(cm)',
                                        '原体积重(kg)','公差体积重(kg)','源行'])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        style_table(table)
        for r,c in enumerate(invoice.cartons):
            for col,value in enumerate([c.number,c.fba_id,c.weight,c.length,c.width,c.height,c.volume,c.tolerance_volume,c.source_row]):
                table.setItem(r,col,QTableWidgetItem(f'{value:.3f}' if isinstance(value,Decimal) else str(value)))
        table.resizeColumnsToContents();layout.addWidget(table)
        dialog.exec()

    def can_close(self):
        if self.busy or self.worker is not None:
            self.status.setText('货件核对任务尚未结束，请完成后再关闭窗口。')
            return False
        return True
