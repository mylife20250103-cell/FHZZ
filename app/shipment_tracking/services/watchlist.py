from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from app.json_io import read_json, write_json
from app.shipment_tracking.paths import WATCHLIST_PATH

DEFAULT_LOOKBACK_DAYS = 60
DELIVERED_MARKERS = ("已签收", "已送达", "delivered")
_STORE_TAIL = re.compile(r"^(.*?)(\d+)$")


@dataclass(frozen=True)
class WatchItem:
    store_code: str
    name_contains: str
    sku_contains: str = ""

    def label(self) -> str:
        sku = self.sku_contains.strip()
        if sku:
            return f"{self.store_code}｜{self.name_contains}｜SKU {sku}"
        return f"{self.store_code}｜{self.name_contains}"


def lookback_range(
    days: int = DEFAULT_LOOKBACK_DAYS,
    today: date | None = None,
) -> tuple[date, date]:
    end = today or date.today()
    span = max(int(days), 1)
    start = end - timedelta(days=span - 1)
    return start, end


def _norm(value: str) -> str:
    return str(value or "").strip()


def item_key(item: WatchItem) -> tuple[str, str, str]:
    return (
        _norm(item.store_code),
        _norm(item.name_contains).casefold(),
        _norm(item.sku_contains).casefold(),
    )


def matches_watch_item(
    store_code: str,
    sku: str,
    product_name: str,
    item: WatchItem,
) -> bool:
    if _norm(store_code) != _norm(item.store_code):
        return False
    name_q = _norm(item.name_contains).casefold()
    sku_q = _norm(item.sku_contains).casefold()
    if not name_q:
        return False
    if name_q not in _norm(product_name).casefold():
        return False
    if sku_q and sku_q not in _norm(sku).casefold():
        return False
    return True


def matches_any_watch_item(
    store_code: str,
    sku: str,
    product_name: str,
    items: list[WatchItem],
) -> bool:
    return any(
        matches_watch_item(store_code, sku, product_name, item)
        for item in items
    )


def store_sort_key(store_code: str) -> tuple:
    text = _norm(store_code)
    match = _STORE_TAIL.match(text)
    if match:
        return (match.group(1).casefold(), int(match.group(2)))
    return (text.casefold(), 0)


def watch_result_sort_key(
    store_code: str,
    product_name: str,
    ship_date: str,
) -> tuple:
    return (
        store_sort_key(store_code),
        _norm(product_name).casefold(),
        _norm(ship_date),
    )


def classify_shipment(tracking: str, latest_event: str) -> str:
    if not _norm(tracking):
        return "无运单"
    text = _norm(latest_event)
    folded = text.casefold()
    for marker in DELIVERED_MARKERS:
        if marker.casefold() in folded:
            return "已签收"
    return "在途"


def load_watchlist(path=None) -> list[WatchItem]:
    store = Path(path) if path is not None else WATCHLIST_PATH
    if not store.exists():
        return []
    try:
        payload = read_json(store)
    except Exception:
        return []
    raw_items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        return []
    items: list[WatchItem] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item = WatchItem(
            store_code=_norm(str(raw.get("store_code") or "")),
            name_contains=_norm(str(raw.get("name_contains") or "")),
            sku_contains=_norm(str(raw.get("sku_contains") or "")),
        )
        if not item.store_code or not item.name_contains:
            continue
        key = item_key(item)
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def save_watchlist(items: list[WatchItem], path=None) -> None:
    store = Path(path) if path is not None else WATCHLIST_PATH
    write_json(
        store,
        {
            "version": 1,
            "items": [asdict(item) for item in items],
        },
    )


def add_watch_item(
    store_code: str,
    name_contains: str,
    sku_contains: str = "",
    path=None,
) -> tuple[WatchItem, bool]:
    item = WatchItem(
        store_code=_norm(store_code),
        name_contains=_norm(name_contains),
        sku_contains=_norm(sku_contains),
    )
    if not item.store_code:
        raise ValueError("请选择店铺")
    if not item.name_contains:
        raise ValueError("请填写产品中文品名（包含即可）")
    items = load_watchlist(path)
    if any(item_key(existing) == item_key(item) for existing in items):
        return item, False
    items.append(item)
    save_watchlist(items, path)
    return item, True


def remove_watch_item(item: WatchItem, path=None) -> bool:
    items = load_watchlist(path)
    key = item_key(item)
    kept = [existing for existing in items if item_key(existing) != key]
    if len(kept) == len(items):
        return False
    save_watchlist(kept, path)
    return True
