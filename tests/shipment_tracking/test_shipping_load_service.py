from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook

from app.shipment_tracking.indexing.shipping_file_indexer import IndexedShippingFile
from app.shipment_tracking.services.shipping_load_service import (
    load_shipping_snapshot,
    load_store_snapshots,
)


def _write_plan(path: Path, fba_id: str, sku: str, qty: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "美国3号-发货规划"
    ws["M1"] = "仓库"
    ws["M2"] = "FBA批号"
    ws["N1"] = "IND9"
    ws["N2"] = fba_id
    ws["N13"] = 1
    ws["A13"] = "*产品英文品名"
    ws["F13"] = "SKU"
    ws["F14"] = sku
    ws["N14"] = qty
    wb.save(path)
    wb.close()


def _indexed(path: Path) -> IndexedShippingFile:
    return IndexedShippingFile(
        path=path,
        store_code="美3",
        year=2026,
        month=6,
        folder_day=11,
        ship_date=date(2026, 6, 11),
        filename_month=6,
        filename_day=11,
        batch_no=1,
        candidate_forwarder="迈创合德",
    )


def test_load_snapshot_is_batch_fba_sku_qty(tmp_path):
    path = tmp_path / "0611-美3-迈创合德.xlsx"
    _write_plan(path, "FBA-A", "SKU-A", 40)
    snap = load_shipping_snapshot(_indexed(path))

    assert snap.source.store_code == "美3"
    assert snap.source.batch_no == 1
    assert snap.source.ship_date == date(2026, 6, 11)
    assert snap.plan.fbas[0].fba_id == "FBA-A"
    assert snap.plan.fbas[0].cartons[0].items[0].sku == "SKU-A"
    assert snap.aggregated[0].items[0].quantity == 40


def test_load_store_skips_unreadable_file(tmp_path):
    root = tmp_path / "装箱明细"
    good = root / "美3" / "2026.6" / "6.11美3" / "0611-美3-迈创合德.xlsx"
    bad = root / "美3" / "2026.6" / "6.11美3" / "0611-美3-坏文件.xlsx"
    _write_plan(good, "FBA-A", "SKU-A", 8)
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"not-excel")

    result = load_store_snapshots(root, "美3")
    assert len(result.snapshots) == 1
    assert result.snapshots[0].aggregated[0].items[0].quantity == 8
    assert any("坏文件" in item for item in result.errors)
