from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Shipment


MAX_CODE_RETRIES = 8


class ShipmentCodeError(RuntimeError):
    pass


class ShipmentCodeGenerator:

    def __init__(self, session: Session) -> None:

        self._session = session

    def generate_shipment_code(self, ship_date: date, store_code: str) -> str:

        prefix = _prefix(ship_date, store_code)
        start = self._max_sequence(prefix) + 1
        for offset in range(MAX_CODE_RETRIES):
            code = f"{prefix}{start + offset:04d}"
            if not self._exists(code):
                return code
        raise ShipmentCodeError(
            f"无法生成唯一货件编号（已重试 {MAX_CODE_RETRIES} 次）: {prefix}"
        )

    def _max_sequence(self, prefix: str) -> int:

        codes = self._session.scalars(
            select(Shipment.shipment_code).where(
                Shipment.shipment_code.like(f"{prefix}%")
            )
        ).all()
        max_seq = 0
        for code in codes:
            suffix = code[len(prefix) :]
            if suffix.isdigit():
                max_seq = max(max_seq, int(suffix))
        return max_seq

    def _exists(self, code: str) -> bool:

        return (
            self._session.scalar(
                select(Shipment.id).where(Shipment.shipment_code == code)
            )
            is not None
        )


def generate_shipment_code(
    ship_date: date,
    store_code: str,
    session: Session,
) -> str:

    return ShipmentCodeGenerator(session).generate_shipment_code(
        ship_date, store_code
    )


def _prefix(ship_date: date, store_code: str) -> str:

    return f"SHP-{ship_date.strftime('%Y%m%d')}-{store_code}-"
