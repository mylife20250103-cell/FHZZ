from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ShipmentTracking, TrackingEvent


class TrackingRepository:

    def __init__(self, session: Session) -> None:

        self._session = session

    def add_tracking(
        self,
        shipment_id: UUID,
        tracking_number: str,
        forwarder_id: UUID,
        channel_id: UUID,
        is_primary: bool = True,
    ) -> ShipmentTracking:

        row = ShipmentTracking(
            shipment_id=shipment_id,
            tracking_number=tracking_number.strip(),
            forwarder_id=forwarder_id,
            channel_id=channel_id,
            is_primary=is_primary,
            is_active=True,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get_tracking(self, tracking_id: UUID) -> ShipmentTracking | None:

        return self._session.get(ShipmentTracking, tracking_id)

    def add_event_if_new(
        self,
        tracking_id: UUID,
        *,
        event_code: str,
        event_name: str,
        event_time: datetime,
        event_fingerprint: str,
        location: str | None = None,
        description: str | None = None,
        raw_status_code: str | None = None,
        raw_status: str | None = None,
    ) -> TrackingEvent:

        existing = self._session.scalar(
            select(TrackingEvent).where(
                TrackingEvent.event_fingerprint == event_fingerprint
            )
        )
        if existing is not None:
            return existing

        event = TrackingEvent(
            tracking_id=tracking_id,
            event_code=event_code,
            event_name=event_name,
            event_time=event_time,
            location=location,
            description=description,
            raw_status_code=raw_status_code,
            raw_status=raw_status,
            event_fingerprint=event_fingerprint,
        )
        self._session.add(event)
        self._session.flush()
        return event

    def get_latest_event(self, tracking_id: UUID) -> TrackingEvent | None:

        return self._session.scalar(
            select(TrackingEvent)
            .where(TrackingEvent.tracking_id == tracking_id)
            .order_by(TrackingEvent.event_time.desc(), TrackingEvent.created_at.desc())
            .limit(1)
        )

    def list_events(self, tracking_id: UUID) -> list[TrackingEvent]:

        return list(
            self._session.scalars(
                select(TrackingEvent)
                .where(TrackingEvent.tracking_id == tracking_id)
                .order_by(TrackingEvent.event_time.asc(), TrackingEvent.created_at.asc())
            )
        )
