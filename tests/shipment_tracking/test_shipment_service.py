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
    ShipmentAuditLog,
    ShipmentCarton,
    ShipmentItem,
)
from app.database.session import create_schema, make_engine, make_session_factory
from app.shipment_tracking.domain.commands import (
    ShipmentCartonInput,
    ShipmentCreateCommand,
    ShipmentItemInput,
)
from app.shipment_tracking.domain.enums import HealthStatus, LifecycleStatus
from app.shipment_tracking.services.shipment_code import generate_shipment_code
from app.shipment_tracking.services.shipment_service import ShipmentService
from app.shipment_tracking.services.source_fingerprint import (
    build_source_fingerprint,
)


@pytest.fixture
def session(tmp_path) -> Session:

    engine = make_engine(f"sqlite:///{tmp_path / 'create.db'}")
    create_schema(engine)
    factory = make_session_factory(engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_create_shipment_persists_items_cartons_and_audit(session: Session) -> None:

    _seed_forwarder(session)
    command = _make_command()
    created = ShipmentService(session).create_shipment(command)

    assert created.shipment_code == "SHP-20260828-美10-0001"
    assert created.lifecycle_status == LifecycleStatus.CREATED.value
    assert created.health_status == HealthStatus.NORMAL.value
    assert created.source_fingerprint == build_source_fingerprint(command)
    assert created.fba_shipment_id == "FBA-A"
    items = list(session.scalars(select(ShipmentItem)))
    cartons = list(session.scalars(select(ShipmentCarton)))
    audits = list(session.scalars(select(ShipmentAuditLog)))
    assert len(items) == 1
    assert items[0].sku == "SKU-1"
    assert items[0].quantity == 18
    assert len(cartons) == 1
    assert cartons[0].carton_number == "FBA-AU000001"
    assert len(audits) == 1
    assert audits[0].action == "CREATE"
    assert audits[0].actor == "Mayn"
    assert audits[0].shipment_id == created.id


def test_create_shipment_returns_existing_by_fingerprint(session: Session) -> None:

    _seed_forwarder(session)
    service = ShipmentService(session)
    first = service.create_shipment(_make_command())
    second = service.create_shipment(_make_command())
    assert first.id == second.id
    assert session.scalar(select(func.count()).select_from(Shipment)) == 1


def test_create_shipment_rejects_invalid_command(session: Session) -> None:

    _seed_forwarder(session)
    service = ShipmentService(session)
    with pytest.raises(ValueError, match="店铺不能为空"):
        service.create_shipment(_make_command(store_code="  "))
    with pytest.raises(ValueError, match="明细不能为空"):
        service.create_shipment(_make_command(items=[]))
    with pytest.raises(ValueError, match="箱信息不能为空"):
        service.create_shipment(_make_command(cartons=[]))
    assert session.scalar(select(func.count()).select_from(Shipment)) == 0


def test_create_shipment_rejects_unknown_forwarder(session: Session) -> None:

    service = ShipmentService(session)
    with pytest.raises(ValueError, match="未知货代"):
        service.create_shipment(_make_command())


def test_commit_failure_rolls_back_entire_shipment(session: Session, monkeypatch) -> None:

    _seed_forwarder(session)
    service = ShipmentService(session)
    monkeypatch.setattr(
        session,
        "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("写入失败")),
    )
    with pytest.raises(RuntimeError, match="写入失败"):
        service.create_shipment(_make_command())
    assert session.scalar(select(func.count()).select_from(Shipment)) == 0
    assert session.scalar(select(func.count()).select_from(ShipmentItem)) == 0
    assert session.scalar(select(func.count()).select_from(ShipmentCarton)) == 0
    assert session.scalar(select(func.count()).select_from(ShipmentAuditLog)) == 0


def test_retries_when_generated_code_already_taken(
    session: Session, monkeypatch
) -> None:

    forwarder, channel = _seed_forwarder(session)
    taken = generate_shipment_code(date(2026, 8, 28), "美10", session)
    session.add(
        Shipment(
            id=uuid4(),
            shipment_code=taken,
            store_code="美10",
            ship_date=date(2026, 8, 28),
            fba_shipment_id="FBA-OTHER",
            destination_fc="GYR2",
            forwarder_id=forwarder.id,
            channel_id=channel.id,
            lifecycle_status=LifecycleStatus.CREATED.value,
            health_status=HealthStatus.NORMAL.value,
            owner="Mayn",
            source_file="other.xlsx",
            source_fingerprint="other-fp",
        )
    )
    session.commit()

    calls = {"n": 0}
    real = generate_shipment_code

    def fake(ship_date, store_code, db):

        calls["n"] += 1
        if calls["n"] == 1:
            return taken
        return real(ship_date, store_code, db)

    monkeypatch.setattr(
        "app.shipment_tracking.services.shipment_service.generate_shipment_code",
        fake,
    )
    created = ShipmentService(session).create_shipment(_make_command())
    assert created.shipment_code != taken
    assert created.shipment_code == "SHP-20260828-美10-0002"
    assert calls["n"] == 2


def _seed_forwarder(session: Session) -> tuple[Forwarder, ForwarderChannel]:

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
    return forwarder, channel


def _make_command(
    *,
    store_code: str = "美10",
    items=None,
    cartons=None,
) -> ShipmentCreateCommand:

    if items is None:
        items = [
            ShipmentItemInput(
                sku="SKU-1",
                product_name="daisy necklace",
                quantity=18,
                asin="B0TEST",
                cartons=3,
                weight_kg=Decimal("12.50"),
            )
        ]
    if cartons is None:
        cartons = [
            ShipmentCartonInput(
                carton_number="FBA-AU000001",
                weight_kg=Decimal("4.20"),
                length_cm=Decimal("50"),
                width_cm=Decimal("40"),
                height_cm=Decimal("30"),
            )
        ]
    return ShipmentCreateCommand(
        store_code=store_code,
        ship_date=date(2026, 8, 28),
        fba_shipment_id="FBA-A",
        destination_fc="GYR2",
        forwarder_code="MC",
        channel_code="MXS",
        owner="Mayn",
        source_file=r"I:\demo\GYR2_FBA-A_迈创发票.xlsx",
        items=items,
        cartons=cartons,
    )
