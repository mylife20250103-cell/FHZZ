from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.json_io import read_json
from app.services.batch_service import STATUS_INVALIDATED


@dataclass(frozen=True)
class ForwarderBinding:
    carrier_code: str
    state: str  # confirmed | missing | conflict


def load_confirmed_forwarders(
    batch_root,
    store_code: str | None = None,
) -> dict[str, ForwarderBinding]:
    """
    从发票批次 snapshot 读取 FBA → CarrierCode。
    只在扫描通过后的记录里才算确认货代，不用文件名。
    """

    root = Path(batch_root)
    wanted = (store_code or "").strip()
    codes: dict[str, set[str]] = {}
    if not root.exists():
        return {}

    for snapshot_path in root.glob("*/*/snapshot.json"):
        if _batch_invalidated(snapshot_path.parent):
            continue
        try:
            snapshot = read_json(snapshot_path)
        except Exception:
            continue
        for record in snapshot.get("Files") or []:
            if not isinstance(record, dict):
                continue
            store = str(record.get("store_code") or "").strip()
            if wanted and store != wanted:
                continue
            fba_id = str(record.get("fba_batch") or "").strip().upper()
            carrier = str(record.get("carrier_code") or "").strip().upper()
            if not fba_id or not carrier:
                continue
            codes.setdefault(fba_id, set()).add(carrier)

    result: dict[str, ForwarderBinding] = {}
    for fba_id, found in codes.items():
        ordered = tuple(sorted(found))
        if len(ordered) == 1:
            result[fba_id] = ForwarderBinding(ordered[0], "confirmed")
        else:
            result[fba_id] = ForwarderBinding("/".join(ordered), "conflict")
    return result


def binding_for(
    fba_id: str,
    lookup: dict[str, ForwarderBinding],
) -> ForwarderBinding:
    key = (fba_id or "").strip().upper()
    return lookup.get(key, ForwarderBinding("", "missing"))


def _batch_invalidated(batch_dir: Path) -> bool:
    status_path = batch_dir / "status.json"
    if not status_path.exists():
        return False
    try:
        payload = read_json(status_path)
    except Exception:
        return False
    return str(payload.get("Status") or "") == STATUS_INVALIDATED
