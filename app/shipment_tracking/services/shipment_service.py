from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import (
    Forwarder,
    ForwarderChannel,
    Shipment,
    ShipmentAuditLog,
    ShipmentCarton,
    ShipmentItem,
)
from app.shipment_tracking.domain.commands import ShipmentCreateCommand
from app.shipment_tracking.domain.enums import HealthStatus, LifecycleStatus
from app.shipment_tracking.repositories.shipment_repository import (
    ShipmentRepository,
)
from app.shipment_tracking.services.shipment_code import (
    MAX_CODE_RETRIES,
    ShipmentCodeError,
    generate_shipment_code,
)
from app.shipment_tracking.services.source_fingerprint import (
    build_source_fingerprint,
)


class ShipmentService:

    def __init__(self, session: Session) -> None:

        self._session = session
        self._shipments = ShipmentRepository(session)

    def create_shipment(self, command: ShipmentCreateCommand) -> Shipment:

        _validate(command)
        fingerprint = build_source_fingerprint(command)
        existing = self._shipments.get_by_source_fingerprint(fingerprint)
        if existing is not None:
            return existing
        forwarder_id, channel_id = self._require_forwarder(command)
        last_error: BaseException | None = None
        for _ in range(MAX_CODE_RETRIES):
            try:
                shipment = self._persist(
                    command, fingerprint, forwarder_id, channel_id
                )
                self._session.commit()
                return shipment
            except IntegrityError as exc:
                self._session.rollback()
                raced = self._shipments.get_by_source_fingerprint(fingerprint)
                if raced is not None:
                    return raced
                last_error = exc
                continue
            except Exception:
                self._session.rollback()
                raise
        raise ShipmentCodeError(
            f"无法生成唯一货件编号（已重试 {MAX_CODE_RETRIES} 次）"
        ) from last_error

    def _require_forwarder(
        self, command: ShipmentCreateCommand
    ) -> tuple[UUID, UUID]:

        forwarder = self._session.scalar(
            select(Forwarder).where(Forwarder.code == command.forwarder_code.strip())
        )
        if forwarder is None:
            raise ValueError(f"未知货代：{command.forwarder_code}")
        channel = self._session.scalar(
            select(ForwarderChannel).where(
                ForwarderChannel.forwarder_id == forwarder.id,
                ForwarderChannel.code == command.channel_code.strip(),
            )
        )
        if channel is None:
            raise ValueError(f"未知渠道：{command.channel_code}")
        return forwarder.id, channel.id

    def _persist(
        self,
        command: ShipmentCreateCommand,
        fingerprint: str,
        forwarder_id,
        channel_id,
    ) -> Shipment:

        code = generate_shipment_code(
            command.ship_date, command.store_code.strip(), self._session
        )
        shipment = Shipment(
            shipment_code=code,
            store_code=command.store_code.strip(),
            ship_date=command.ship_date,
            fba_shipment_id=command.fba_shipment_id.strip(),
            destination_fc=command.destination_fc,
            forwarder_id=forwarder_id,
            channel_id=channel_id,
            lifecycle_status=LifecycleStatus.CREATED.value,
            health_status=HealthStatus.NORMAL.value,
            owner=command.owner,
            source_file=command.source_file.strip(),
            source_fingerprint=fingerprint,
        )
        self._shipments.create(shipment)
        for item in command.items:
            self._session.add(
                ShipmentItem(
                    shipment_id=shipment.id,
                    sku=item.sku.strip(),
                    product_name=item.product_name.strip(),
                    quantity=item.quantity,
                    asin=item.asin,
                    cartons=item.cartons,
                    weight_kg=item.weight_kg,
                )
            )
        for carton in command.cartons:
            self._session.add(
                ShipmentCarton(
                    shipment_id=shipment.id,
                    carton_number=carton.carton_number.strip(),
                    weight_kg=carton.weight_kg,
                    length_cm=carton.length_cm,
                    width_cm=carton.width_cm,
                    height_cm=carton.height_cm,
                )
            )
        self._session.add(
            ShipmentAuditLog(
                shipment_id=shipment.id,
                actor=(command.owner or "system").strip() or "system",
                action="CREATE",
                new_value=code,
            )
        )
        self._session.flush()
        return shipment


def _validate(command: ShipmentCreateCommand) -> None:

    if not command.store_code.strip():
        raise ValueError("店铺不能为空")
    if not command.fba_shipment_id.strip():
        raise ValueError("FBA货件号不能为空")
    if not command.source_file.strip():
        raise ValueError("源文件不能为空")
    if not command.forwarder_code.strip():
        raise ValueError("货代不能为空")
    if not command.channel_code.strip():
        raise ValueError("渠道不能为空")
    if not command.items:
        raise ValueError("明细不能为空")
    if not command.cartons:
        raise ValueError("箱信息不能为空")
    for item in command.items:
        if not item.sku.strip():
            raise ValueError("SKU不能为空")
        if not item.product_name.strip():
            raise ValueError("品名不能为空")
        if item.quantity <= 0:
            raise ValueError("数量必须大于0")
    for carton in command.cartons:
        if not carton.carton_number.strip():
            raise ValueError("箱号不能为空")
        if carton.weight_kg <= 0:
            raise ValueError("箱重必须大于0")
