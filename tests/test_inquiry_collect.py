from __future__ import annotations

from pathlib import Path

from app.invoice_config import is_excel_junk_file
from app.services.inquiry_service import (
    collect_inquiry_files,
    inquiry_directories_for_range,
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
            "美3",
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
    )

    assert result.passed is False
    assert any("不在扫描范围" in item for item in result.errors)
