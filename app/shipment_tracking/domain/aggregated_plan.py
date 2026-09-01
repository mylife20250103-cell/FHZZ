from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AggregatedSkuQty:
    sku: str
    quantity: int
    product_name: str | None = None
    asin: str | None = None


@dataclass(frozen=True)
class AggregatedFBA:
    fba_id: str
    destination_fc: str | None
    items: tuple[AggregatedSkuQty, ...]
