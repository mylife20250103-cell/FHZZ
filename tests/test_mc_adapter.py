from __future__ import annotations

from pathlib import Path

from app.services.invoice_adapters.mc_adapter import McAdapter


def test_mc_template_anchors_confirmed():

    adapter = McAdapter()
    cfg = adapter.template_config()

    assert cfg.sheet_name == "迈创发票"
    assert cfg.header_row == 17
    assert cfg.data_start_row == 18
    assert cfg.channel_cell == "B2"
    assert cfg.warehouse_cell == "B3"
    assert cfg.carton_count_cell == "B16"

    columns = {
        spec.field_code: spec.column
        for spec in cfg.product_fields
    }
    assert columns["ProductEN"] == 7
    assert columns["ProductCN"] == 8
    assert columns["MaterialEN"] == 11
    assert columns["MaterialCN"] == 11


def test_mc_validate_source_rejects_wrong_carrier(tmp_path):

    adapter = McAdapter()
    fake = tmp_path / "demo.xlsx"
    fake.write_bytes(b"not-excel")

    errors = adapter.validate_source(
        fake,
        {"CarrierCode": "KYD", "TemplateVersion": "1.0"},
    )

    assert any("CarrierCode 不是 MC" in item for item in errors)
