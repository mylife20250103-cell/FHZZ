from __future__ import annotations

from pathlib import Path

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

from app.services.batch_modify_service import (
    apply_modifications,
    normalize_cell_address,
    preview_files,
)
from app.workers import TaskWorker


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
        subtitle = QLabel("优先读取 _SystemMeta.ChannelCell，批量修改发票发货渠道")
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
        self.cell_edit.setPlaceholderText("无 _SystemMeta 时使用，例如 B2")
        self.cell_edit.setMaximumWidth(140)
        self.cell_edit.editingFinished.connect(self.refresh_inputs)
        controls.addWidget(self.cell_edit)

        controls.addWidget(QLabel("新值："))
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("新的发货渠道")
        self.value_edit.textChanged.connect(self.refresh_inputs)
        controls.addWidget(self.value_edit)

        self.select_all_button = QPushButton("全选 / 取消全选")
        self.select_all_button.setObjectName("SecondaryButton")
        self.select_all_button.clicked.connect(self.toggle_select_all)
        controls.addWidget(self.select_all_button)

        self.run_button = QPushButton("批量执行")
        self.run_button.setStyleSheet(
            "QPushButton { background:#F58A07; color:white; border:none;"
            "border-radius:6px; padding:9px 18px; font-weight:600; }"
        )
        self.run_button.clicked.connect(self.run_modify)
        controls.addWidget(self.run_button)
        layout.addLayout(controls)

        self.status = QLabel("选择 Excel 文件或文件夹后自动识别 ChannelCell")
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
            ["勾选", "文件名", "CarrierCode", "目标单元格", "当前值", "新值", "状态"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().sectionClicked.connect(
            self._on_header_clicked
        )
        table_layout.addWidget(self.table)
        root.addWidget(table_card, 1)

    def choose_files(self):

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择发票 Excel",
            "",
            "Excel (*.xlsx)",
        )
        if files:
            self.load_paths([Path(item) for item in files])

    def choose_folder(self):

        directory = QFileDialog.getExistingDirectory(self, "选择文件夹")
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

    def toggle_select_all(self):

        if not self.rows:
            return

        all_selected = all(row.selected for row in self.rows)
        new_state = not all_selected

        for row in self.rows:
            row.selected = new_state

        self.render_rows()

    def _on_header_clicked(self, section: int):

        if section == 0:
            self.toggle_select_all()

    def render_rows(self):

        new_value = self.value_edit.text().strip()
        self.table.setRowCount(len(self.rows))

        for index, row in enumerate(self.rows):
            row.new_value = new_value
            check = QCheckBox()
            check.setChecked(row.selected)
            check.stateChanged.connect(
                lambda state, i=index: self._set_selected(i, state)
            )
            self.table.setCellWidget(index, 0, check)
            values = [
                row.file_name,
                row.carrier_code,
                row.cell,
                row.current_value,
                row.new_value,
                row.status,
            ]
            for column, value in enumerate(values, start=1):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))

    def _set_selected(self, index: int, state: int):

        if 0 <= index < len(self.rows):
            self.rows[index].selected = bool(state)

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
