from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
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
    QCheckBox,
    QAbstractItemView,
)

from app.invoice_config import MERGE_RESULT_ROOT, QUICK_MERGE_ROOT
from app.services.batch_modify_service import (
    apply_modifications,
    looks_like_merge_output,
    looks_like_source_invoice,
    normalize_cell_address,
    preview_files,
)
from app.workers import TaskWorker

CHECKBOX_STYLE = """
QCheckBox {
    margin: 0px;
    padding: 0px;
    background: transparent;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
}
"""


class BatchEditPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self._worker = None
        self.build_ui()

    def build_ui(self):

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 25, 30, 25)
        root.setSpacing(15)

        title = QLabel("批量修改单元格值")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "默认打开「合并结果」。快越达合并文件是 KYD_仓库_N箱.xls，"
            "不经 Excel，避免上传失败"
        )
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
        controls.addWidget(file_btn)
        controls.addWidget(folder_btn)

        controls.addWidget(QLabel("手工单元格："))
        self.cell_edit = QLineEdit()
        self.cell_edit.setPlaceholderText("快越达合并结果默认 B4")
        self.cell_edit.setMaximumWidth(140)
        self.cell_edit.editingFinished.connect(self.refresh_inputs)
        controls.addWidget(self.cell_edit)

        controls.addWidget(QLabel("新值："))
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("新的发货渠道")
        self.value_edit.textChanged.connect(self.refresh_inputs)
        controls.addWidget(self.value_edit)

        self.run_button = QPushButton("批量执行")
        self.run_button.setStyleSheet(
            "QPushButton { background:#F58A07; color:white; border:none;"
            "border-radius:6px; padding:9px 18px; font-weight:600; }"
        )
        self.run_button.clicked.connect(self.run_modify)
        controls.addWidget(self.run_button)
        layout.addLayout(controls)

        self.status = QLabel("请选择「合并结果」里的 KYD_仓库_N箱.xls，不要选全部发票汇总里的源发票")
        self.status.setObjectName("SecondaryText")
        layout.addWidget(self.status)
        root.addWidget(card)

        table_card = QFrame()
        table_card.setObjectName("Card")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(18, 16, 18, 16)
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["", "文件名", "CarrierCode", "目标单元格", "当前值", "新值", "状态"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 44)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._install_header_checkbox()
        table_layout.addWidget(self.table)
        root.addWidget(table_card, 1)

    def _install_header_checkbox(self):

        header = self.table.horizontalHeader()
        self.header_check = QCheckBox(header)
        self.header_check.setToolTip("全选 / 取消全选")
        self.header_check.setTristate(True)
        self.header_check.setStyleSheet(CHECKBOX_STYLE)
        self.header_check.setCursor(Qt.PointingHandCursor)
        self.header_check.setFixedSize(16, 16)
        self.header_check.clicked.connect(self._on_header_check_clicked)
        header.sectionResized.connect(self._place_header_checkbox)
        header.geometriesChanged.connect(self._place_header_checkbox)
        self.table.horizontalScrollBar().valueChanged.connect(
            self._place_header_checkbox
        )
        self._place_header_checkbox()

    def _place_header_checkbox(self, *_args):

        header = self.table.horizontalHeader()
        size = 16
        x = header.sectionViewportPosition(0)
        width = header.sectionSize(0)
        y = max(0, (header.height() - size) // 2)
        self.header_check.setGeometry(
            x + (width - size) // 2,
            y,
            size,
            size,
        )

    def _picker_start_dir(self) -> str:

        if MERGE_RESULT_ROOT.exists():
            today = MERGE_RESULT_ROOT / datetime.now().strftime("%Y%m%d")
            if today.exists():
                return str(today)
            return str(MERGE_RESULT_ROOT)
        if QUICK_MERGE_ROOT.exists():
            return str(QUICK_MERGE_ROOT)
        return ""

    def choose_files(self):

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择合并后的发票",
            self._picker_start_dir(),
            "Excel (*.xlsx *.xls)",
        )
        if files:
            self.load_paths([Path(item) for item in files])

    def choose_folder(self):

        directory = QFileDialog.getExistingDirectory(
            self,
            "选择合并结果文件夹",
            self._picker_start_dir(),
        )
        if directory:
            self.load_paths([Path(directory)])

    def load_paths(self, paths: list[Path]):

        new_value = self.value_edit.text().strip()
        self.rows = preview_files(
            paths,
            new_value=new_value,
            manual_cell=self.cell_edit.text().strip(),
        )
        self.render_rows()
        merge_count = sum(
            1 for row in self.rows if looks_like_merge_output(Path(row.path))
        )
        source_count = sum(
            1 for row in self.rows if looks_like_source_invoice(Path(row.path))
        )
        if source_count and not merge_count:
            self.status.setText(
                f"已加载 {len(self.rows)} 个源发票，改这些不会更新「合并结果」里的文件。"
                "请改选 发票系统\\合并结果 下的 KYD_仓库_N箱.xls"
            )
        elif merge_count:
            self.status.setText(f"已加载 {len(self.rows)} 个合并结果")
        else:
            self.status.setText(f"已加载 {len(self.rows)} 个文件")

    def _manual_cell(self) -> str:

        return normalize_cell_address(self.cell_edit.text())

    def refresh_inputs(self):

        if not self.rows:
            return

        self._apply_inputs_to_rows()
        self.render_rows()

    def _apply_inputs_to_rows(self):

        new_value = self.value_edit.text().strip()
        manual_cell = self._manual_cell()

        for row in self.rows:
            row.new_value = new_value
            if not row.cell and manual_cell:
                row.cell = manual_cell

    def toggle_select_all(self, selected: bool | None = None):

        if not self.rows:
            return

        if selected is None:
            selected = not all(row.selected for row in self.rows)

        for row in self.rows:
            row.selected = selected

        self.render_rows()

    def _on_header_check_clicked(self):

        select_all = not all(row.selected for row in self.rows)
        self.toggle_select_all(select_all)

    def _sync_header_check(self):

        if not hasattr(self, "header_check"):
            return

        self.header_check.blockSignals(True)
        if not self.rows:
            self.header_check.setCheckState(Qt.Unchecked)
        elif all(row.selected for row in self.rows):
            self.header_check.setCheckState(Qt.Checked)
        elif any(row.selected for row in self.rows):
            self.header_check.setCheckState(Qt.PartiallyChecked)
        else:
            self.header_check.setCheckState(Qt.Unchecked)
        self.header_check.blockSignals(False)
        self._place_header_checkbox()

    def render_rows(self):

        new_value = self.value_edit.text().strip()
        self.table.setRowCount(len(self.rows))

        for index, row in enumerate(self.rows):
            row.new_value = new_value
            check = QCheckBox()
            check.setChecked(row.selected)
            check.setStyleSheet(CHECKBOX_STYLE)
            check.setFixedSize(16, 16)
            check.stateChanged.connect(
                lambda state, i=index: self._set_selected(i, state)
            )
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setAlignment(Qt.AlignCenter)
            cell_layout.addWidget(check)
            self.table.setCellWidget(index, 0, cell)
            values = [
                row.file_name,
                row.carrier_code,
                row.cell,
                row.current_value,
                row.new_value,
                row.status,
            ]
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(str(value))
                if column == 1:
                    item.setToolTip(row.path)
                self.table.setItem(index, column, item)

        self._sync_header_check()

    def _set_selected(self, index: int, state: int):

        if 0 <= index < len(self.rows):
            self.rows[index].selected = bool(state)
            self._sync_header_check()

    def run_modify(self):

        if not self.rows:
            QMessageBox.warning(self, "没有文件", "请先选择文件或文件夹。")
            return

        new_value = self.value_edit.text().strip()
        if not new_value:
            QMessageBox.warning(self, "缺少新值", "请输入要写入的新值。")
            return

        self._apply_inputs_to_rows()

        missing_cell = [
            row.file_name
            for row in self.rows
            if row.selected and not row.cell
        ]
        if missing_cell:
            QMessageBox.warning(
                self,
                "未指定目标单元格",
                "这些文件没有 ChannelCell，请在「手工单元格」填 Excel 地址，"
                "例如 B2：\n\n"
                + "\n".join(missing_cell[:12]),
            )
            self.render_rows()
            return

        selected = [row for row in self.rows if row.selected]
        if not selected:
            QMessageBox.warning(self, "未勾选", "请至少勾选一个文件。")
            return

        source_rows = [
            row.file_name
            for row in selected
            if looks_like_source_invoice(Path(row.path))
        ]
        if source_rows and not any(
            looks_like_merge_output(Path(row.path)) for row in selected
        ):
            answer = QMessageBox.question(
                self,
                "这些不是合并结果",
                "当前勾选的是源发票（例如 IND9_FBA..._快越达发票.xlsx），"
                "改它们不会更新「合并结果」里的 KYD_IND9_1箱.xls。\n\n"
                "请到：\n"
                r"发票系统\合并结果\日期\批次号"
                "\n选择 KYD_仓库_N箱.xls 后再执行。\n\n"
                "仍要修改这些源发票吗？\n\n"
                + "\n".join(source_rows[:8]),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        if self._worker and self._worker.isRunning():
            QMessageBox.warning(self, "请等待", "当前已有任务正在执行。")
            return

        self.run_button.setEnabled(False)
        self.status.setText("正在预检并批量修改...")

        rows = self.rows

        def job():
            return apply_modifications(rows)

        self._worker = TaskWorker(
            job,
            use_com=True,
            module="batch_edit",
            parent=self,
        )
        self._worker.succeeded.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_done(self, result):

        self.run_button.setEnabled(True)
        self.rows = result.rows
        self.render_rows()

        if result.passed:
            self.status.setText(f"全部成功：{result.success_count} 个文件")
            QMessageBox.information(
                self,
                "修改完成",
                f"已成功修改 {result.success_count} 个文件。",
            )
        else:
            self.status.setText("修改失败，已尝试回滚")
            QMessageBox.critical(
                self,
                "修改失败",
                "\n".join(result.errors[:12]) or "未知错误",
            )

    def _on_fail(self, message: str, detail: str):

        self.run_button.setEnabled(True)
        self.status.setText("任务失败：" + message)
        QMessageBox.critical(self, "任务失败", message)
