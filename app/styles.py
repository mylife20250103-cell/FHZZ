"""浅色桌面主题，仅包含呈现规则。"""

from pathlib import Path

PRIMARY_BUTTON_STYLE = """
QPushButton {
    background:#0071E3; color:#FFFFFF; border:1px solid #0071E3;
    border-radius:7px; padding:6px 16px; min-height:20px; font-weight:600;
}
QPushButton:hover { background:#0064C8; border-color:#0064C8; }
QPushButton:pressed { background:#005BB8; border-color:#005BB8; }
QPushButton:focus { border-color:#004F9F; }
QPushButton:disabled { background:#E5E5EA; color:#8E8E93; border-color:#E5E5EA; }
"""

SECONDARY_BUTTON_STYLE = """
QPushButton {
    background:#FFFFFF; color:#3A3A3C; border:1px solid #D4D4D8;
    border-radius:7px; padding:6px 12px; min-height:20px; font-weight:500;
}
QPushButton:hover { background:#F5F5F7; border-color:#B8B8BE; }
QPushButton:pressed { background:#EDEDF0; }
QPushButton:focus { border-color:#0071E3; }
QPushButton:disabled { background:#F5F5F7; color:#97979E; border-color:#E5E5EA; }
"""

CAUTION_BUTTON_STYLE = """
QPushButton {
    background:#FFF5E6; color:#855313; border:1px solid #E8CDA3;
    border-radius:7px; padding:6px 16px; min-height:20px; font-weight:600;
}
QPushButton:hover { background:#FFECCB; border-color:#D9B67E; }
QPushButton:pressed { background:#F7DDB3; }
QPushButton:focus { border-color:#A36D20; }
QPushButton:disabled { background:#F5F5F7; color:#97979E; border-color:#E5E5EA; }
"""

STATUS_IDLE_STYLE = "padding:9px 12px; color:#6E6E73; background:#F5F5F7; border:1px solid #E8E8ED; border-radius:7px;"
STATUS_INFO_STYLE = "padding:9px 12px; color:#285DAC; background:#EEF4FF; border:1px solid #DAE6FA; border-radius:7px;"
STATUS_SUCCESS_STYLE = "padding:9px 12px; color:#247449; background:#EDF6EF; border:1px solid #D6E8DB; border-radius:7px;"
STATUS_ERROR_STYLE = "padding:9px 12px; color:#B33B35; background:#FFF1F0; border:1px solid #F2D9D6; border-radius:7px;"
STATUS_WARNING_STYLE = "padding:9px 12px; color:#855313; background:#FFF6E6; border:1px solid #F1E2C6; border-radius:7px;"

STEP_ACTIVE_STYLE = "color:#0065CC; background:#E9F2FF; border-radius:6px; padding:5px 7px; font-size:12px; font-weight:600;"
STEP_DONE_STYLE = "color:#247449; background:#F0F7F2; border-radius:6px; padding:5px 7px; font-size:12px; font-weight:500;"
STEP_PENDING_STYLE = "color:#86868B; padding:5px 7px; font-size:12px;"
METRIC_STYLE = "font-size:19px; font-weight:600; color:#1D1D1F;"
PATH_STYLE = "font-size:12px; color:#515154; background:#F7F7F9; border:1px solid #E5E5EA; border-radius:7px; padding:9px 12px;"


def style_table(table) -> None:
    """统一表格的视觉密度，保留编辑、选择、排序和列宽设置。"""
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.verticalHeader().setDefaultSectionSize(34)


APP_STYLE = """
/* 中性工作区与统一文字层级 */
QMainWindow, QDialog { background:#F7F7F9; }
QWidget { font-family:"Segoe UI","Microsoft YaHei UI"; font-size:13px; color:#1D1D1F; }
QStackedWidget#PageStack { background:#F7F7F9; }
QLabel { background:transparent; }
QLabel#PageTitle { font-size:25px; font-weight:600; color:#1D1D1F; }
QLabel#PageSubtitle { font-size:12px; color:#6E6E73; }
QLabel#CardTitle { font-size:14px; font-weight:600; color:#1D1D1F; }
QLabel#SecondaryText { font-size:12px; color:#6E6E73; }

/* 保持原有导航入口及顺序 */
QFrame#Sidebar { background:#F0F0F2; border-right:1px solid #DDDDE2; }
QLabel#AppTitle { font-size:17px; font-weight:600; color:#1D1D1F; }
QLabel#AppVersion { font-size:11px; color:#86868B; }
QLabel#SidebarSection { font-size:11px; font-weight:600; color:#77777D; padding:5px 10px; }
QLabel#SidebarInfo { font-size:11px; color:#77777D; padding:0 10px; }
QPushButton#NavButton {
    background:transparent; border:1px solid transparent; border-radius:7px;
    text-align:left; color:#515154; padding:8px 10px; font-size:13px; min-height:20px; font-weight:400;
}
QPushButton#NavButton:hover { background:#E7E7EB; color:#1D1D1F; }
QPushButton#NavButton:checked { background:#DDE9F8; color:#005DBB; font-weight:600; }
QPushButton#NavButton:focus { border-color:#97BFEA; }

/* 白色内容面板 */
QFrame#Card, QFrame#ModuleCard { background:#FFFFFF; border:1px solid #E4E4E8; border-radius:12px; }
QFrame#ModuleCard:hover { border-color:#CDD6E2; }

/* 默认及辅助按钮 */
QPushButton {
    background:#FFFFFF; color:#3A3A3C; border:1px solid #D4D4D8;
    border-radius:7px; padding:6px 12px; min-height:20px; font-weight:500;
}
QPushButton:hover { background:#F5F5F7; border-color:#B8B8BE; }
QPushButton:pressed { background:#EDEDF0; }
QPushButton:focus { border-color:#0071E3; }
QPushButton:disabled { background:#F5F5F7; color:#97979E; border-color:#E5E5EA; }
QPushButton#SecondaryButton { background:#FFFFFF; color:#3A3A3C; border-color:#D4D4D8; }
QPushButton#SecondaryButton:hover { background:#F5F5F7; border-color:#B8B8BE; }
QPushButton#SecondaryButton:pressed { background:#EDEDF0; }
QPushButton#SecondaryButton:disabled { background:#F5F5F7; color:#97979E; border-color:#E5E5EA; }

/* 输入与菜单保留 Qt 原有交互 */
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox {
    background:#FFFFFF; color:#1D1D1F; border:1px solid #D4D4D8; border-radius:6px;
    padding:5px 8px; min-height:18px; selection-background-color:#0071E3; selection-color:#FFFFFF;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color:#0071E3; }
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background:#F5F5F7; color:#97979E; border-color:#E5E5EA;
}
QComboBox { padding-right:25px; }
QComboBox::drop-down { border:none; width:22px; }
QComboBox::down-arrow, QDateEdit::down-arrow { image:url("__CHEVRON__"); width:12px; height:12px; }
QDateEdit { min-width:110px; max-width:140px; padding-right:23px; }
QDateEdit::drop-down { border:none; width:22px; }
QComboBox QAbstractItemView {
    background:#FFFFFF; border:1px solid #D4D4D8; padding:4px;
    selection-background-color:#E9F2FF; selection-color:#005DBB;
}
QCheckBox, QRadioButton { spacing:6px; color:#515154; }
QCheckBox:disabled, QRadioButton:disabled { color:#97979E; }
QTextEdit, QPlainTextEdit, QListWidget {
    background:#FAFAFC; border:1px solid #E1E1E6; border-radius:7px; padding:6px;
    selection-background-color:#E9F2FF; selection-color:#1D1D1F;
}
QListWidget::item { padding:4px 6px; border-radius:4px; }
QListWidget::item:selected { background:#E9F2FF; color:#005DBB; }
QMenu { background:#FFFFFF; border:1px solid #D4D4D8; padding:5px; }
QMenu::item { padding:6px 22px 6px 12px; border-radius:4px; }
QMenu::item:selected { background:#E9F2FF; color:#005DBB; }
QToolTip { background:#FFFFFF; color:#1D1D1F; border:1px solid #D4D4D8; padding:5px 8px; }

/* 数据表格 */
QTableWidget {
    background:#FFFFFF; alternate-background-color:#FAFAFC; border:none;
    gridline-color:#EFEFF2; selection-background-color:#E9F2FF; selection-color:#1D1D1F;
}
QTableWidget::item { padding:4px 7px; border:none; }
QTableWidget::item:selected { background:#E9F2FF; color:#1D1D1F; }
QTableWidget::item:focus { border:1px solid #B4CEF0; }
QHeaderView::section {
    background:#F7F7F9; color:#6E6E73; border:none; border-bottom:1px solid #DDDDE2;
    padding:8px 7px; font-size:12px; font-weight:500;
}
QTableCornerButton::section { background:#F7F7F9; border:none; }
QCalendarWidget QWidget#qt_calendar_navigationbar { background:#F5F5F7; }
QCalendarWidget QToolButton { color:#1D1D1F; background:transparent; border:none; padding:4px; }
QCalendarWidget QAbstractItemView { background:#FFFFFF; selection-background-color:#0071E3; selection-color:#FFFFFF; }

/* 滚动区域 */
QScrollArea { background:#F7F7F9; border:none; }
QScrollArea > QWidget > QWidget { background:#F7F7F9; }
QScrollBar:vertical { background:transparent; border:none; width:8px; margin:2px 0; }
QScrollBar:horizontal { background:transparent; border:none; height:8px; margin:0 2px; }
QScrollBar::handle:vertical { background:#C6C6CC; border-radius:4px; min-height:30px; }
QScrollBar::handle:horizontal { background:#C6C6CC; border-radius:4px; min-width:30px; }
QScrollBar::handle:hover { background:#A8A8B0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
""".replace("__CHEVRON__", (Path(__file__).parent / "assets" / "ui" / "chevron-down.svg").as_posix())
