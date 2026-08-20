from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.batch_modify_service import (
    ModifyPreviewRow,
    apply_modifications,
)
from app.services.sensitive_word_service import (
    FIELD_NAMES,
    aggregate_hits,
    export_results,
    load_full_config,
    load_keyword_rules,
    load_scan_profiles,
    save_full_config,
    scan_paths,
)
from app.workers import TaskWorker


class LexiconDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("词库与扫描规则")
        self.resize(860, 520)
        self.build_ui()
        self.reload()

    def build_ui(self):

        root = QVBoxLayout(self)

        profile_hint = QLabel(
            "物流商扫描规则：迈创默认第18行、快越达默认第30行。"
            "以后加新物流商，点「添加物流商规则」即可。"
        )
        profile_hint.setObjectName("SecondaryText")
        profile_hint.setWordWrap(True)
        root.addWidget(profile_hint)

        self.profile_table = QTableWidget()
        self.profile_table.setColumnCount(5)
        self.profile_table.setHorizontalHeaderLabels(
            ["代码", "名称", "起始行", "表头行", "工作表"]
        )
        self.profile_table.verticalHeader().setVisible(False)
        self.profile_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.Stretch
        )
        self.profile_table.setMaximumHeight(170)
        root.addWidget(self.profile_table)

        profile_btns = QHBoxLayout()
        add_profile_btn = QPushButton("添加物流商规则")
        add_profile_btn.setObjectName("SecondaryButton")
        add_profile_btn.clicked.connect(self.add_profile)
        delete_profile_btn = QPushButton("删除物流商规则")
        delete_profile_btn.setObjectName("SecondaryButton")
        delete_profile_btn.clicked.connect(self.delete_profile)
        profile_btns.addWidget(add_profile_btn)
        profile_btns.addWidget(delete_profile_btn)
        profile_btns.addStretch()
        root.addLayout(profile_btns)

        add_row = QHBoxLayout()
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("敏感词")
        self.category_edit = QLineEdit()
        self.category_edit.setPlaceholderText("分类，例如 合规")
        self.whitelist_edit = QLineEdit()
        self.whitelist_edit.setPlaceholderText("白名单短语，逗号分隔")
        add_btn = QPushButton("添加到词库")
        add_btn.setObjectName("SecondaryButton")
        add_btn.clicked.connect(self.add_keyword)
        add_row.addWidget(self.keyword_edit)
        add_row.addWidget(self.category_edit)
        add_row.addWidget(self.whitelist_edit, 1)
        add_row.addWidget(add_btn)
        root.addLayout(add_row)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["启用", "敏感词", "分类", "白名单", "备注"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        delete_btn = QPushButton("删除选中")
        delete_btn.setObjectName("SecondaryButton")
        delete_btn.clicked.connect(self.delete_selected)
        save_btn = QPushButton("保存词库")
        save_btn.clicked.connect(self.save)
        buttons.addWidget(delete_btn)
        buttons.addStretch()
        buttons.addWidget(save_btn)
        root.addLayout(buttons)

    def reload(self):

        data = load_full_config()
        profiles = data.get("scan_profiles") or []
        self.profile_table.setRowCount(len(profiles))
        for index, item in enumerate(profiles):
            self._fill_profile_row(index, item)

        keywords = data.get("keywords") or []
        self.table.setRowCount(len(keywords))

        for index, item in enumerate(keywords):
            check = QCheckBox()
            check.setChecked(bool(item.get("enabled", True)))
            self.table.setCellWidget(index, 0, check)
            self.table.setItem(
                index, 1, QTableWidgetItem(str(item.get("keyword", "")))
            )
            self.table.setItem(
                index, 2, QTableWidgetItem(str(item.get("category", "")))
            )
            self.table.setItem(
                index,
                3,
                QTableWidgetItem(
                    "，".join(item.get("whitelist_phrases") or [])
                ),
            )
            self.table.setItem(
                index, 4, QTableWidgetItem(str(item.get("remark", "")))
            )

    def add_keyword(self):

        keyword = self.keyword_edit.text().strip()
        if not keyword:
            QMessageBox.warning(self, "缺少敏感词", "请先填写要加入词库的词。")
            return

        row = self.table.rowCount()
        self.table.insertRow(row)
        check = QCheckBox()
        check.setChecked(True)
        self.table.setCellWidget(row, 0, check)
        self.table.setItem(row, 1, QTableWidgetItem(keyword))
        self.table.setItem(
            row, 2, QTableWidgetItem(self.category_edit.text().strip())
        )
        self.table.setItem(
            row, 3, QTableWidgetItem(self.whitelist_edit.text().strip())
        )
        self.table.setItem(row, 4, QTableWidgetItem(""))
        self.keyword_edit.clear()

    def add_profile(self):

        row = self.profile_table.rowCount()
        self.profile_table.insertRow(row)
        self._fill_profile_row(
            row,
            {
                "carrier_code": "",
                "carrier_name": "",
                "data_start_row": 2,
                "header_row": 1,
                "sheet_name": "",
            },
        )

    def _make_row_spin(self, value: int) -> QSpinBox:

        spin = QSpinBox()
        spin.setRange(1, 500)
        spin.setValue(max(1, int(value or 1)))
        return spin

    def _fill_profile_row(self, row: int, item: dict):

        start = self._make_row_spin(item.get("data_start_row") or 1)
        header = self._make_row_spin(item.get("header_row") or 1)
        start.valueChanged.connect(
            lambda value, target=header: target.setValue(max(value - 1, 1))
        )

        self.profile_table.setItem(
            row, 0, QTableWidgetItem(str(item.get("carrier_code", "")))
        )
        self.profile_table.setItem(
            row, 1, QTableWidgetItem(str(item.get("carrier_name", "")))
        )
        self.profile_table.setCellWidget(row, 2, start)
        self.profile_table.setCellWidget(row, 3, header)
        self.profile_table.setItem(
            row, 4, QTableWidgetItem(str(item.get("sheet_name", "")))
        )

    def _collect_profiles(self) -> list[dict]:

        result = []
        for row in range(self.profile_table.rowCount()):
            code_item = self.profile_table.item(row, 0)
            code = code_item.text().strip().upper() if code_item else ""
            if not code:
                continue
            name_item = self.profile_table.item(row, 1)
            sheet_item = self.profile_table.item(row, 4)
            start = self.profile_table.cellWidget(row, 2)
            header = self.profile_table.cellWidget(row, 3)
            start_row = start.value() if start is not None else 1
            header_row = header.value() if header is not None else max(start_row - 1, 1)
            result.append(
                {
                    "carrier_code": code,
                    "carrier_name": name_item.text().strip() if name_item else "",
                    "data_start_row": start_row,
                    "header_row": header_row,
                    "sheet_name": sheet_item.text().strip() if sheet_item else "",
                }
            )
        return result

    def delete_profile(self):

        rows = sorted(
            {index.row() for index in self.profile_table.selectedIndexes()},
            reverse=True,
        )
        if not rows:
            QMessageBox.information(self, "未选择", "请先点选要删除的物流商规则。")
            return
        for row in rows:
            self.profile_table.removeRow(row)

    def delete_selected(self):

        rows = sorted(
            {index.row() for index in self.table.selectedIndexes()},
            reverse=True,
        )
        for row in rows:
            self.table.removeRow(row)

    def _split_whitelist(self, text: str) -> list[str]:

        result = []
        for part in text.replace("，", ",").split(","):
            phrase = part.strip()
            if phrase:
                result.append(phrase)
        return result

    def save(self):

        keywords = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            keyword = item.text().strip() if item else ""
            if not keyword:
                continue
            check = self.table.cellWidget(row, 0)
            keywords.append(
                {
                    "keyword": keyword,
                    "category": (
                        self.table.item(row, 2).text().strip()
                        if self.table.item(row, 2)
                        else ""
                    ),
                    "enabled": bool(
                        check is not None and check.isChecked()
                    ),
                    "fields": list(FIELD_NAMES),
                    "whitelist_phrases": self._split_whitelist(
                        self.table.item(row, 3).text()
                        if self.table.item(row, 3)
                        else ""
                    ),
                    "remark": (
                        self.table.item(row, 4).text().strip()
                        if self.table.item(row, 4)
                        else ""
                    ),
                }
            )

        data = load_full_config()
        data["keywords"] = keywords
        data["scan_profiles"] = self._collect_profiles()
        save_full_config(data)
        QMessageBox.information(self, "已保存", "词库和扫描起始行已写入中央配置。")
        self.accept()


def format_cell_labels(labels: list[str], limit: int = 3) -> str:

    unique = list(dict.fromkeys(labels))
    if not unique:
        return "—"
    if len(unique) <= limit:
        return "、".join(unique)
    return "、".join(unique[:limit]) + f" 等{len(unique)}处"


def suggested_new_value(original: str, keyword: str) -> str:

    text = original or ""
    if keyword and keyword in text:
        return text.replace(keyword, "").strip()
    return text


class HitDetailDialog(QDialog):

    def __init__(self, aggregate: dict, parent=None):
        super().__init__(parent)
        self.aggregate = aggregate
        self.hits = list(aggregate.get("details") or [])
        self._worker = None
        self.updated_hits: list = []
        self.setWindowTitle(
            f"命中明细  {aggregate.get('file_name', '')} / {aggregate.get('keyword', '')}"
        )
        self.resize(920, 460)
        self.build_ui()
        self.render_rows()

    def build_ui(self):

        root = QVBoxLayout(self)
        hint = QLabel(
            "每一行对应一个命中单元格。写入前请先关闭 Excel 里已打开的同一文件。"
        )
        hint.setObjectName("SecondaryText")
        hint.setWordWrap(True)
        root.addWidget(hint)

        uniform = QHBoxLayout()
        uniform.addWidget(QLabel("统一新值："))
        self.uniform_edit = QLineEdit()
        self.uniform_edit.setPlaceholderText("填到所有勾选行，例如改成不含敏感词的品名")
        uniform.addWidget(self.uniform_edit, 1)
        apply_uniform = QPushButton("填到勾选行")
        apply_uniform.setObjectName("SecondaryButton")
        apply_uniform.clicked.connect(self.apply_uniform)
        uniform.addWidget(apply_uniform)
        root.addLayout(uniform)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["勾选", "工作表", "单元格", "字段", "当前值", "新值"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        locate_btn = QPushButton("打开并定位选中")
        locate_btn.setObjectName("SecondaryButton")
        locate_btn.clicked.connect(self.locate_selected)
        self.write_button = QPushButton("写入选中单元格")
        self.write_button.setStyleSheet(
            "QPushButton { background:#F58A07; color:white; border:none;"
            "border-radius:6px; padding:9px 18px; font-weight:600; }"
        )
        self.write_button.clicked.connect(self.write_selected)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("SecondaryButton")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(locate_btn)
        buttons.addStretch()
        buttons.addWidget(self.write_button)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

    def render_rows(self):

        keyword = str(self.aggregate.get("keyword") or "")
        self.table.setRowCount(len(self.hits))
        self._checks = []
        self._edits = []

        for index, hit in enumerate(self.hits):
            check = QCheckBox()
            check.setChecked(True)
            self.table.setCellWidget(index, 0, check)
            self._checks.append(check)
            self.table.setItem(index, 1, QTableWidgetItem(hit.sheet_name))
            self.table.setItem(index, 2, QTableWidgetItem(hit.cell_address))
            self.table.setItem(index, 3, QTableWidgetItem(hit.field_name))
            self.table.setItem(index, 4, QTableWidgetItem(hit.original_text))
            edit = QLineEdit()
            edit.setText(suggested_new_value(hit.original_text, keyword))
            self.table.setCellWidget(index, 5, edit)
            self._edits.append(edit)

    def _selected_indexes(self) -> list[int]:

        return [
            index
            for index, check in enumerate(self._checks)
            if check.isChecked()
        ]

    def apply_uniform(self):

        text = self.uniform_edit.text()
        for index in self._selected_indexes():
            self._edits[index].setText(text)

    def locate_selected(self):

        indexes = self._selected_indexes()
        if not indexes:
            QMessageBox.information(self, "未勾选", "请先勾选要定位的单元格。")
            return
        hit = self.hits[indexes[0]]
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

    def write_selected(self):

        indexes = self._selected_indexes()
        if not indexes:
            QMessageBox.information(self, "未勾选", "请先勾选要修改的单元格。")
            return

        rows = []
        for index in indexes:
            hit = self.hits[index]
            rows.append(
                ModifyPreviewRow(
                    path=hit.file_path,
                    file_name=Path(hit.file_path).name,
                    carrier_code="",
                    sheet_name=hit.sheet_name,
                    cell=hit.cell_address,
                    current_value=hit.original_text,
                    new_value=self._edits[index].text(),
                    selected=True,
                )
            )

        preview = "\n".join(
            f"{row.sheet_name}!{row.cell}：{row.current_value} → {row.new_value or '（清空）'}"
            for row in rows[:12]
        )
        confirm = QMessageBox.question(
            self,
            "确认写入",
            f"将修改 {len(rows)} 个单元格：\n\n{preview}",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        if self._worker and self._worker.isRunning():
            QMessageBox.warning(self, "请等待", "当前已有写入任务。")
            return

        self.write_button.setEnabled(False)

        def job():
            return apply_modifications(rows)

        self._pending_indexes = indexes
        self._worker = TaskWorker(
            job,
            use_com=True,
            module="sensitive",
            parent=self,
        )
        self._worker.succeeded.connect(self._on_written)
        self._worker.failed.connect(self._on_write_fail)
        self._worker.start()

    def _on_written(self, result):

        self.write_button.setEnabled(True)
        if not result.passed:
            QMessageBox.critical(
                self,
                "写入失败",
                "\n".join(result.errors[:12]) or "未知错误",
            )
            return

        removed = [self.hits[index] for index in self._pending_indexes]
        self.updated_hits.extend(removed)
        remaining = [
            hit
            for index, hit in enumerate(self.hits)
            if index not in set(self._pending_indexes)
        ]
        self.hits = remaining
        QMessageBox.information(
            self,
            "已写入",
            f"已修改 {result.success_count} 个单元格。",
        )
        if not self.hits:
            self.accept()
            return
        self.render_rows()

    def _on_write_fail(self, message: str, detail: str):

        self.write_button.setEnabled(True)
        QMessageBox.critical(self, "写入失败", message)


class SensitivePage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self._worker = None
        self.paths: list[Path] = []
        self.build_ui()
        self.refresh_summary()

    def build_ui(self):

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 25, 30, 25)
        root.setSpacing(15)

        title = QLabel("敏感词检查")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "用中央词库匹配品名和材质四个字段。"
            "迈创默认从第18行、快越达默认从第30行开始，可在词库里改。"
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
        lexicon_btn = QPushButton("维护词库")
        lexicon_btn.setObjectName("SecondaryButton")
        lexicon_btn.clicked.connect(self.open_lexicon)
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
        self.modify_button = QPushButton("修改单元格值")
        self.modify_button.setObjectName("SecondaryButton")
        self.modify_button.clicked.connect(self.show_selected_details)
        controls.addWidget(file_btn)
        controls.addWidget(folder_btn)
        controls.addWidget(lexicon_btn)
        controls.addWidget(self.scan_button)
        controls.addWidget(self.export_button)
        controls.addWidget(self.open_button)
        controls.addWidget(self.modify_button)
        layout.addLayout(controls)

        self.summary = QLabel()
        self.summary.setObjectName("SecondaryText")
        layout.addWidget(self.summary)

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
        hint = QLabel("双击一行可查看单元格明细，并直接修改单元格值")
        hint.setObjectName("SecondaryText")
        table_layout.addWidget(hint)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["文件", "敏感词", "分类", "单元格", "命中次数"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.cellDoubleClicked.connect(self.show_details)
        table_layout.addWidget(self.table)
        root.addWidget(table_card, 1)

    def refresh_summary(self):

        rules = load_keyword_rules()
        profiles = load_scan_profiles()
        mc = profiles.get("MC")
        kyd = profiles.get("KYD")
        mc_row = mc.data_start_row if mc else 18
        kyd_row = kyd.data_start_row if kyd else 30
        self.summary.setText(
            f"词库启用 {len(rules)} 个｜"
            f"迈创从第 {mc_row} 行开始｜"
            f"快越达从第 {kyd_row} 行开始"
        )

    def open_lexicon(self):

        dialog = LexiconDialog(self)
        dialog.exec()
        self.refresh_summary()

    def choose_files(self):

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择 Excel",
            "",
            "Excel (*.xlsx)",
        )
        if files:
            self.paths = [Path(item) for item in files]
            self.refresh_summary()
            self.summary.setText(
                self.summary.text() + f"｜已选 {len(self.paths)} 个文件"
            )

    def choose_folder(self):

        directory = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if directory:
            self.paths = [Path(directory)]
            self.refresh_summary()
            self.summary.setText(self.summary.text() + f"｜已选文件夹 {directory}")

    def start_scan(self):

        if not self.paths:
            QMessageBox.warning(self, "未选择", "请先选择文件或文件夹。")
            return

        if not load_keyword_rules():
            QMessageBox.warning(
                self,
                "词库为空",
                "当前没有启用的敏感词。请先点「维护词库」添加后再检查。",
            )
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
        self._render_result()

        if result.errors:
            QMessageBox.warning(self, "部分失败", "\n".join(result.errors[:8]))

    def _render_result(self):

        result = self.result
        if result is None:
            return

        self.file_value.setText(str(result.file_count))
        self.field_value.setText(str(result.field_count))
        self.hit_value.setText(str(result.hit_count))
        self.hit_file_value.setText(str(result.hit_file_count))

        self.table.setRowCount(len(result.aggregates))
        for index, item in enumerate(result.aggregates):
            self.table.setItem(index, 0, QTableWidgetItem(item["file_name"]))
            self.table.setItem(index, 1, QTableWidgetItem(item["keyword"]))
            self.table.setItem(index, 2, QTableWidgetItem(item["category"]))
            self.table.setItem(
                index,
                3,
                QTableWidgetItem(format_cell_labels(item.get("cell_labels") or [])),
            )
            self.table.setItem(index, 4, QTableWidgetItem(str(item["count"])))

    def _on_fail(self, message: str, detail: str):

        self.scan_button.setEnabled(True)
        QMessageBox.critical(self, "检查失败", message)

    def show_selected_details(self):

        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "未选择", "请先点选一行命中结果。")
            return
        self.show_details(row, 0)

    def show_details(self, row: int, column: int):

        if not self.result or row >= len(self.result.aggregates):
            return

        item = self.result.aggregates[row]
        dialog = HitDetailDialog(item, self)
        dialog.exec()
        if dialog.updated_hits:
            self._drop_hits(dialog.updated_hits)

    def _drop_hits(self, removed):

        if not self.result:
            return
        dropped = {id(hit) for hit in removed}
        remaining = [hit for hit in self.result.hits if id(hit) not in dropped]
        self.result.hits = remaining
        self.result.aggregates = aggregate_hits(remaining)
        self.result.hit_count = len(remaining)
        self.result.hit_file_count = len({hit.file_path for hit in remaining})
        self._render_result()

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
