from __future__ import annotations

from pathlib import Path

from app.invoice_config import is_excel_junk_file
from app.services.inquiry_service import collect_inquiry_files


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
