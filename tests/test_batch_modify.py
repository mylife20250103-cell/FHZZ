from __future__ import annotations

from app.services.batch_modify_service import (
    ModifyPreviewRow,
    normalize_cell_address,
    parse_cell,
    precheck_rows,
)


def test_normalize_cell_address():

    assert normalize_cell_address("B2单元格") == "B2"
    assert normalize_cell_address(" b4 ") == "B4"
    assert normalize_cell_address("单元格B2") == "B2"
    assert parse_cell("B2单元格") == ("B", 2)


def test_precheck_requires_cell_and_existing_file(tmp_path):

    missing = ModifyPreviewRow(
        path=str(tmp_path / "gone.xlsx"),
        file_name="gone.xlsx",
        carrier_code="KYD",
        sheet_name="快越达发票",
        cell="B4",
        current_value="",
        new_value="K18",
    )

    no_cell = ModifyPreviewRow(
        path=str(tmp_path / "a.xlsx"),
        file_name="a.xlsx",
        carrier_code="",
        sheet_name="Sheet1",
        cell="",
        current_value="",
        new_value="K18",
    )
    (tmp_path / "a.xlsx").write_bytes(b"not-really-xlsx")

    errors = precheck_rows([missing, no_cell])

    assert any("不存在" in item for item in errors)
    assert any("未指定目标单元格" in item for item in errors)
