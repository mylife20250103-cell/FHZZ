from __future__ import annotations

from app.shipment_tracking.domain.enums import (
    ExceptionSeverity,
    ExceptionStatus,
    HealthStatus,
    LifecycleStatus,
    ResponsibleParty,
)


def test_customs_clearance_value() -> None:

    assert LifecycleStatus.CUSTOMS_CLEARANCE.value == "CUSTOMS_CLEARANCE"


def test_lifecycle_has_no_exception_status() -> None:

    names = {item.name for item in LifecycleStatus}
    values = {item.value for item in LifecycleStatus}
    assert "EXCEPTION" not in names
    assert "EXCEPTION" not in values


def test_health_is_separate_from_lifecycle() -> None:

    assert HealthStatus.CRITICAL.value == "CRITICAL"
    assert "CRITICAL" not in {item.name for item in LifecycleStatus}


def test_exception_and_party_enums() -> None:

    assert ExceptionStatus.OPEN.value == "OPEN"
    assert ExceptionStatus.RESOLVED.value == "RESOLVED"
    assert ExceptionSeverity.CRITICAL.value == "CRITICAL"
    assert ResponsibleParty.FORWARDER.value == "FORWARDER"
    assert ResponsibleParty.AMAZON.value == "AMAZON"
