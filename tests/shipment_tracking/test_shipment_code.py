from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.database.models import Forwarder, ForwarderChannel, Shipment
from app.database.session import create_schema, make_engine, make_session_factory
from app.shipment_tracking.domain.enums import HealthStatus, LifecycleStatus
from app.shipment_tracking.services.shipment_code import (
    MAX_CODE_RETRIES,
    ShipmentCodeError,
    ShipmentCodeGenerator,
    generate_shipment_code,
)


@pytest.fixture
def session(tmp_path) -> Session:

    engine = make_engine(f"sqlite:///{tmp_path / 'code.db'}")
    create_schema(engine)
    factory = make_session_factory(engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_first_code_matches_plan_format(session: Session) -> None:

    code = generate_shipment_code(date(2026, 8, 28), "US10", session)
    assert code == "SHP-20260828-US10-0001"


def test_sequence_increments_for_same_date_and_store(session: Session) -> None:

    forwarder, channel = _seed_forwarder(session)
    _insert_code(session, forwarder.id, channel.id, "SHP-20260828-US10-0001")

    second = generate_shipment_code(date(2026, 8, 28), "US10", session)
    assert second == "SHP-20260828-US10-0002"

    _insert_code(
        session, forwarder.id, channel.id, second, fingerprint="fp-2"
    )
    third = generate_shipment_code(date(2026, 8, 28), "US10", session)
    assert third == "SHP-20260828-US10-0003"


def test_sequence_is_not_global_count(session: Session) -> None:

    forwarder, channel = _seed_forwarder(session)
    for index in range(1, 6):
        _insert_code(
            session,
            forwarder.id,
            channel.id,
            f"SHP-20260828-US11-{index:04d}",
            fingerprint=f"other-{index}",
            store_code="US11",
        )

    code = generate_shipment_code(date(2026, 8, 28), "US10", session)
    assert code == "SHP-20260828-US10-0001"


def test_different_dates_have_independent_sequences(session: Session) -> None:

    forwarder, channel = _seed_forwarder(session)
    _insert_code(session, forwarder.id, channel.id, "SHP-20260828-US10-0001")

    code = generate_shipment_code(date(2026, 8, 29), "US10", session)
    assert code == "SHP-20260829-US10-0001"


def test_retries_skip_occupied_candidates(session: Session, monkeypatch) -> None:

    forwarder, channel = _seed_forwarder(session)
    _insert_code(session, forwarder.id, channel.id, "SHP-20260828-US10-0001")
    _insert_code(
        session,
        forwarder.id,
        channel.id,
        "SHP-20260828-US10-0002",
        fingerprint="fp-2",
    )
    generator = ShipmentCodeGenerator(session)
    monkeypatch.setattr(generator, "_max_sequence", lambda prefix: 0)

    code = generator.generate_shipment_code(date(2026, 8, 28), "US10")
    assert code == "SHP-20260828-US10-0003"


def test_raises_after_limited_retries(session: Session, monkeypatch) -> None:

    forwarder, channel = _seed_forwarder(session)
    for index in range(1, MAX_CODE_RETRIES + 1):
        _insert_code(
            session,
            forwarder.id,
            channel.id,
            f"SHP-20260828-US10-{index:04d}",
            fingerprint=f"fp-{index}",
        )
    generator = ShipmentCodeGenerator(session)
    monkeypatch.setattr(generator, "_max_sequence", lambda prefix: 0)

    with pytest.raises(ShipmentCodeError, match="无法生成唯一货件编号"):
        generator.generate_shipment_code(date(2026, 8, 28), "US10")


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


def _insert_code(
    session: Session,
    forwarder_id,
    channel_id,
    code: str,
    *,
    fingerprint: str = "fp-1",
    store_code: str = "US10",
) -> Shipment:

    ship_date = date(
        int(code[4:8]),
        int(code[8:10]),
        int(code[10:12]),
    )
    row = Shipment(
        id=uuid4(),
        shipment_code=code,
        store_code=store_code,
        ship_date=ship_date,
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
    session.add(row)
    session.flush()
    return row
