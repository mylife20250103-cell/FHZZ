from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from app.shipment_tracking.domain.commands import (
    ShipmentCartonInput,
    ShipmentCreateCommand,
    ShipmentItemInput,
)


def test_create_command_holds_confirmed_invoice_fields() -> None:

    command = ShipmentCreateCommand(
        store_code="美10",
        ship_date=date(2026, 8, 28),
        fba_shipment_id="FBA-A",
        destination_fc="GYR2",
        forwarder_code="MC",
        channel_code="美森限时达",
        owner="Mayn",
        source_file=r"I:\demo\GYR2_FBA-A_迈创发票.xlsx",
        items=[
            ShipmentItemInput(
                sku="SKU-1",
                product_name="daisy necklace",
                quantity=18,
                asin="B0TEST",
                cartons=3,
                weight_kg=Decimal("12.50"),
            )
        ],
        cartons=[
            ShipmentCartonInput(
                carton_number="FBA-AU000001",
                weight_kg=Decimal("4.20"),
                length_cm=Decimal("50"),
                width_cm=Decimal("40"),
                height_cm=Decimal("30"),
            )
        ],
    )

    assert command.store_code == "美10"
    assert command.ship_date == date(2026, 8, 28)
    assert command.fba_shipment_id == "FBA-A"
    assert command.destination_fc == "GYR2"
    assert command.forwarder_code == "MC"
    assert command.channel_code == "美森限时达"
    assert command.items[0].sku == "SKU-1"
    assert command.cartons[0].carton_number == "FBA-AU000001"
    assert command.cartons[0].weight_kg == Decimal("4.20")


def test_optional_item_and_carton_fields_default_none() -> None:

    item = ShipmentItemInput(
        sku="SKU-2",
        product_name="patch",
        quantity=1,
    )
    carton = ShipmentCartonInput(
        carton_number="FBA-BU000001",
        weight_kg=Decimal("1.00"),
    )

    assert item.asin is None
    assert item.cartons is None
    assert item.weight_kg is None
    assert carton.length_cm is None
    assert carton.width_cm is None
    assert carton.height_cm is None


def test_commands_module_has_no_database_imports() -> None:

    source = Path(
        "app/shipment_tracking/domain/commands.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "sqlalchemy" not in lowered
    assert "repository" not in lowered
    assert "sqlite" not in lowered
