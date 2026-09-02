from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.json_io import read_json
from app.services.batch_modify_service import read_cell_value
from app.services.batch_service import STATUS_INVALIDATED

MERGE_OUTPUT_NAME = re.compile(
    r"^([A-Za-z0-9]+)_([A-Za-z0-9]+)_(\d+)箱\.(xlsx|xls)$",
    re.IGNORECASE,
)
CHANNEL_CELL = {
    "KYD": ("模板", "B4"),
    "MC": ("模板", "B2"),
}


@dataclass(frozen=True)
class ChannelBinding:
    channel_text: str
    state: str  # confirmed | missing | conflict


def load_confirmed_channels(
    batch_root,
    merge_root,
    store_code: str | None = None,
) -> dict[str, ChannelBinding]:
    """
    发货规划 FBA → 合并结果渠道文本。
    KYD 读模板!B4，迈创读模板!B2。跳过已作废批次。不改合并文件。
    """

    pairs = _fba_pairs(batch_root, store_code)
    if not pairs:
        return {}
    needed = {key for key in pairs.values()}
    texts = _channel_texts(batch_root, merge_root, needed)
    result: dict[str, ChannelBinding] = {}
    for fba_id, key in pairs.items():
        found = texts.get(key, set())
        ordered = tuple(sorted(item for item in found if item))
        if len(ordered) == 1:
            result[fba_id] = ChannelBinding(ordered[0], "confirmed")
        elif len(ordered) > 1:
            result[fba_id] = ChannelBinding(" / ".join(ordered), "conflict")
        else:
            result[fba_id] = ChannelBinding("", "missing")
    return result


def channel_for(
    fba_id: str,
    lookup: dict[str, ChannelBinding],
) -> ChannelBinding:
    key = (fba_id or "").strip().upper()
    return lookup.get(key, ChannelBinding("", "missing"))


def _fba_pairs(batch_root, store_code: str | None) -> dict[str, tuple[str, str]]:
    root = Path(batch_root)
    wanted = (store_code or "").strip()
    found: dict[str, set[tuple[str, str]]] = {}
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
            warehouse = str(record.get("warehouse_code") or "").strip().upper()
            if not fba_id or not carrier or not warehouse:
                continue
            found.setdefault(fba_id, set()).add((carrier, warehouse))

    pairs: dict[str, tuple[str, str]] = {}
    for fba_id, keys in found.items():
        if len(keys) == 1:
            pairs[fba_id] = next(iter(keys))
    return pairs


def _channel_texts(
    batch_root,
    merge_root,
    needed: set[tuple[str, str]],
) -> dict[tuple[str, str], set[str]]:
    texts: dict[tuple[str, str], set[str]] = {}
    merge_base = Path(merge_root)
    batch_base = Path(batch_root)
    if not merge_base.exists():
        return texts

    for path in sorted(merge_base.glob("*/*/*箱.xls")) + sorted(
        merge_base.glob("*/*/*箱.xlsx")
    ):
        if path.name.startswith("~$") or path.name.startswith(".__"):
            continue
        parsed = MERGE_OUTPUT_NAME.fullmatch(path.name)
        if not parsed:
            continue
        carrier = parsed.group(1).upper()
        warehouse = parsed.group(2).upper()
        key = (carrier, warehouse)
        if key not in needed:
            continue
        if _batch_invalidated(batch_base / path.parent.parent.name / path.parent.name):
            continue
        cell = CHANNEL_CELL.get(carrier)
        if cell is None:
            continue
        try:
            value = str(read_cell_value(path, cell[0], cell[1]) or "").strip()
        except Exception:
            continue
        if value:
            texts.setdefault(key, set()).add(value)
    return texts


def _batch_invalidated(batch_dir: Path) -> bool:
    status_path = batch_dir / "status.json"
    if not status_path.exists():
        return False
    try:
        payload = read_json(status_path)
    except Exception:
        return False
    return str(payload.get("Status") or "") == STATUS_INVALIDATED
