from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Shipment
from app.shipment_tracking.domain.enums import HealthStatus, LifecycleStatus


_INACTIVE = {
    LifecycleStatus.COMPLETED.value,
    LifecycleStatus.CANCELLED.value,
}


class ShipmentRepository:

    def __init__(self, session: Session) -> None:

        self._session = session

    def get_by_id(self, shipment_id: UUID) -> Shipment | None:

        return self._session.get(Shipment, shipment_id)

    def get_by_code(self, shipment_code: str) -> Shipment | None:

        return self._session.scalar(
            select(Shipment).where(Shipment.shipment_code == shipment_code)
        )

    def get_by_source_fingerprint(self, fingerprint: str) -> Shipment | None:

        return self._session.scalar(
            select(Shipment).where(Shipment.source_fingerprint == fingerprint)
        )

    def create(self, shipment: Shipment) -> Shipment:

        self._session.add(shipment)
        self._session.flush()
        return shipment

    def list_active(self) -> list[Shipment]:

        return list(
            self._session.scalars(
                select(Shipment)
                .where(Shipment.lifecycle_status.not_in(_INACTIVE))
                .order_by(Shipment.ship_date.desc(), Shipment.created_at.desc())
            )
        )

    def update_status(
        self,
        shipment_id: UUID,
        *,
        lifecycle_status: LifecycleStatus | str | None = None,
        health_status: HealthStatus | str | None = None,
    ) -> Shipment:

        shipment = self.get_by_id(shipment_id)
        if shipment is None:
            raise KeyError(f"shipment not found: {shipment_id}")
        if lifecycle_status is not None:
            value = _enum_value(lifecycle_status)
            if value == "EXCEPTION" or value not in {
                item.value for item in LifecycleStatus
            }:
                raise ValueError(f"非法生命周期状态：{value}")
            shipment.lifecycle_status = value
        if health_status is not None:
            shipment.health_status = _enum_value(health_status)
        self._session.flush()
        return shipment


def _enum_value(value: object) -> str:

    return value.value if hasattr(value, "value") else str(value)
