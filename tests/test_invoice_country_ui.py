from pathlib import Path

import pytest


@pytest.fixture
def invoice_page(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from app.pages import invoice_page as module
    from app.services.invoice_scan_service import RegisteredSource
    app = QApplication.instance() or QApplication([])
    entries = [
        RegisteredSource("KYD", Path("D:/KYD/未合并"), "owner", "美10", "KYD"),
        RegisteredSource("MC_US", Path("D:/MC/未合并/美国发票"), "owner", "美10", "MC", "US"),
        RegisteredSource("MC_CA", Path("D:/MC/未合并/加拿大发票"), "owner", "美10", "MC", "CA"),
    ]
    monkeypatch.setattr(module, "load_source_entries", lambda: entries)
    monkeypatch.setattr(module, "portals_grouped_by_carrier", lambda: {})
    monkeypatch.setattr(module, "enforce_single_active", lambda date, **scope: None)
    page = module.InvoicePage()
    yield page
    page.close()
    page.deleteLater()
    app.processEvents()


def test_country_selection_routes_legacy_root_and_clears_previous_batch(invoice_page):
    page = invoice_page
    page.source_combo.setCurrentIndex(page.source_combo.findData("KYD"))
    assert "美国发票" in page.path_list.item(0).text()
    page.current_batch_id = "old-us-batch"
    page.country_combo.setCurrentIndex(page.country_combo.findData("CA"))
    assert page.selected_source().carrier_code == "KYD"
    assert "加拿大发票" in page.path_list.item(0).text()
    assert page.current_batch_id is None


def test_country_selection_matches_explicit_source_by_carrier(invoice_page):
    page = invoice_page
    page.source_combo.setCurrentIndex(page.source_combo.findData("MC_US"))
    page.country_combo.setCurrentIndex(page.country_combo.findData("CA"))
    assert page.selected_source().source_key == "MC_CA"
    assert page.source_combo.findData("MC_US") == -1
    assert "加拿大发票" in page.path_list.item(0).text()


def test_batch_restore_uses_selected_carrier_and_country(invoice_page, monkeypatch):
    from app.pages import invoice_page as module
    from app.services.batch_service import BatchRecord
    from tests.test_batch_service import make_record
    from dataclasses import asdict

    page = invoice_page
    page.country_combo.setCurrentIndex(page.country_combo.findData("CA"))
    page.source_combo.setCurrentIndex(page.source_combo.findData("MC_CA"))
    snapshot = {"BatchID": "20261020-B0002", "Files": [asdict(make_record(
        carrier_code="MC", country_code="CA", warehouse_code="YOW3",
    ))], "CountryCode": "CA", "CarrierCode": "MC"}
    record = BatchRecord("20261020-B0002", "20261020", Path("D:/test"),
                         "FIRST_SCAN_PASSED", "hash", snapshot, {})
    def find_batch(date, *, carrier_code, country_code):
        assert (carrier_code, country_code) == ("MC", "CA")
        return record
    monkeypatch.setattr(module, "enforce_single_active", find_batch)
    page.restore_active_batch()
    assert page.current_batch_id == "20261020-B0002"
    assert page.selected_source().source_key == "MC_CA"


def test_country_and_source_are_disabled_during_work(invoice_page):
    invoice_page._set_busy(True)
    assert not invoice_page.country_combo.isEnabled()
    assert not invoice_page.source_combo.isEnabled()


def test_country_controls_fit_main_window_content_width(invoice_page):
    invoice_page.source_combo.setCurrentIndex(invoice_page.source_combo.findData("KYD"))
    assert invoice_page.minimumSizeHint().width() <= 1100
