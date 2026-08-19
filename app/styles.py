APP_STYLE = """
/* =========================
   全局
   ========================= */

QMainWindow {
    background: #F5F7FB;
}

QWidget {
    font-family: "Microsoft YaHei UI";
    color: #172033;
}


/* =========================
   左侧导航
   ========================= */

QFrame#Sidebar {
    background: #FFFFFF;
    border-right: 1px solid #E7EBF2;
}

QLabel#AppTitle {
    font-size: 18px;
    font-weight: 700;
    color: #172033;
}

QLabel#AppVersion {
    color: #8992A3;
    font-size: 11px;
}

QPushButton#NavButton {
    border: none;
    background: transparent;
    text-align: left;
    padding: 11px 14px;
    border-radius: 7px;
    font-size: 14px;
    color: #39435A;
}

QPushButton#NavButton:hover {
    background: #F0F5FF;
    color: #1677FF;
}

QPushButton#NavButton:checked {
    background: #1677FF;
    color: white;
    font-weight: 600;
}


/* =========================
   页面标题
   ========================= */

QLabel#PageTitle {
    font-size: 27px;
    font-weight: 700;
    color: #172033;
}

QLabel#PageSubtitle {
    color: #747F93;
    font-size: 13px;
}


/* =========================
   卡片
   ========================= */

QFrame#Card,
QFrame#ModuleCard {
    background: #FFFFFF;
    border: 1px solid #E5EAF1;
    border-radius: 10px;
}

QLabel#CardTitle {
    font-size: 15px;
    font-weight: 700;
    color: #172033;
}

QLabel#SecondaryText {
    color: #7B8496;
    font-size: 12px;
}


/* =========================
   按钮
   ========================= */

QPushButton#SecondaryButton {
    background: #FFFFFF;
    color: #1677FF;
    border: 1px solid #B8D1FF;
    padding: 8px 14px;
    border-radius: 6px;
    font-size: 13px;
}

QPushButton#SecondaryButton:hover {
    background: #F2F7FF;
}


/* =========================
   表格
   ========================= */

QTableWidget {
    background: white;
    border: none;
    gridline-color: #EEF1F5;
    selection-background-color: #EAF2FF;
    selection-color: #172033;
}

QHeaderView::section {
    background: #F8FAFD;
    color: #697386;
    border: none;
    border-bottom: 1px solid #E9EDF3;
    padding: 8px;
    font-size: 12px;
    font-weight: 600;
}


/* =========================
   ScrollArea
   ========================= */

QScrollArea {
    background: #F5F7FB;
    border: none;
}

QScrollArea > QWidget > QWidget {
    background: #F5F7FB;
}


/* =========================
   滚动条
   ========================= */

QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 8px;
}

QScrollBar::handle:vertical {
    background: #CCD3DE;
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #AEB8C7;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
"""