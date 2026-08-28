from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import (
    Forwarder,
    ForwarderChannel,
    Shipment,
    ShipmentCarton,
    ShipmentItem,
)
from app.database.session import create_schema, make_engine, make_session_factory
from app.shipment_tracking.domain.commands import (
    ShipmentCartonInput,
    ShipmentCreateCommand,
    ShipmentItemInput,
)
from app.shipment_tracking.services.shipment_service import ShipmentService


@pytest.fixture
def session(tmp_path) -> Session:

    engine = make_engine(f"sqlite:///{tmp_path / 'idempotency.db'}")
    create_schema(engine)
    factory = make_session_factory(engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_create_shipment_is_idempotent(session: Session) -> None:

    _seed_forwarder(session)
    service = ShipmentService(session)
    command = _make_command()

    shipment1 = service.create_shipment(command)
    shipment2 = service.create_shipment(command)

    assert shipment1.id == shipment2.id
    assert session.scalar(select(func.count()).select_from(Shipment)) == 1
    assert session.scalar(select(func.count()).select_from(ShipmentItem)) == 1
    assert session.scalar(select(func.count()).select_from(ShipmentCarton)) == 1


def test_repeat_create_does_not_duplicate_items_or_cartons(session: Session) -> None:

    _seed_forwarder(session)
    service = ShipmentService(session)
    command = _make_command(
        items=[
            ShipmentItemInput(sku="SKU-1", product_name="a", quantity=2),
            ShipmentItemInput(sku="SKU-2", product_name="b", quantity=3),
        ],
        cartons=[
            ShipmentCartonInput(carton_number="FBA-AU000001", weight_kg=Decimal("4.20")),
            ShipmentCartonInput(carton_number="FBA-AU000002", weight_kg=Decimal("5.10")),
        ],
    )

    first = service.create_shipment(command)
    second = service.create_shipment(command)
    third = service.create_shipment(
        _make_command(
            source_file=r"I:\batch2\GYR2_FBA-A_迈创发票.xlsx",
            items=command.items,
            cartons=command.cartons,
        )
    )

    assert first.id == second.id == third.id
    assert session.scalar(select(func.count()).select_from(Shipment)) == 1
    assert session.scalar(select(func.count()).select_from(ShipmentItem)) == 2
    assert session.scalar(select(func.count()).select_from(ShipmentCarton)) == 2
    skus = set(session.scalars(select(ShipmentItem.sku)))
    numbers = set(session.scalars(select(ShipmentCarton.carton_number)))
    assert skus == {"SKU-1", "SKU-2"}
    assert numbers == {"FBA-AU000001", "FBA-AU000002"}


def _seed_forwarder(session: Session) -> None:

    forwarder = Forwarder(id=uuid4(), code="MC", name="迈创")
    channel = ForwarderChannel(
        id=uuid4(),
        forwarder_id=forwarder.id,
        code="MXS",
        name="美森限时达",
        default_transit_days=12,
    )
    session.add_all([forwarder, channel])
    session.commit()


def _make_command(
    *,
    source_file: str = r"I:\demo\GYR2_FBA-A_迈创发票.xlsx",
    items=None,
    cartons=None,
) -> ShipmentCreateCommand:

    if items is None:
        items = [
            ShipmentItemInput(
                sku="SKU-1",
                product_name="daisy necklace",
                quantity=18,
                weight_kg=Decimal("12.50"),
            )
        ]
    if cartons is None:
        cartons = [
            ShipmentCartonInput(
                carton_number="FBA-AU000001",
                weight_kg=Decimal("4.20"),
            )
        ]
    return ShipmentCreateCommand(
        store_code="美10",
        ship_date=date(2026, 8, 28),
        fba_shipment_id="FBA-A",
        destination_fc="GYR2",
        forwarder_code="MC",
        channel_code="MXS",
        owner="Mayn",
        source_file=source_file,
        items=items,
        cartons=cartons,
    )
