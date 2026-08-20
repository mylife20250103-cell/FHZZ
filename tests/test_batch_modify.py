from __future__ import annotations

from app.services.batch_modify_service import (
    ModifyPreviewRow,
    apply_modifications,
    normalize_cell_address,
    parse_cell,
    precheck_rows,
    preview_files,
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


def test_folder_prefers_merge_output_over_source_xlsx(tmp_path):

    (tmp_path / "IND9_FBA88U000001_快越达发票.xlsx").write_bytes(b"src")
    merged = tmp_path / "KYD_IND9_1箱.xls"
    merged.write_bytes(b"out")
    nested = tmp_path / "KYD" / "IND9"
    nested.mkdir(parents=True)
    (nested / "IND9_FBA88U000001_快越达发票.xlsx").write_bytes(b"src2")

    from app.services.batch_modify_service import _collect_modify_files

    files = _collect_modify_files([tmp_path])
    assert [item.name for item in files] == ["KYD_IND9_1箱.xls"]


def test_looks_like_merge_output():

    from pathlib import Path
    from app.services.batch_modify_service import (
        looks_like_merge_output,
        looks_like_source_invoice,
    )

    assert looks_like_merge_output(Path("KYD_IND9_1箱.xls"))
    assert looks_like_merge_output(Path("MC_GYR2_3箱.xlsx"))
    assert looks_like_source_invoice(Path("IND9_FBA88U000001_快越达发票.xlsx"))
    assert not looks_like_source_invoice(Path("KYD_IND9_1箱.xls"))


def test_preview_and_apply_kyd_xls_skips_excel(tmp_path, monkeypatch):

    from app.invoice_config import KYD_TEMPLATE_PATH
    from tests.test_kyd_xls_fill import _filled_kyd_xls

    if not KYD_TEMPLATE_PATH.exists():
        return

    dest = tmp_path / "KYD_GYR2_1箱.xls"
    _filled_kyd_xls(dest)

    def boom(*_args, **_kwargs):
        raise AssertionError("快越达 .xls 不能走 Excel COM")

    monkeypatch.setattr("app.excel_com.excel_application", boom)

    rows = preview_files([dest], new_value="K18美西顺丰速运-卡派")
    assert len(rows) == 1
    assert rows[0].carrier_code == "KYD"
    assert rows[0].sheet_name == "模板"
    assert rows[0].cell == "B4"

    result = apply_modifications(rows)
    assert result.passed, result.errors
    assert result.success_count == 1

    import olefile
    import xlrd

    ole = olefile.OleFileIO(str(dest))
    streams = ["/".join(item) for item in ole.listdir()]
    ole.close()
    assert not any("CompObj" in name for name in streams)

    wb = xlrd.open_workbook(str(dest))
    assert str(wb.sheet_by_name("模板").cell_value(3, 1)).strip() == (
        "K18美西顺丰速运-卡派"
    )
