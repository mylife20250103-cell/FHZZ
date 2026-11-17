"""查看官方服务目录，以及明确选择人工核实过的服务。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout


class ChannelServiceDialog(QDialog):
    def __init__(self, catalog, carrier='', parent=None, *, selection=True):
        super().__init__(parent)
        self.setWindowTitle('官方服务目录' if not selection else '人工选择服务，请核对仓库、税费和派送适用性')
        self.resize(820, 600)
        self.catalog, self.carrier, self.selection = catalog, carrier, selection
        root = QVBoxLayout(self)
        note = QLabel('目录提供官方代码和名称，不代表所有服务适用于当前仓库。人工选择仅影响本次，不会自动新增规则。')
        note.setWordWrap(True)
        root.addWidget(note)
        self.accounts = QComboBox()
        self.accounts.addItem('全部账号', '')
        for account in catalog.accounts:
            if not carrier or account.carrier_code == carrier:
                self.accounts.addItem(f'{account.label}｜{account.provider_id}｜上次成功 {account.updated_at or "无"}'
                                      + ('｜本次同步失败' if account.error else ''), account.provider_id)
        root.addWidget(self.accounts)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索服务名称或代码')
        root.addWidget(self.search)
        self.services = QListWidget()
        root.addWidget(self.services)
        self.count = QLabel()
        root.addWidget(self.count)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel if selection else QDialogButtonBox.Close)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.ok = buttons.button(QDialogButtonBox.Ok)
        if self.ok:
            self.ok.setText('选择此服务')
            self.ok.setEnabled(False)
            self.services.currentItemChanged.connect(lambda current, _: self.ok.setEnabled(current is not None))
            self.services.itemDoubleClicked.connect(lambda _: self.accept())
        self.accounts.currentIndexChanged.connect(self.render)
        self.search.textChanged.connect(self.render)
        self.render()

    def render(self, *_):
        self.services.clear()
        provider = self.accounts.currentData()
        query = self.search.text().strip().casefold()
        for service in self.catalog.services:
            if self.carrier and service.carrier_code != self.carrier or provider and service.provider_id != provider:
                continue
            if query and query not in (service.name + ' ' + service.code).casefold():
                continue
            item = QListWidgetItem(f'{service.name}    [{service.code}]    {service.provider_id}')
            item.setData(Qt.UserRole, service)
            self.services.addItem(item)
        self.count.setText(f'{self.services.count()} 项服务（按账号区分）')

    def selected_service(self):
        item = self.services.currentItem()
        return item.data(Qt.UserRole) if item else None
