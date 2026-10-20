"""随程序绘制的线性导航图标，不依赖系统符号字体或外部图片。"""

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


_PATHS = {
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
    "home": '<path d="M3 10 12 3l9 7M5 9v12h5v-7h4v7h5V9"/>',
    "inquiry": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h3m-3 4h3m4-4h1m-1 4h1"/>',
    "invoice": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M8 13h8m-8 4h6"/>',
    "tracking": '<path d="m12 3 9 5v9l-9 5-9-5V8zm-9 5 9 5 9-5m-9 5v9M7.5 5.5l9 5V15"/>',
    "watchlist": '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>',
    "batch_edit": '<path d="M12 5H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7M9 15l1-4L18 3a2.1 2.1 0 0 1 3 3l-8 8zM16 5l3 3"/>',
    "sensitive": '<path d="m12 3 8 3v6c0 5-4 8-8 10-4-2-8-5-8-10V6zM12 8v5m0 4h.01"/>',
    "maintain": '<path d="M4 6h6m4 0h6M4 12h10m4 0h2M4 18h2m4 0h10"/><circle cx="12" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="8" cy="18" r="2"/>',
}


def navigation_icon(name: str) -> QIcon:
    icon = QIcon()
    for state, color in ((QIcon.Off, "#68686E"), (QIcon.On, "#005DBB")):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
            f'<g fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
            f'{_PATHS[name]}</g></svg>'
        )
        pixmap = QPixmap(40, 40)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(2)
        icon.addPixmap(pixmap, QIcon.Normal, state)
    return icon
