from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
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
    QAbstractItemView,
    QDialog,
    QTextEdit,
)

from app.services.sensitive_word_service import (
    export_results,
    scan_paths,
)
from app.workers import TaskWorker


class SensitivePage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self._worker = None
        self.paths: list[Path] = []
        self.build_ui()

    def build_ui(self):

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 25, 30, 25)
        root.setSpacing(15)

        title = QLabel("敏感词检查")
        title.setObjectName("PageTitle")
        subtitle = QLabel("只扫描品名和材质四个字段，命中后可导出汇总/明细")
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)

        controls = QHBoxLayout()
        file_btn = QPushButton("选择文件")
        file_btn.setObjectName("SecondaryButton")
        file_btn.clicked.connect(self.choose_files)
        folder_btn = QPushButton("选择文件夹")
        folder_btn.setObjectName("SecondaryButton")
        folder_btn.clicked.connect(self.choose_folder)
        self.scan_button = QPushButton("开始检查")
        self.scan_button.setStyleSheet(
            "QPushButton { background:#D64B6A; color:white; border:none;"
            "border-radius:6px; padding:9px 18px; font-weight:600; }"
        )
        self.scan_button.clicked.connect(self.start_scan)
        self.export_button = QPushButton("导出结果")
        self.export_button.setObjectName("SecondaryButton")
        self.export_button.clicked.connect(self.export)
        self.open_button = QPushButton("打开并定位")
        self.open_button.setObjectName("SecondaryButton")
        self.open_button.clicked.connect(self.open_selected)
        controls.addWidget(file_btn)
        controls.addWidget(folder_btn)
        controls.addWidget(self.scan_button)
        controls.addWidget(self.export_button)
        controls.addWidget(self.open_button)
        layout.addLayout(controls)

        stats = QHBoxLayout()
        self.file_value = QLabel("—")
        self.field_value = QLabel("—")
        self.hit_value = QLabel("—")
        self.hit_file_value = QLabel("—")
        for name, label in (
            ("扫描文件", self.file_value),
            ("扫描字段", self.field_value),
            ("命中词数", self.hit_value),
            ("命中文件数", self.hit_file_value),
        ):
            box = QVBoxLayout()
            caption = QLabel(name)
            caption.setObjectName("SecondaryText")
            label.setStyleSheet("font-size:18px; font-weight:700;")
            box.addWidget(caption)
            box.addWidget(label)
            stats.addLayout(box)
        layout.addLayout(stats)
        root.addWidget(card)

        table_card = QFrame()
        table_card.setObjectName("Card")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(18, 16, 18, 16)
        hint = QLabel("双击一行可查看明细")
        hint.setObjectName("SecondaryText")
        table_layout.addWidget(hint)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["文件", "敏感词", "分类", "命中次数"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.cellDoubleClicked.connect(self.show_details)
        table_layout.addWidget(self.table)
        root.addWidget(table_card, 1)

    def choose_files(self):

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择 Excel",
            "",
            "Excel (*.xlsx)",
        )
        if files:
            self.paths = [Path(item) for item in files]

    def choose_folder(self):

        directory = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if directory:
            self.paths = [Path(directory)]

    def start_scan(self):

        if not self.paths:
            QMessageBox.warning(self, "未选择", "请先选择文件或文件夹。")
            return

        if self._worker and self._worker.isRunning():
            return

        paths = list(self.paths)
        self.scan_button.setEnabled(False)

        def job():
            return scan_paths(paths)

        self._worker = TaskWorker(job, module="sensitive", parent=self)
        self._worker.succeeded.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_done(self, result):

        self.scan_button.setEnabled(True)
        self.result = result
        self.file_value.setText(str(result.file_count))
        self.field_value.setText(str(result.field_count))
        self.hit_value.setText(str(result.hit_count))
        self.hit_file_value.setText(str(result.hit_file_count))

        self.table.setRowCount(len(result.aggregates))
        for index, item in enumerate(result.aggregates):
            self.table.setItem(index, 0, QTableWidgetItem(item["file_name"]))
            self.table.setItem(index, 1, QTableWidgetItem(item["keyword"]))
            self.table.setItem(index, 2, QTableWidgetItem(item["category"]))
            self.table.setItem(index, 3, QTableWidgetItem(str(item["count"])))

        if result.errors:
            QMessageBox.warning(self, "部分失败", "\n".join(result.errors[:8]))

    def _on_fail(self, message: str, detail: str):

        self.scan_button.setEnabled(True)
        QMessageBox.critical(self, "检查失败", message)

    def show_details(self, row: int, column: int):

        if not self.result or row >= len(self.result.aggregates):
            return

        item = self.result.aggregates[row]
        lines = [
            f"{hit.sheet_name}!{hit.cell_address}  [{hit.field_name}]",
            f"命中：{hit.keyword}",
            f"原文：{hit.original_text}",
            "",
        ]
        for hit in item["details"]:
            lines.extend(
                [
                    f"{hit.sheet_name}!{hit.cell_address}  [{hit.field_name}]",
                    f"原文：{hit.original_text}",
                    "",
                ]
            )

        dialog = QDialog(self)
        dialog.setWindowTitle("命中明细")
        dialog.resize(620, 360)
        box = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText("\n".join(lines).strip())
        box.addWidget(text)
        dialog.exec()

    def export(self):

        if not self.result or not self.result.hits:
            QMessageBox.information(self, "没有结果", "请先检查并确保有命中。")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出敏感词结果",
            "敏感词检查结果.xlsx",
            "Excel (*.xlsx)",
        )
        if not path:
            return

        output = export_results(self.result, Path(path))
        QMessageBox.information(self, "已导出", str(output))

    def open_selected(self):

        if self.result is None or self.table.currentRow() < 0:
            return

        row = self.table.currentRow()
        if row >= len(self.result.aggregates):
            return

        item = self.result.aggregates[row]
        hit = item["details"][0]

        try:
            import win32com.client as win32

            excel = win32.Dispatch("Excel.Application")
            excel.Visible = True
            excel.AskToUpdateLinks = False
            workbook = excel.Workbooks.Open(
                hit.file_path,
                UpdateLinks=0,
                ReadOnly=True,
            )
            ws = workbook.Worksheets(hit.sheet_name)
            ws.Activate()
            ws.Range(hit.cell_address).Select()
        except Exception as exc:
            QMessageBox.critical(self, "打开失败", str(exc))
