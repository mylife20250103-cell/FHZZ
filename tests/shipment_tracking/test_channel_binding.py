from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from app.json_io import write_json
from app.shipment_tracking.services.channel_binding import (
    channel_for,
    load_confirmed_channels,
)


def _write_batch(
    root: Path,
    batch_id: str,
    date_id: str,
    files: list[dict],
    status: str = "CONTENT_MERGED",
) -> Path:
    directory = root / date_id / batch_id
    directory.mkdir(parents=True, exist_ok=True)
    write_json(
        directory / "snapshot.json",
        {"BatchID": batch_id, "DateID": date_id, "Files": files},
    )
    write_json(directory / "status.json", {"Status": status, "BatchID": batch_id})
    return directory


def _write_merge_xlsx(path: Path, cell: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "模板"
    ws[cell] = value
    wb.save(path)
    wb.close()


def test_channel_from_kyd_merge_b4(tmp_path):
    batches = tmp_path / "batches"
    merges = tmp_path / "merges"
    _write_batch(
        batches,
        "20260821-B0001",
        "20260821",
        [
            {
                "store_code": "美3",
                "fba_batch": "FBA19MHDCGMP",
                "carrier_code": "KYD",
                "warehouse_code": "AVP1",
            }
        ],
    )
    _write_merge_xlsx(
        merges / "20260821" / "20260821-B0001" / "KYD_AVP1_2箱.xlsx",
        "B4",
        "K18美西稳速达-卡派-包税",
    )
    lookup = load_confirmed_channels(batches, merges, store_code="美3")
    bound = channel_for("FBA19MHDCGMP", lookup)
    assert bound.state == "confirmed"
    assert bound.channel_text == "K18美西稳速达-卡派-包税"
    assert channel_for("FBA-MISSING", lookup).state == "missing"


def test_channel_conflict_and_invalidated(tmp_path):
    batches = tmp_path / "batches"
    merges = tmp_path / "merges"
    _write_batch(
        batches,
        "20260821-B0001",
        "20260821",
        [
            {
                "store_code": "美3",
                "fba_batch": "FBA-A",
                "carrier_code": "MC",
                "warehouse_code": "BJC1",
            }
        ],
        status="INVALIDATED",
    )
    _write_merge_xlsx(
        merges / "20260821" / "20260821-B0001" / "MC_BJC1_1箱.xlsx",
        "B2",
        "旧渠道",
    )
    _write_batch(
        batches,
        "20260821-B0002",
        "20260821",
        [
            {
                "store_code": "美3",
                "fba_batch": "FBA-A",
                "carrier_code": "MC",
                "warehouse_code": "BJC1",
            }
        ],
    )
    _write_merge_xlsx(
        merges / "20260821" / "20260821-B0002" / "MC_BJC1_1箱.xlsx",
        "B2",
        "新渠道A",
    )
    _write_merge_xlsx(
        merges / "20260822" / "20260822-B0001" / "MC_BJC1_3箱.xlsx",
        "B2",
        "新渠道B",
    )
    _write_batch(
        batches,
        "20260822-B0001",
        "20260822",
        [
            {
                "store_code": "美3",
                "fba_batch": "FBA-A",
                "carrier_code": "MC",
                "warehouse_code": "BJC1",
            }
        ],
    )
    bound = channel_for(
        "FBA-A",
        load_confirmed_channels(batches, merges, store_code="美3"),
    )
    assert bound.state == "conflict"
    assert "新渠道A" in bound.channel_text
    assert "新渠道B" in bound.channel_text
    assert "旧渠道" not in bound.channel_text
