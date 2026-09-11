from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.json_io import read_json, write_json
from app.shipment_tracking.paths import TRACKING_STORE_PATH


@dataclass(frozen=True)
class TrackingRecord:
    tracking_number: str
    source: str
    latest_event: str = ""


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
        latest = str(item.get("latest_event") or "").strip()
        result[fba_id] = TrackingRecord(number, source, latest)
    return result


def tracking_for(
    fba_id: str,
    lookup: dict[str, TrackingRecord],
) -> str:
    key = (fba_id or "").strip().upper()
    record = lookup.get(key)
    return record.tracking_number if record else ""


def latest_event_for(
    fba_id: str,
    lookup: dict[str, TrackingRecord],
) -> str:
    key = (fba_id or "").strip().upper()
    record = lookup.get(key)
    return record.latest_event if record else ""


def upsert_tracking(
    fba_id: str,
    tracking_number: str,
    *,
    source: str = "manual",
    latest_event: str | None = None,
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
    previous = payload.get(fba_key) if isinstance(payload.get(fba_key), dict) else {}
    event = (
        str(previous.get("latest_event") or "").strip()
        if latest_event is None
        else str(latest_event).strip()
    )
    record = TrackingRecord(number, source.strip() or "manual", event)
    payload[fba_key] = {
        "tracking_number": record.tracking_number,
        "source": record.source,
        "latest_event": record.latest_event,
    }
    write_json(store, payload)
    return record
