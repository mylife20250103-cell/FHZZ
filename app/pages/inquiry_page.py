from __future__ import annotations

import os
import subprocess

from pathlib import Path

from PySide6.QtCore import (
    QDate,
    Qt,
)

from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QDateEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)

from app.inquiry_config import (
    INQUIRY_SOURCE_ROOT,
)

from app.services.inquiry_service import (
    ScanResult,
    generate_inquiry_summary,
    resolve_inquiry_scan_directories,
    scan_inquiry_batch,
)


class InquiryPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.extra_directories: list[
            Path
        ] = []

        self.scan_result: (
            ScanResult | None
        ) = None

        self.build_ui()

    # ==========================================
    # UI
    # ==========================================

    def build_ui(self):

        root = QVBoxLayout(self)

        root.setContentsMargins(
            30,
            25,
            30,
            25,
        )

        root.setSpacing(16)

        # ======================================
        # 标题
        # ======================================

        title = QLabel(
            "询价中心"
        )

        title.setObjectName(
            "PageTitle"
        )

        subtitle = QLabel(
            "扫描当天询价明细，"
            "校验后按仓库生成统一询价汇总"
        )

        subtitle.setObjectName(
            "PageSubtitle"
        )

        root.addWidget(title)
        root.addWidget(subtitle)

        # ======================================
        # 1. 扫描设置
        # ======================================

        setup_card = QFrame()

        setup_card.setObjectName(
            "Card"
        )

        setup = QVBoxLayout(
            setup_card
        )

        setup.setContentsMargins(
            18,
            16,
            18,
            16,
        )

        section_title = QLabel(
            "1  选择询价日期"
        )

        section_title.setObjectName(
            "CardTitle"
        )

        setup.addWidget(
            section_title
        )

        controls = QHBoxLayout()

        controls.addWidget(
            QLabel("DateID：")
        )

        self.date_edit = QDateEdit()

        self.date_edit.setCalendarPopup(
            True
        )

        self.date_edit.setDisplayFormat(
            "yyyy-MM-dd"
        )

        self.date_edit.setDate(
            QDate.currentDate()
        )

        controls.addWidget(
            self.date_edit
        )

        controls.addSpacing(25)

        self.source_label = QLabel()

        self.source_label.setObjectName(
            "SecondaryText"
        )

        controls.addWidget(
            self.source_label,
            1,
        )

        add_button = QPushButton(
            "＋ 临时追加目录"
        )

        add_button.setObjectName(
            "SecondaryButton"
        )

        add_button.clicked.connect(
            self.add_directory
        )

        controls.addWidget(
            add_button
        )

        self.extra_scan_button = QPushButton(
            "扫描临时追加目录"
        )

        self.extra_scan_button.setEnabled(
            False
        )

        self.extra_scan_button.setStyleSheet(
            """
            QPushButton {
                background:#16A765;
                color:white;
                border:none;
                border-radius:6px;
                padding:9px 18px;
                font-weight:600;
            }

            QPushButton:hover {
                background:#13955A;
            }

            QPushButton:disabled {
                background:#C8D0D9;
            }
            """
        )

        self.extra_scan_button.clicked.connect(
            self.scan_extra
        )

        controls.addWidget(
            self.extra_scan_button
        )

        self.scan_button = QPushButton(
            "扫描当天询价明细"
        )

        self.scan_button.setStyleSheet(
            """
            QPushButton {
                background:#16A765;
                color:white;
                border:none;
                border-radius:6px;
                padding:9px 18px;
                font-weight:600;
            }

            QPushButton:hover {
                background:#13955A;
            }
            """
        )

        self.scan_button.clicked.connect(
            self.scan
        )

        controls.addWidget(
            self.scan_button
        )

        setup.addLayout(controls)

        self.extra_list = QListWidget()

        self.extra_list.setMaximumHeight(
            80
        )

        self.extra_list.setVisible(
            False
        )

        setup.addWidget(
            self.extra_list
        )

        root.addWidget(
            setup_card
        )

        # ======================================
        # 2. 扫描结果概览
        # ======================================

        summary_card = QFrame()

        summary_card.setObjectName(
            "Card"
        )

        summary_layout = QVBoxLayout(
            summary_card
        )

        summary_layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )

        summary_title = QLabel(
            "2  扫描与校验结果"
        )

        summary_title.setObjectName(
            "CardTitle"
        )

        summary_layout.addWidget(
            summary_title
        )

        stats = QHBoxLayout()

        (
            self.file_value,
            self.source_value,
            self.carton_value,
            self.weight_value,
            self.warehouse_value,
        ) = (
            QLabel("—"),
            QLabel("—"),
            QLabel("—"),
            QLabel("—"),
            QLabel("—"),
        )

        stat_items = [
            (
                "询价文件",
                self.file_value,
            ),
            (
                "SourceID",
                self.source_value,
            ),
            (
                "总箱数",
                self.carton_value,
            ),
            (
                "总重量 KG",
                self.weight_value,
            ),
            (
                "仓库数",
                self.warehouse_value,
            ),
        ]

        for name, value_label in (
            stat_items
        ):

            box = QVBoxLayout()

            name_label = QLabel(name)

            name_label.setObjectName(
                "SecondaryText"
            )

            value_label.setStyleSheet(
                """
                font-size:20px;
                font-weight:700;
                """
            )

            box.addWidget(name_label)

            box.addWidget(
                value_label
            )

            stats.addLayout(box)

        summary_layout.addLayout(
            stats
        )

        self.status_label = QLabel(
            "等待扫描"
        )

        self.status_label.setStyleSheet(
            """
            padding:8px;
            background:#F5F7FB;
            border-radius:5px;
            """
        )

        summary_layout.addWidget(
            self.status_label
        )

        root.addWidget(
            summary_card
        )

        # ======================================
        # 3. 汇总预览
        # ======================================

        preview_card = QFrame()

        preview_card.setObjectName(
            "Card"
        )

        preview_layout = QVBoxLayout(
            preview_card
        )

        preview_layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )

        preview_title = QLabel(
            "3  仓库汇总预览"
        )

        preview_title.setObjectName(
            "CardTitle"
        )

        preview_layout.addWidget(
            preview_title
        )

        self.table = QTableWidget()

        self.table.setColumnCount(3)

        self.table.setHorizontalHeaderLabels(
            [
                "WarehouseCode",
                "总重量 KG",
                "总箱数",
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

        self.table.setMinimumHeight(
            250
        )

        preview_layout.addWidget(
            self.table
        )

        root.addWidget(
            preview_card,
            1,
        )

        # ======================================
        # 底部操作
        # ======================================

        actions = QHBoxLayout()

        actions.addStretch()

        self.generate_button = QPushButton(
            "生成询价汇总表"
        )

        self.generate_button.setEnabled(
            False
        )

        self.generate_button.setStyleSheet(
            """
            QPushButton {
                background:#16A765;
                color:white;
                border:none;
                border-radius:6px;
                padding:10px 24px;
                font-weight:600;
            }

            QPushButton:disabled {
                background:#C8D0D9;
            }
            """
        )

        self.generate_button.clicked.connect(
            self.generate
        )

        actions.addWidget(
            self.generate_button
        )

        root.addLayout(
            actions
        )

        self.refresh_source_label()

    # ==========================================
    # 当前日期
    # ==========================================

    def current_date_id(self):

        return (
            self.date_edit
            .date()
            .toString("yyyyMMdd")
        )

    def default_directory(self):

        return (
            INQUIRY_SOURCE_ROOT
            / self.current_date_id()
        )

    # ==========================================
    # 路径
    # ==========================================

    def refresh_source_label(self):

        self.source_label.setText(
            "默认扫描："
            f"{self.default_directory()}"
        )

    def add_directory(self):

        start_dir = (
            str(INQUIRY_SOURCE_ROOT)
            if INQUIRY_SOURCE_ROOT.exists()
            else ""
        )

        directory = QFileDialog.getExistingDirectory(
            self,
            "临时追加询价目录",
            start_dir,
        )

        if not directory:
            return

        path = Path(directory)

        if path not in self.extra_directories:

            self.extra_directories.append(
                path
            )

            self.extra_list.addItem(
                str(path)
            )

        self.extra_list.setVisible(
            bool(self.extra_directories)
        )
        self.extra_scan_button.setEnabled(
            bool(self.extra_directories)
        )

    # ==========================================
    # 扫描
    # ==========================================

    def scan(self):

        self._run_scan(
            resolve_inquiry_scan_directories(
                default_directory=self.default_directory(),
                extra_directories=self.extra_directories,
                extra_only=False,
            ),
            empty_message="当天询价目录不存在，请先确认日期。",
        )

    def scan_extra(self):

        if not self.extra_directories:

            QMessageBox.information(
                self,
                "扫描临时追加目录",
                "请先点击「＋ 临时追加目录」，选择要统计的询价路径。",
            )
            return

        self._run_scan(
            resolve_inquiry_scan_directories(
                default_directory=self.default_directory(),
                extra_directories=self.extra_directories,
                extra_only=True,
            ),
            empty_message="临时追加的目录里没有找到询价明细。",
        )

    def _run_scan(
        self,
        directories: list[Path],
        empty_message: str,
    ):

        if not directories:

            QMessageBox.information(
                self,
                "扫描",
                empty_message,
            )
            return

        date_id = (
            self.current_date_id()
        )

        self.generate_button.setEnabled(
            False
        )

        self.scan_result = None

        self.table.setRowCount(0)

        self.status_label.setText(
            "正在扫描和校验..."
        )

        QApplication.setOverrideCursor(
            Qt.WaitCursor
        )

        try:

            result = scan_inquiry_batch(
                date_id=date_id,
                directories=directories,
            )

        finally:

            QApplication.restoreOverrideCursor()

        self.scan_result = result

        self.show_scan_result(
            result
        )

    def show_scan_result(
        self,
        result: ScanResult,
    ):

        self.file_value.setText(
            str(result.file_count)
        )

        self.source_value.setText(
            str(result.source_count)
        )

        self.carton_value.setText(
            str(result.carton_count)
        )

        self.weight_value.setText(
            f"{result.total_weight:.2f}"
        )

        self.warehouse_value.setText(
            str(result.warehouse_count)
        )

        self.table.setRowCount(
            len(result.summaries)
        )

        for row_index, summary in enumerate(
            result.summaries
        ):

            self.table.setItem(
                row_index,
                0,
                QTableWidgetItem(
                    summary.warehouse_code
                ),
            )

            self.table.setItem(
                row_index,
                1,
                QTableWidgetItem(
                    f"{summary.weight_kg:.2f}"
                ),
            )

            self.table.setItem(
                row_index,
                2,
                QTableWidgetItem(
                    str(
                        summary.carton_count
                    )
                ),
            )

        if result.passed:

            self.status_label.setText(
                "PASS｜数据校验通过，"
                "可以生成询价汇总表"
            )

            self.status_label.setStyleSheet(
                """
                padding:8px;
                color:#087A45;
                background:#E8F7EF;
                border-radius:5px;
                """
            )

            self.generate_button.setEnabled(
                True
            )

        else:

            error_preview = "\n".join(
                result.errors[:8]
            )

            if len(result.errors) > 8:

                error_preview += (
                    f"\n……还有 "
                    f"{len(result.errors)-8}"
                    " 条异常"
                )

            self.status_label.setText(
                "FAILED｜发现关键异常，"
                "禁止生成\n\n"
                + error_preview
            )

            self.status_label.setStyleSheet(
                """
                padding:8px;
                color:#B42318;
                background:#FFF0F0;
                border-radius:5px;
                """
            )

    # ==========================================
    # 生成
    # ==========================================

    def generate(self):

        if not self.scan_result:

            return

        if not self.scan_result.passed:

            return

        answer = QMessageBox.question(
            self,
            "确认生成",
            (
                "确认根据当前扫描结果生成询价表？\n\n"
                f"仓库："
                f"{self.scan_result.warehouse_count}\n"
                f"总箱数："
                f"{self.scan_result.carton_count}\n"
                f"总重量："
                f"{self.scan_result.total_weight:.2f} KG"
            ),
            QMessageBox.Yes
            | QMessageBox.No,
            QMessageBox.Yes,
        )

        if answer != QMessageBox.Yes:
            return

        try:

            output_path = (
                generate_inquiry_summary(
                    date_id=(
                        self.current_date_id()
                    ),
                    summaries=(
                        self.scan_result.summaries
                    ),
                )
            )

        except Exception as exc:

            QMessageBox.critical(
                self,
                "生成失败",
                str(exc),
            )

            return

        QMessageBox.information(
            self,
            "生成完成",
            "询价汇总表已生成：\n\n"
            f"{output_path}",
        )

        # Windows Explorer 中选中文件
        try:

            subprocess.Popen(
                [
                    "explorer",
                    "/select,",
                    str(output_path),
                ]
            )

        except Exception:
            pass