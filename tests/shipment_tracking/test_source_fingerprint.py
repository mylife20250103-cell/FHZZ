from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from app.shipment_tracking.domain.commands import (
    ShipmentCartonInput,
    ShipmentCreateCommand,
    ShipmentItemInput,
)
from app.shipment_tracking.services.source_fingerprint import (
    build_source_fingerprint,
)


def test_same_command_produces_same_sha256() -> None:

    command = _make_command()
    first = build_source_fingerprint(command)
    second = build_source_fingerprint(_make_command())
    assert first == second
    assert len(first) == 64
    int(first, 16)


def test_repeat_invoice_keeps_one_fingerprint() -> None:

    first = build_source_fingerprint(
        _make_command(source_file=r"I:\batch1\GYR2_FBA-A_迈创发票.xlsx")
    )
    second = build_source_fingerprint(
        _make_command(source_file=r"I:\batch2\GYR2_FBA-A_迈创发票.xlsx")
    )
    third = build_source_fingerprint(
        _make_command(source_file="I:/batch3/GYR2_FBA-A_迈创发票.xlsx")
    )
    assert first == second == third


def test_carton_order_does_not_change_fingerprint() -> None:

    left = build_source_fingerprint(
        _make_command(
            cartons=["FBA-AU000001", "FBA-AU000002"],
        )
    )
    right = build_source_fingerprint(
        _make_command(
            cartons=["FBA-AU000002", "FBA-AU000001"],
        )
    )
    assert left == right


def test_business_key_change_changes_fingerprint() -> None:

    baseline = build_source_fingerprint(_make_command())
    assert build_source_fingerprint(_make_command(store_code="美11")) != baseline
    assert (
        build_source_fingerprint(_make_command(ship_date=date(2026, 8, 29)))
        != baseline
    )
    assert (
        build_source_fingerprint(_make_command(fba_shipment_id="FBA-B"))
        != baseline
    )
    assert (
        build_source_fingerprint(_make_command(cartons=["FBA-AU000099"]))
        != baseline
    )


def test_volatile_fields_are_ignored() -> None:

    baseline = build_source_fingerprint(_make_command())
    same = build_source_fingerprint(
        _make_command(owner="other", destination_fc="ONT8", sku="SKU-9")
    )
    assert same == baseline


def test_fingerprint_module_has_no_database_imports() -> None:

    source = Path(
        "app/shipment_tracking/services/source_fingerprint.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "sqlalchemy" not in lowered
    assert "repository" not in lowered
    assert "sqlite" not in lowered


def _make_command(
    *,
    store_code: str = "美10",
    ship_date: date = date(2026, 8, 28),
    fba_shipment_id: str = "FBA-A",
    destination_fc: str | None = "GYR2",
    owner: str | None = "Mayn",
    source_file: str = r"I:\demo\GYR2_FBA-A_迈创发票.xlsx",
    sku: str = "SKU-1",
    cartons: list[str] | None = None,
) -> ShipmentCreateCommand:

    numbers = cartons or ["FBA-AU000001"]
    return ShipmentCreateCommand(
        store_code=store_code,
        ship_date=ship_date,
        fba_shipment_id=fba_shipment_id,
        destination_fc=destination_fc,
        forwarder_code="MC",
        channel_code="美森限时达",
        owner=owner,
        source_file=source_file,
        items=[
            ShipmentItemInput(
                sku=sku,
                product_name="daisy necklace",
                quantity=18,
                weight_kg=Decimal("12.50"),
            )
        ],
        cartons=[
            ShipmentCartonInput(carton_number=number, weight_kg=Decimal("4.20"))
            for number in numbers
        ],
    )
