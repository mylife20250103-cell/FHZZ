import pytest

from tests.test_channel_revision import scan_fixture


@pytest.fixture
def panel(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from app.pages.channel_batch_panel import ChannelBatchPanel
    app=QApplication.instance() or QApplication([])
    widget=ChannelBatchPanel(state_path=tmp_path/'state.json',catalog_path=tmp_path/'catalog.json')
    yield widget
    widget.set_busy(False)
    widget.close();widget.deleteLater();app.processEvents()


def preview(panel,tmp_path):
    scan=scan_fixture(tmp_path)
    panel.category_combo.setCurrentText('美国合德')
    panel.tax_combo.setCurrentIndex(panel.tax_combo.findData('包税'))
    panel.delivery_combo.setCurrentIndex(panel.delivery_combo.findData('卡派'))
    panel.accept_scan(scan)
    return scan


def test_global_condition_change_invalidates_preview(panel,tmp_path):
    preview(panel,tmp_path)
    assert panel.table.rowCount()==1 and panel.edits[0].new_value=='美速达快提卡派'
    panel.tax_combo.setCurrentIndex(panel.tax_combo.findData('递延'))
    assert panel.scan is None and panel.table.rowCount()==0
    assert not panel.confirm_button.isEnabled()


def test_carrier_choice_fills_editable_default_service_cell(panel):
    panel.carrier_combo.setCurrentIndex(panel.carrier_combo.findData('MC'))
    assert panel.cell_edit.text()=='B2'
    panel.cell_edit.setText('D2')
    assert panel.cell_edit.text()=='D2'
    panel.carrier_combo.setCurrentIndex(panel.carrier_combo.findData('HP'))
    assert panel.cell_edit.text()=='B1'
    panel.carrier_combo.setCurrentIndex(panel.carrier_combo.findData('KYD'))
    assert panel.cell_edit.text()=='B4'


def test_per_row_condition_rematches_and_requires_new_confirmation(panel,tmp_path):
    preview(panel,tmp_path)
    panel.select_ready()
    assert panel.edits[0].selected and panel.confirm_button.isEnabled()
    combo=panel.table.cellWidget(0,8)
    combo.setCurrentIndex(combo.findData('快递派'))
    assert not panel.edits[0].selected
    assert panel.edits[0].new_value==''
    assert not panel.confirm_button.isEnabled()


def test_manual_value_is_kept_after_render_and_recorded_as_manual(panel,tmp_path):
    preview(panel,tmp_path)
    panel.table.item(0,10).setText('人工核实的服务填写别名')
    assert panel.edits[0].new_value=='人工核实的服务填写别名'
    assert panel.edits[0].manual
    panel.render_rows()
    assert panel.table.item(0,10).text()=='人工核实的服务填写别名'


def test_manual_service_selection_can_resolve_unconfigured_row(panel,tmp_path):
    scan=preview(panel,tmp_path)
    panel.change_condition(0,delivery='快递派')
    panel.select_manual_service(0,scan.catalog.find('MC.A','EXP'))
    assert panel.edits[0].manual and panel.edits[0].service_code=='EXP'
    assert panel.edits[0].new_value=='美速达快提快递派'
    assert not panel.edits[0].selected


def test_busy_controls_and_merge_handoff_are_safe(panel,tmp_path):
    panel.set_busy(True)
    assert not panel.source_edit.isEnabled() and not panel.sync_button.isEnabled()
    folder=tmp_path/'new_batch';folder.mkdir()
    before=panel.source_edit.text()
    panel.receive_merge({'directory':str(folder),'carrier':'MC','country':'US'})
    assert panel.source_edit.text()==before
    panel.set_busy(False)
    assert panel.source_edit.text()==str(folder)
    assert panel.carrier_combo.currentData()=='MC'
    assert panel.state_path.exists()


def test_bad_preferences_do_not_prevent_page_opening(panel):
    for raw in ('[]','null','{broken','{"tax": []}'):
        panel.state_path.write_text(raw,encoding='utf-8')
        panel.load_state()
    assert panel.scan is None


def test_merge_arriving_during_scan_cannot_leave_old_preview_under_new_path(panel,tmp_path):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QElapsedTimer
    from PySide6.QtWidgets import QApplication
    scan=scan_fixture(tmp_path)
    folder=tmp_path/'new_batch';folder.mkdir()
    panel.run_job(lambda: scan,panel.accept_scan,'scan')
    panel.receive_merge({'directory':str(folder),'carrier':'MC','country':'US'})
    timer=QElapsedTimer();timer.start()
    while panel.worker is not None and timer.elapsed()<4000:
        QApplication.processEvents();QTest.qWait(10)
    assert panel.worker is None
    assert panel.source_edit.text()==str(folder)
    assert panel.scan is None and not panel.confirm_button.isEnabled()


def test_existing_manual_mode_stays_available_with_channel_tab(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from app.pages.batch_edit_page import BatchEditPage
    app=QApplication.instance() or QApplication([])
    page=BatchEditPage(channel_state_path=tmp_path/'state.json',channel_catalog_path=tmp_path/'cache.json')
    assert page.tabs.tabText(0)=='按渠道规则'
    assert page.tabs.tabText(1)=='手工修改'
    assert page.cell_edit.placeholderText()=='快越达合并结果默认 B4'
    folder=tmp_path/'merged';folder.mkdir()
    page.receive_merge({'directory':str(folder),'carrier':'KYD','country':'US'})
    assert page.channel_panel.source_edit.text()==str(folder)
    page.close();page.deleteLater();app.processEvents()
