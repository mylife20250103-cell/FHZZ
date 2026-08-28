from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ShipmentException
from app.shipment_tracking.domain.enums import (
    ExceptionSeverity,
    ExceptionStatus,
    ResponsibleParty,
)


_OPEN_STATUSES = {
    ExceptionStatus.OPEN.value,
    ExceptionStatus.FOLLOWING.value,
    ExceptionStatus.WAITING.value,
}


class ExceptionRepository:

    def __init__(self, session: Session) -> None:

        self._session = session

    def create_if_not_open(
        self,
        shipment_id: UUID,
        exception_code: str,
        exception_name: str,
        severity: ExceptionSeverity | str,
        responsible_party: ResponsibleParty | str,
        message: str | None = None,
    ) -> ShipmentException:

        existing = self._session.scalar(
            select(ShipmentException).where(
                ShipmentException.shipment_id == shipment_id,
                ShipmentException.exception_code == exception_code,
                ShipmentException.status.in_(_OPEN_STATUSES),
            )
        )
        if existing is not None:
            return existing

        row = ShipmentException(
            shipment_id=shipment_id,
            exception_code=exception_code,
            exception_name=exception_name,
            status=ExceptionStatus.OPEN.value,
            severity=_enum_value(severity),
            responsible_party=_enum_value(responsible_party),
            message=message,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get_open_exceptions(
        self,
        shipment_id: UUID | None = None,
    ) -> list[ShipmentException]:

        stmt = select(ShipmentException).where(
            ShipmentException.status.in_(_OPEN_STATUSES)
        )
        if shipment_id is not None:
            stmt = stmt.where(ShipmentException.shipment_id == shipment_id)
        stmt = stmt.order_by(ShipmentException.opened_at.desc())
        return list(self._session.scalars(stmt))

    def resolve(self, exception_id: UUID) -> ShipmentException:

        row = self._session.get(ShipmentException, exception_id)
        if row is None:
            raise KeyError(f"exception not found: {exception_id}")
        row.status = ExceptionStatus.RESOLVED.value
        row.resolved_at = datetime.now(timezone.utc)
        self._session.flush()
        return row


def _enum_value(value: object) -> str:

    return value.value if hasattr(value, "value") else str(value)
