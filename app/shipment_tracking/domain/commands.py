from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass
class ShipmentItemInput:
    sku: str
    product_name: str
    quantity: int
    asin: str | None = None
    cartons: int | None = None
    weight_kg: Decimal | None = None


@dataclass
class ShipmentCartonInput:
    carton_number: str
    weight_kg: Decimal
    length_cm: Decimal | None = None
    width_cm: Decimal | None = None
    height_cm: Decimal | None = None


@dataclass
class ShipmentCreateCommand:
    """
    发票模块只认识这个命令，不依赖 Shipment 存库细节。
    """

    store_code: str
    ship_date: date
    fba_shipment_id: str
    destination_fc: str | None
    forwarder_code: str
    channel_code: str
    owner: str | None
    source_file: str
    items: list[ShipmentItemInput]
    cartons: list[ShipmentCartonInput]
