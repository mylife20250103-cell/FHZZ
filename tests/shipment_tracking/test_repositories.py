from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import (
    Forwarder,
    ForwarderChannel,
    Shipment,
    ShipmentException,
    TrackingEvent,
)
from app.database.session import create_schema, make_engine, make_session_factory
from app.shipment_tracking.domain.enums import (
    ExceptionSeverity,
    ExceptionStatus,
    HealthStatus,
    LifecycleStatus,
    ResponsibleParty,
)
from app.shipment_tracking.repositories.exception_repository import (
    ExceptionRepository,
)
from app.shipment_tracking.repositories.shipment_repository import (
    ShipmentRepository,
)
from app.shipment_tracking.repositories.tracking_repository import (
    TrackingRepository,
)


@pytest.fixture
def session(tmp_path) -> Session:

    engine = make_engine(f"sqlite:///{tmp_path / 'repo.db'}")
    create_schema(engine)
    factory = make_session_factory(engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_shipment_repository_create_and_get(session: Session) -> None:

    forwarder, channel = _seed_forwarder(session)
    repo = ShipmentRepository(session)
    created = repo.create(_make_shipment(forwarder.id, channel.id))

    assert repo.get_by_id(created.id).id == created.id
    assert repo.get_by_code(created.shipment_code).id == created.id
    assert repo.get_by_source_fingerprint("fp-1").id == created.id


def test_list_active_excludes_completed_and_cancelled(session: Session) -> None:

    forwarder, channel = _seed_forwarder(session)
    repo = ShipmentRepository(session)
    active = repo.create(
        _make_shipment(forwarder.id, channel.id, code="SHP-A", fingerprint="a")
    )
    done = repo.create(
        _make_shipment(forwarder.id, channel.id, code="SHP-B", fingerprint="b")
    )
    repo.update_status(done.id, lifecycle_status=LifecycleStatus.COMPLETED)
    cancelled = repo.create(
        _make_shipment(forwarder.id, channel.id, code="SHP-C", fingerprint="c")
    )
    repo.update_status(cancelled.id, lifecycle_status=LifecycleStatus.CANCELLED)

    ids = {item.id for item in repo.list_active()}
    assert active.id in ids
    assert done.id not in ids
    assert cancelled.id not in ids


def test_update_status_keeps_lifecycle_and_health_separate(session: Session) -> None:

    forwarder, channel = _seed_forwarder(session)
    repo = ShipmentRepository(session)
    shipment = repo.create(_make_shipment(forwarder.id, channel.id))
    repo.update_status(
        shipment.id,
        lifecycle_status=LifecycleStatus.CUSTOMS_CLEARANCE,
        health_status=HealthStatus.CRITICAL,
    )
    loaded = repo.get_by_id(shipment.id)
    assert loaded.lifecycle_status == LifecycleStatus.CUSTOMS_CLEARANCE.value
    assert loaded.health_status == HealthStatus.CRITICAL.value


def test_add_event_if_new_deduplicates_by_fingerprint(session: Session) -> None:

    forwarder, channel = _seed_forwarder(session)
    shipments = ShipmentRepository(session)
    tracking = TrackingRepository(session)
    shipment = shipments.create(_make_shipment(forwarder.id, channel.id))
    record = tracking.add_tracking(
        shipment_id=shipment.id,
        tracking_number="MC123",
        forwarder_id=forwarder.id,
        channel_id=channel.id,
        is_primary=True,
    )
    now = datetime.now(timezone.utc)
    first = tracking.add_event_if_new(
        tracking_id=record.id,
        event_code="PICKED_UP",
        event_name="已揽收",
        event_time=now,
        location="深圳",
        event_fingerprint="evt-1",
    )
    second = tracking.add_event_if_new(
        tracking_id=record.id,
        event_code="PICKED_UP",
        event_name="已揽收",
        event_time=now,
        location="深圳",
        event_fingerprint="evt-1",
    )
    assert first.id == second.id
    count = session.scalar(select(func.count()).select_from(TrackingEvent))
    assert count == 1
    latest = tracking.get_latest_event(record.id)
    assert latest.id == first.id
    assert tracking.get_tracking(record.id).tracking_number == "MC123"
    assert [item.id for item in tracking.list_events(record.id)] == [first.id]


def test_create_if_not_open_and_resolve_does_not_delete(session: Session) -> None:

    forwarder, channel = _seed_forwarder(session)
    shipments = ShipmentRepository(session)
    exceptions = ExceptionRepository(session)
    shipment = shipments.create(_make_shipment(forwarder.id, channel.id))
    first = exceptions.create_if_not_open(
        shipment_id=shipment.id,
        exception_code="EX001",
        exception_name="TRACKING_NOT_CREATED",
        severity=ExceptionSeverity.HIGH,
        responsible_party=ResponsibleParty.FORWARDER,
    )
    second = exceptions.create_if_not_open(
        shipment_id=shipment.id,
        exception_code="EX001",
        exception_name="TRACKING_NOT_CREATED",
        severity=ExceptionSeverity.HIGH,
        responsible_party=ResponsibleParty.FORWARDER,
    )
    assert first.id == second.id
    assert len(exceptions.get_open_exceptions(shipment.id)) == 1

    resolved = exceptions.resolve(first.id)
    assert resolved.status == ExceptionStatus.RESOLVED.value
    assert resolved.resolved_at is not None
    assert exceptions.get_open_exceptions(shipment.id) == []
    remaining = session.scalar(select(func.count()).select_from(ShipmentException))
    assert remaining == 1


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
    session.flush()
    return forwarder, channel


def _make_shipment(forwarder_id, channel_id, *, code="SHP-1", fingerprint="fp-1"):

    return Shipment(
        id=uuid4(),
        shipment_code=code,
        store_code="美10",
        ship_date=date(2026, 8, 28),
        fba_shipment_id="FBA-A",
        destination_fc="GYR2",
        forwarder_id=forwarder_id,
        channel_id=channel_id,
        lifecycle_status=LifecycleStatus.CREATED.value,
        health_status=HealthStatus.NORMAL.value,
        owner="Mayn",
        source_file="demo.xlsx",
        source_fingerprint=fingerprint,
    )
