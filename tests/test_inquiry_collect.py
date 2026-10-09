from __future__ import annotations

from pathlib import Path

from app.invoice_config import is_excel_junk_file
from app.services.inquiry_service import (
    collect_inquiry_files,
    country_name_for_store,
    inquiry_directories_for_range,
    inquiry_summary_output_name,
    resolve_inquiry_scan_directories,
    scan_inquiry_batch,
)


def test_is_excel_junk_file():

    assert is_excel_junk_file(Path("~$abc_询价明细.xlsx"))
    assert is_excel_junk_file(
        Path(".~tmp_20260819_美10_CD_ECD6D9A4_询价明细.xlsx")
    )
    assert is_excel_junk_file(Path(".__inquiry_tmp_20260819.xlsx"))
    assert not is_excel_junk_file(
        Path("20260819_美10_CD_ECD6D9A4_询价明细.xlsx")
    )


def test_collect_inquiry_skips_excel_tmp(tmp_path):

    real = tmp_path / "20260819_美10_CD_ECD6D9A4_询价明细.xlsx"
    junk = tmp_path / ".~tmp_20260819_美10_CD_ECD6D9A4_询价明细.xlsx"
    lock = tmp_path / "~$20260819_美10_CD_ECD6D9A4_询价明细.xlsx"
    real.write_bytes(b"real")
    junk.write_bytes(b"tmp")
    lock.write_bytes(b"lock")

    files = collect_inquiry_files([tmp_path])

    assert files == [real]
    assert not junk.exists()
    assert not lock.exists()


def test_resolve_inquiry_scan_directories_separates_daily_and_extra():

    default = Path(r"D:\inquiry\20260820")
    extra = [
        Path(r"D:\manual\GYR2"),
        Path(r"D:\manual\LAX9"),
    ]

    assert resolve_inquiry_scan_directories(
        default_directory=default,
        extra_directories=extra,
        extra_only=False,
    ) == [default]

    assert resolve_inquiry_scan_directories(
        default_directory=default,
        extra_directories=extra,
        extra_only=True,
    ) == extra

    range_dirs = [
        Path(r"D:\inquiry\20260910"),
        Path(r"D:\inquiry\20260911"),
    ]
    assert resolve_inquiry_scan_directories(
        default_directories=range_dirs,
        extra_directories=extra,
        extra_only=False,
    ) == range_dirs


def test_inquiry_directories_for_range(tmp_path):
    folders = inquiry_directories_for_range(
        "20260911",
        "20260910",
        source_root=tmp_path,
    )
    assert folders == [
        tmp_path / "20260910",
        tmp_path / "20260911",
    ]


def _write_inquiry_file(
    path,
    *,
    date_id: str,
    source_id: str,
    carton: str,
    fba: str,
    warehouse: str = "GYR2",
    store_code: str = "美3",
):
    from openpyxl import Workbook

    workbook = Workbook()
    ws = workbook.active
    ws.title = "询价明细"
    headers = [
        "SchemaVersion",
        "DateID",
        "StoreCode",
        "PlanID",
        "SourceID",
        "WarehouseCode",
        "FBABatch",
        "CartonNumber",
        "WeightKG",
    ]
    ws.append(headers)
    ws.append(
        [
            "1.0",
            date_id,
            store_code,
            "CD",
            source_id,
            warehouse,
            fba,
            carton,
            10.5,
        ]
    )
    workbook.save(path)
    workbook.close()


def test_scan_inquiry_accepts_date_range(tmp_path):
    day1 = tmp_path / "20260910"
    day2 = tmp_path / "20260911"
    day1.mkdir()
    day2.mkdir()
    _write_inquiry_file(
        day1 / "20260910_美3_CD_AAAAAAAA_询价明细.xlsx",
        date_id="20260910",
        source_id="AAAAAAAA",
        carton="FBA10U000001",
        fba="FBA10",
    )
    _write_inquiry_file(
        day2 / "20260911_美3_CD_BBBBBBBB_询价明细.xlsx",
        date_id="20260911",
        source_id="BBBBBBBB",
        carton="FBA11U000001",
        fba="FBA11",
    )

    result = scan_inquiry_batch(
        date_id="20260911",
        directories=[day1, day2],
        allowed_date_ids=["20260910", "20260911"],
        country_name="美国",
    )

    assert result.passed is True
    assert result.file_count == 2
    assert result.source_count == 2
    assert result.carton_count == 2


def test_scan_inquiry_rejects_date_outside_range(tmp_path):
    folder = tmp_path / "20260911"
    folder.mkdir()
    _write_inquiry_file(
        folder / "20260911_美3_CD_BBBBBBBB_询价明细.xlsx",
        date_id="20260911",
        source_id="BBBBBBBB",
        carton="FBA11U000001",
        fba="FBA11",
    )

    result = scan_inquiry_batch(
        date_id="20260910",
        directories=[folder],
        allowed_date_ids=["20260910"],
        country_name="美国",
    )

    assert result.passed is False
    assert any("不在扫描范围" in item for item in result.errors)


def test_country_name_for_store():
    assert country_name_for_store("美10") == "美国"
    assert country_name_for_store("加13") == "加拿大"
    assert country_name_for_store("英1") == "英国"
    assert country_name_for_store("德2") == "德国"
    assert country_name_for_store("欧1") is None


def test_inquiry_summary_output_name_includes_country():
    assert inquiry_summary_output_name(
        "20261009",
        "美国",
        15,
    ) == "20261009_美国_询价汇总_15箱.xlsx"


def test_scan_keeps_selected_country_and_skips_others(tmp_path):
    folder = tmp_path / "20261009"
    folder.mkdir()
    _write_inquiry_file(
        folder / "20261009_美2_LBX_BE31A7EC_询价明细.xlsx",
        date_id="20261009",
        source_id="BE31A7EC",
        carton="FBAUSU000001",
        fba="FBAUS",
        warehouse="LBX",
        store_code="美2",
    )
    _write_inquiry_file(
        folder / "20261009_加13_LBX_1002EA25_询价明细.xlsx",
        date_id="20261009",
        source_id="1002EA25",
        carton="FBACAU000001",
        fba="FBACA",
        warehouse="LBX",
        store_code="加13",
    )

    united_states = scan_inquiry_batch(
        date_id="20261009",
        directories=[folder],
        allowed_date_ids=["20261009"],
        country_name="美国",
    )
    canada = scan_inquiry_batch(
        date_id="20261009",
        directories=[folder],
        allowed_date_ids=["20261009"],
        country_name="加拿大",
    )

    assert united_states.passed is True
    assert united_states.file_count == 1
    assert united_states.carton_count == 1
    assert united_states.store_codes == ["美2"]
    assert united_states.skipped_other_country_count == 1
    assert united_states.summaries[0].warehouse_code == "LBX"
    assert united_states.summaries[0].carton_count == 1

    assert canada.passed is True
    assert canada.carton_count == 1
    assert canada.store_codes == ["加13"]
    assert canada.skipped_other_country_count == 1


def test_scan_reports_when_selected_country_has_no_files(tmp_path):
    folder = tmp_path / "20261009"
    folder.mkdir()
    _write_inquiry_file(
        folder / "20261009_加2_L8X_34BC76F3_询价明细.xlsx",
        date_id="20261009",
        source_id="34BC76F3",
        carton="FBA11U000001",
        fba="FBA11",
        warehouse="L8X",
        store_code="加2",
    )

    result = scan_inquiry_batch(
        date_id="20261009",
        directories=[folder],
        allowed_date_ids=["20261009"],
        country_name="美国",
    )

    assert result.passed is False
    assert result.file_count == 0
    assert result.skipped_other_country_count == 1
    assert any("没有询价明细" in item for item in result.errors)


def test_scan_reports_filename_store_mismatch(tmp_path):
    folder = tmp_path / "20261009"
    folder.mkdir()
    _write_inquiry_file(
        folder / "20261009_美3_CD_AAAAAAAA_询价明细.xlsx",
        date_id="20261009",
        source_id="AAAAAAAA",
        carton="FBA10U000001",
        fba="FBA10",
        store_code="美10",
    )

    result = scan_inquiry_batch(
        date_id="20261009",
        directories=[folder],
        allowed_date_ids=["20261009"],
        country_name="美国",
    )

    assert result.passed is False
    assert any("不一致" in item for item in result.errors)


def test_scan_lists_unknown_store_prefix_without_merging(tmp_path):
    folder = tmp_path / "20261009"
    folder.mkdir()
    _write_inquiry_file(
        folder / "20261009_美1_CWJ_5D185A11_询价明细.xlsx",
        date_id="20261009",
        source_id="5D185A11",
        carton="FBA10U000001",
        fba="FBA10",
        warehouse="CWJ",
        store_code="美1",
    )
    _write_inquiry_file(
        folder / "20261009_欧1_CD_CCCCCCCC_询价明细.xlsx",
        date_id="20261009",
        source_id="CCCCCCCC",
        carton="FBA99U000001",
        fba="FBA99",
        warehouse="CD",
        store_code="欧1",
    )

    result = scan_inquiry_batch(
        date_id="20261009",
        directories=[folder],
        allowed_date_ids=["20261009"],
        country_name="美国",
    )

    assert result.passed is True
    assert result.carton_count == 1
    assert result.summaries[0].warehouse_code == "CWJ"
    assert result.unknown_store_files
    assert "欧1" in result.unknown_store_files[0]
