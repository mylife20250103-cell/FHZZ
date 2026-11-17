import pytest

from tests.test_customs_service import scanned


@pytest.fixture
def page(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from app.pages.customs_page import CustomsPage
    app = QApplication.instance() or QApplication([])
    widget = CustomsPage(state_path=tmp_path / "state.json")
    yield widget
    widget.set_busy(False)
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_changing_input_invalidates_preview_and_disables_confirmation(page, tmp_path):
    scan = scanned(tmp_path)
    page.accept_scan(scan)
    assert page.table.rowCount() == 1
    assert page.confirm_button.isEnabled()
    page.threshold.setValue(96)
    assert page.scan is None
    assert not page.confirm_button.isEnabled()
    assert page.table.rowCount() == 0


def test_conflict_requires_candidate_and_all_four_new_fields_change_together(page, tmp_path):
    from tests.test_customs_rules import row
    scan = scanned(tmp_path, [row(), row("美2", after="头饰")])
    page.accept_scan(scan)
    assert page.selections() == {}
    combo = page.table.cellWidget(0, 4)
    combo.setCurrentIndex(2)
    assert page.selections() == {scan.rows[0].key: 1}
    assert page.table.item(0, 6).text() == "头饰"
    assert page.table.item(0, 12).text() == "0096151900"


def test_busy_prevents_input_changes_and_confirm(page):
    page.set_busy(True)
    assert not page.rule_edit.isEnabled()
    assert not page.source_edit.isEnabled()
    assert not page.carrier_combo.isEnabled()
    assert not page.region_combo.isEnabled()
    assert not page.confirm_button.isEnabled()


def test_successful_merge_path_handoff_updates_local_defaults(page, tmp_path):
    folder = tmp_path / "successful_batch"
    folder.mkdir()
    page.receive_merge({"directory": str(folder), "carrier": "MC", "country": "CA"})
    assert page.source_edit.text() == str(folder)
    assert page.carrier_combo.currentData() == "MC"
    assert page.region_combo.currentData() == "CA"
    assert page.state_path.exists()


def test_rule_directory_with_multiple_workbooks_requires_selection(page, tmp_path):
    (tmp_path / "one.xlsx").write_bytes(b"sample")
    (tmp_path / "two.xlsx").write_bytes(b"sample")
    page.rule_edit.setText(str(tmp_path))
    with pytest.raises(ValueError):
        page.rule_path()


@pytest.mark.parametrize('raw', ['[]', 'null', '{"threshold": []}', '{broken'])
def test_invalid_local_preferences_do_not_prevent_page_opening(page, tmp_path, raw):
    page.state_path.write_text(raw, encoding='utf-8')
    page.load_state()
    assert not page.confirm_button.isEnabled()


def test_navigation_and_merge_handoff_are_wired_without_starting_old_services(page, tmp_path, monkeypatch):
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QWidget
    from app import main_window as module
    from app.pages.customs_page import CustomsPage
    class StubPage(QWidget):
        navigate_requested = Signal(str)
        content_merge_succeeded = Signal(object)
    for name in ('HomePage', 'InquiryPage', 'InvoicePage', 'TrackingPage', 'WatchlistPage', 'BatchEditPage', 'SensitivePage', 'MaintainPage'):
        monkeypatch.setattr(module, name, StubPage)
    monkeypatch.setattr(module, 'CustomsPage', lambda: CustomsPage(state_path=tmp_path / 'main_state.json'))
    window = module.MainWindow()
    keys = list(window.nav_buttons)
    assert keys[keys.index('invoice') + 1] == 'customs'
    folder = tmp_path / 'merged'
    folder.mkdir()
    window.pages['invoice'].content_merge_succeeded.emit({'directory': str(folder), 'carrier': 'KYD', 'country': 'US'})
    window.go_to('customs')
    assert window.stack.currentWidget() is window.pages['customs']
    assert window.pages['customs'].source_edit.text() == str(folder)
    assert window.pages['customs'].carrier_combo.currentData() == 'KYD'
    window.close()
    window.deleteLater()


def test_changing_batch_directory_resets_previous_manual_carrier_to_auto(page, tmp_path):
    page.carrier_combo.setCurrentIndex(page.carrier_combo.findData('MC'))
    page.source_edit.setText(str(tmp_path / 'different_batch'))
    assert page.carrier_combo.currentData() == 'AUTO'
