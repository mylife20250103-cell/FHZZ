from __future__ import annotations

from pathlib import Path

from app.json_io import write_json
from app.shipment_tracking.services.forwarder_binding import (
    binding_for,
    load_confirmed_forwarders,
)


def _write_batch(
    root: Path,
    batch_id: str,
    date_id: str,
    files: list[dict],
    status: str = "FIRST_SCAN_PASSED",
) -> None:
    directory = root / date_id / batch_id
    directory.mkdir(parents=True, exist_ok=True)
    write_json(
        directory / "snapshot.json",
        {"BatchID": batch_id, "DateID": date_id, "Files": files},
    )
    write_json(
        directory / "status.json",
        {"Status": status, "BatchID": batch_id},
    )


def test_confirmed_forwarder_from_snapshot(tmp_path):
    _write_batch(
        tmp_path,
        "20260611-B0001",
        "20260611",
        [
            {
                "store_code": "美3",
                "fba_batch": "FBA-A",
                "carrier_code": "KYD",
            }
        ],
    )
    lookup = load_confirmed_forwarders(tmp_path, store_code="美3")
    bound = binding_for("FBA-A", lookup)
    assert bound.state == "confirmed"
    assert bound.carrier_code == "KYD"
    assert binding_for("FBA-MISSING", lookup).state == "missing"


def test_conflict_when_two_carriers(tmp_path):
    _write_batch(
        tmp_path,
        "20260611-B0001",
        "20260611",
        [
            {
                "store_code": "美3",
                "fba_batch": "FBA-A",
                "carrier_code": "KYD",
            },
            {
                "store_code": "美3",
                "fba_batch": "FBA-A",
                "carrier_code": "MC",
            },
        ],
    )
    bound = binding_for("FBA-A", load_confirmed_forwarders(tmp_path, "美3"))
    assert bound.state == "conflict"
    assert "KYD" in bound.carrier_code
    assert "MC" in bound.carrier_code


def test_skips_invalidated_and_other_store(tmp_path):
    _write_batch(
        tmp_path,
        "20260611-B0001",
        "20260611",
        [
            {
                "store_code": "美3",
                "fba_batch": "FBA-A",
                "carrier_code": "KYD",
            }
        ],
        status="INVALIDATED",
    )
    _write_batch(
        tmp_path,
        "20260611-B0002",
        "20260611",
        [
            {
                "store_code": "美10",
                "fba_batch": "FBA-A",
                "carrier_code": "MC",
            }
        ],
    )
    lookup = load_confirmed_forwarders(tmp_path, store_code="美3")
    assert binding_for("FBA-A", lookup).state == "missing"
