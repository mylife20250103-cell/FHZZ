from __future__ import annotations

from datetime import date
from pathlib import Path

from app.shipment_tracking.indexing.shipping_file_indexer import (
    index_shipping_files,
    list_store_codes,
)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"xlsm")


def test_index_single_batch_under_month_date(tmp_path):
    root = tmp_path / "装箱明细"
    file_path = root / "美3" / "2026.8" / "8.21美3" / "0811-美3-快越达.xlsm"
    _touch(file_path)
    _touch(root / "美3" / "2026.8" / "8.21美3" / "标签" / "ignore.xlsm")
    _touch(root / "美3" / "2026.8" / "8.21美3" / "~$0811-美3-快越达.xlsm")

    files = index_shipping_files(root)
    assert len(files) == 1
    item = files[0]
    assert item.store_code == "美3"
    assert item.year == 2026
    assert item.month == 8
    assert item.folder_day == 21
    assert item.ship_date == date(2026, 8, 21)
    assert item.filename_month == 8
    assert item.filename_day == 11
    assert item.batch_no == 1
    assert item.candidate_forwarder == "快越达"
    assert item.path == file_path.resolve()


def test_index_numeric_batch_folders(tmp_path):
    root = tmp_path / "装箱明细"
    first = root / "美3" / "2026.6" / "6.11美3" / "1" / "0611-美3-迈创合德.xlsm"
    second = root / "美3" / "2026.6" / "6.11美3" / "2" / "0611-美3-迈创合德.xlsm"
    _touch(first)
    _touch(second)

    files = index_shipping_files(root)
    assert [item.batch_no for item in files] == [1, 2]
    assert files[0].ship_date == date(2026, 6, 11)
    assert files[0].candidate_forwarder == "迈创合德"
    assert files[1].batch_no == 2


def test_index_padded_month_folder(tmp_path):
    root = tmp_path / "装箱明细"
    _touch(root / "美10" / "2026.08" / "8.19美10" / "0819-美10-快越达.xlsm")
    files = index_shipping_files(root)
    assert files[0].month == 8
    assert files[0].store_code == "美10"


def test_index_date_folder_without_year(tmp_path):
    root = tmp_path / "装箱明细"
    _touch(root / "EM" / "2.6EM" / "0206-EM-某某货代.xlsm")
    files = index_shipping_files(root)
    assert len(files) == 1
    assert files[0].store_code == "EM"
    assert files[0].year is None
    assert files[0].month == 2
    assert files[0].folder_day == 6
    assert files[0].ship_date is None
    assert files[0].filename_month == 2
    assert files[0].filename_day == 6
    assert files[0].candidate_forwarder == "某某货代"
    assert files[0].batch_no == 1


def test_index_can_filter_one_store(tmp_path):
    root = tmp_path / "装箱明细"
    _touch(root / "美3" / "2026.8" / "8.21美3" / "0811-美3-快越达.xlsm")
    _touch(root / "美10" / "2026.08" / "8.19美10" / "0819-美10-快越达.xlsm")

    assert set(list_store_codes(root)) == {"美3", "美10"}
    only_three = index_shipping_files(root, store_code="美3")
    assert len(only_three) == 1
    assert only_three[0].store_code == "美3"
