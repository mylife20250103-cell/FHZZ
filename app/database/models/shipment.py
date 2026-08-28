from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.shipment_tracking.domain.enums import HealthStatus, LifecycleStatus


def _utcnow() -> datetime:

    return datetime.now(timezone.utc)


class Forwarder(Base):
    __tablename__ = "forwarders"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    credential_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class ForwarderChannel(Base):
    __tablename__ = "forwarder_channels"
    __table_args__ = (
        UniqueConstraint("forwarder_id", "code", name="uq_forwarder_channel_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    forwarder_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("forwarders.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    default_transit_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("shipment_code", name="uq_shipments_code"),
        UniqueConstraint("source_fingerprint", name="uq_shipments_source_fingerprint"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    shipment_code: Mapped[str] = mapped_column(String(64), nullable=False)
    store_code: Mapped[str] = mapped_column(String(32), nullable=False)
    ship_date: Mapped[date] = mapped_column(Date, nullable=False)
    fba_shipment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_fc: Mapped[str | None] = mapped_column(String(32), nullable=True)
    forwarder_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("forwarders.id"), nullable=False
    )
    channel_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("forwarder_channels.id"), nullable=False
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(32), default=LifecycleStatus.CREATED.value, nullable=False
    )
    health_status: Mapped[str] = mapped_column(
        String(32), default=HealthStatus.NORMAL.value, nullable=False
    )
    current_location: Mapped[str | None] = mapped_column(String(256), nullable=True)
    current_event: Mapped[str | None] = mapped_column(String(256), nullable=True)
    latest_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class ShipmentItem(Base):
    __tablename__ = "shipment_items"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    shipment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("shipments.id"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    product_name: Mapped[str] = mapped_column(String(256), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    asin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cartons: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)


class ShipmentCarton(Base):
    __tablename__ = "shipment_cartons"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    shipment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("shipments.id"), nullable=False
    )
    carton_number: Mapped[str] = mapped_column(String(64), nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    length_cm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    width_cm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)


class ShipmentTracking(Base):
    __tablename__ = "shipment_tracking"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    shipment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("shipments.id"), nullable=False
    )
    tracking_number: Mapped[str] = mapped_column(String(64), nullable=False)
    forwarder_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("forwarders.id"), nullable=False
    )
    channel_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("forwarder_channels.id"), nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class TrackingEvent(Base):
    __tablename__ = "tracking_events"
    __table_args__ = (
        UniqueConstraint("event_fingerprint", name="uq_tracking_events_fingerprint"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tracking_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("shipment_tracking.id"), nullable=False
    )
    event_code: Mapped[str] = mapped_column(String(64), nullable=False)
    event_name: Mapped[str] = mapped_column(String(128), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_status: Mapped[str | None] = mapped_column(String(256), nullable=True)
    event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class ShipmentEtaHistory(Base):
    __tablename__ = "shipment_eta_history"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    shipment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("shipments.id"), nullable=False
    )
    eta: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class ShipmentException(Base):
    __tablename__ = "shipment_exceptions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    shipment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("shipments.id"), nullable=False
    )
    exception_code: Mapped[str] = mapped_column(String(32), nullable=False)
    exception_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    responsible_party: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiSyncLog(Base):
    __tablename__ = "api_sync_logs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    shipment_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("shipments.id"), nullable=True
    )
    tracking_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("shipment_tracking.id"), nullable=True
    )
    forwarder_code: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShipmentAuditLog(Base):
    __tablename__ = "shipment_audit_logs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    shipment_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("shipments.id"), nullable=True
    )
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
