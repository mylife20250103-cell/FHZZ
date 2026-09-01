from __future__ import annotations

from dataclasses import dataclass

from app.shipment_tracking.aggregation.fba_aggregator import aggregate_fba_sku_qty
from app.shipment_tracking.domain.aggregated_plan import AggregatedFBA
from app.shipment_tracking.domain.parsed_plan import ParsedTrackingPlan
from app.shipment_tracking.indexing.shipping_file_indexer import (
    IndexedShippingFile,
    index_shipping_files,
)
from app.shipment_tracking.parsing.shipping_plan_reader import parse_shipping_plan


@dataclass(frozen=True)
class ShippingSnapshot:
    source: IndexedShippingFile
    plan: ParsedTrackingPlan
    aggregated: tuple[AggregatedFBA, ...]


@dataclass(frozen=True)
class ShippingLoadResult:
    snapshots: tuple[ShippingSnapshot, ...]
    errors: tuple[str, ...]


def load_shipping_snapshot(item: IndexedShippingFile) -> ShippingSnapshot:
    """一份发货单：Batch 身份 + FBA → Carton → SKU + FBA → SKU 合计。"""

    plan = parse_shipping_plan(item.path, store_code=item.store_code)
    return ShippingSnapshot(
        source=item,
        plan=plan,
        aggregated=aggregate_fba_sku_qty(plan),
    )


def load_store_snapshots(root, store_code: str) -> ShippingLoadResult:
    items = index_shipping_files(root, store_code=store_code)
    snapshots: list[ShippingSnapshot] = []
    errors: list[str] = []
    for item in items:
        try:
            snapshots.append(load_shipping_snapshot(item))
        except Exception as exc:
            errors.append(f"{item.path.name}：{exc}")
    return ShippingLoadResult(tuple(snapshots), tuple(errors))
