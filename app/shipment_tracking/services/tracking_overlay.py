from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.json_io import read_json, write_json
from app.shipment_tracking.paths import TRACKING_STORE_PATH


@dataclass(frozen=True)
class TrackingRecord:
    tracking_number: str
    source: str


def load_tracking_overlay(path=None) -> dict[str, TrackingRecord]:
    store = Path(path) if path is not None else TRACKING_STORE_PATH
    if not store.exists():
        return {}
    try:
        payload = read_json(store)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[str, TrackingRecord] = {}
    for raw_fba, item in payload.items():
        fba_id = str(raw_fba or "").strip().upper()
        if not fba_id or not isinstance(item, dict):
            continue
        number = str(item.get("tracking_number") or "").strip()
        if not number:
            continue
        source = str(item.get("source") or "manual").strip() or "manual"
        result[fba_id] = TrackingRecord(number, source)
    return result


def tracking_for(
    fba_id: str,
    lookup: dict[str, TrackingRecord],
) -> str:
    key = (fba_id or "").strip().upper()
    record = lookup.get(key)
    return record.tracking_number if record else ""


def upsert_tracking(
    fba_id: str,
    tracking_number: str,
    *,
    source: str = "manual",
    path=None,
) -> TrackingRecord:
    store = Path(path) if path is not None else TRACKING_STORE_PATH
    fba_key = (fba_id or "").strip().upper()
    number = (tracking_number or "").strip()
    if not fba_key:
        raise ValueError("缺少 FBA")
    if not number:
        raise ValueError("缺少运单号")
    payload: dict = {}
    if store.exists():
        try:
            loaded = read_json(store)
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {}
    record = TrackingRecord(number, source.strip() or "manual")
    payload[fba_key] = {
        "tracking_number": record.tracking_number,
        "source": record.source,
    }
    write_json(store, payload)
    return record
