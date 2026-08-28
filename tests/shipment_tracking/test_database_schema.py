from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import (
    Forwarder,
    ForwarderChannel,
    Shipment,
    ShipmentTracking,
    TrackingEvent,
)
from app.database.session import create_schema, make_engine, make_session_factory
from app.shipment_tracking.domain.enums import HealthStatus, LifecycleStatus


REQUIRED_TABLES = {
    "shipments",
    "shipment_items",
    "shipment_cartons",
    "forwarders",
    "forwarder_channels",
    "shipment_tracking",
    "tracking_events",
    "shipment_eta_history",
    "shipment_exceptions",
    "api_sync_logs",
    "shipment_audit_logs",
}


@pytest.fixture
def session(tmp_path) -> Session:

    engine = make_engine(f"sqlite:///{tmp_path / 'shipment.db'}")
    create_schema(engine)
    factory = make_session_factory(engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_required_tables_exist(tmp_path) -> None:

    engine = make_engine(f"sqlite:///{tmp_path / 'schema.db'}")
    create_schema(engine)
    names = set(inspect(engine).get_table_names())
    engine.dispose()
    assert REQUIRED_TABLES <= names


def test_shipments_keep_lifecycle_and_health_separate(session: Session) -> None:

    forwarder, channel = _seed_forwarder(session)
    row = _make_shipment(forwarder.id, channel.id)
    session.add(row)
    session.commit()

    loaded = session.get(Shipment, row.id)
    assert loaded.lifecycle_status == LifecycleStatus.CREATED.value
    assert loaded.health_status == HealthStatus.NORMAL.value
    assert loaded.lifecycle_status != "EXCEPTION"


def test_shipment_code_is_unique(session: Session) -> None:

    forwarder, channel = _seed_forwarder(session)
    session.add(
        _make_shipment(forwarder.id, channel.id, code="SHP-1", fingerprint="fp-1")
    )
    session.commit()
    session.add(
        _make_shipment(forwarder.id, channel.id, code="SHP-1", fingerprint="fp-2")
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_source_fingerprint_is_unique(session: Session) -> None:

    forwarder, channel = _seed_forwarder(session)
    session.add(
        _make_shipment(
            forwarder.id, channel.id, code="SHP-A", fingerprint="same-fp"
        )
    )
    session.commit()
    session.add(
        _make_shipment(
            forwarder.id, channel.id, code="SHP-B", fingerprint="same-fp"
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_event_fingerprint_is_unique(session: Session) -> None:

    forwarder, channel = _seed_forwarder(session)
    shipment = _make_shipment(forwarder.id, channel.id)
    tracking = ShipmentTracking(
        id=uuid4(),
        shipment_id=shipment.id,
        tracking_number="MC123",
        forwarder_id=forwarder.id,
        channel_id=channel.id,
        is_primary=True,
    )
    event = TrackingEvent(
        id=uuid4(),
        tracking_id=tracking.id,
        event_code="PICKED_UP",
        event_name="已揽收",
        event_time=datetime.now(timezone.utc),
        event_fingerprint="dup-event",
    )
    duplicate = TrackingEvent(
        id=uuid4(),
        tracking_id=tracking.id,
        event_code="PICKED_UP",
        event_name="已揽收",
        event_time=datetime.now(timezone.utc),
        event_fingerprint="dup-event",
    )
    session.add_all([shipment, tracking, event])
    session.commit()
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.commit()


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


def _make_shipment(
    forwarder_id,
    channel_id,
    *,
    code="SHP-20260828-US10-0001",
    fingerprint="fp-unique",
):

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
