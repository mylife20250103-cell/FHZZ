from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ParsedCartonItem:
    sku: str
    quantity: int
    product_name: str | None = None
    asin: str | None = None


@dataclass(frozen=True)
class ParsedCarton:
    fba_id: str
    destination_fc: str | None
    carton_no: str | None
    weight_kg: Decimal | None
    length_cm: Decimal | None
    width_cm: Decimal | None
    height_cm: Decimal | None
    items: tuple[ParsedCartonItem, ...]


@dataclass(frozen=True)
class ParsedFBA:
    fba_id: str
    destination_fc: str | None
    cartons: tuple[ParsedCarton, ...]


@dataclass(frozen=True)
class ParsedTrackingPlan:
    fbas: tuple[ParsedFBA, ...]
