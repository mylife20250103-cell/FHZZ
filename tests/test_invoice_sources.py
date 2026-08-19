from __future__ import annotations

from pathlib import Path

from app.services.invoice_scan_service import (
    load_registered_sources,
    load_source_entries,
    scan_original_invoices,
)


def test_load_registered_sources_true(tmp_path, monkeypatch):

    ini_path = tmp_path / "invoice_sources.ini"

    ini_path.write_text(
        "\n".join(
            [
                "[Source.Mayn_KYD]",
                "Enabled=TRUE",
                r"Path=D:\invoices\kyd",
                "Owner=Mayn",
                "StoreCode=美10",
                "CarrierCode=KYD",
                "",
                "[Source.Mayn_MC]",
                "Enabled=TRUE",
                r"Path=D:\invoices\mc",
                "Owner=Mayn",
                "StoreCode=美10",
                "CarrierCode=MC",
                "",
                "[Source.Disabled]",
                "Enabled=FALSE",
                r"Path=D:\invoices\off",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.services.invoice_scan_service.INVOICE_SOURCES_INI",
        ini_path,
    )

    sources = load_registered_sources()

    assert sources == [
        Path(r"D:\invoices\kyd"),
        Path(r"D:\invoices\mc"),
    ]

    entries = load_source_entries()

    assert [entry.source_key for entry in entries] == [
        "Mayn_KYD",
        "Mayn_MC",
    ]
    assert entries[0].carrier_code == "KYD"
    assert entries[1].carrier_code == "MC"


def test_scan_does_not_depend_on_inquiry(tmp_path, monkeypatch):

    monkeypatch.setattr(
        "app.services.invoice_scan_service.load_known_carriers",
        lambda: {"KYD", "MC"},
    )

    result = scan_original_invoices(
        "20260819",
        [tmp_path],
    )

    joined = "\n".join(result.errors)

    assert "询价" not in joined
    assert "没有扫描到任何发票 .xlsx" in joined
    assert result.passed is False
