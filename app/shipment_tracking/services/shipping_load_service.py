from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.invoice_config import BATCH_ROOT, MERGE_RESULT_ROOT
from app.shipment_tracking.aggregation.fba_aggregator import aggregate_fba_sku_qty
from app.shipment_tracking.domain.aggregated_plan import AggregatedFBA
from app.shipment_tracking.domain.parsed_plan import ParsedTrackingPlan
from app.shipment_tracking.indexing.shipping_file_indexer import (
    IndexedShippingFile,
    index_shipping_files,
    matches_date_range,
    matches_period,
)
from app.shipment_tracking.parsing.shipping_plan_reader import parse_shipping_plan
from app.shipment_tracking.services.channel_binding import (
    ChannelBinding,
    load_confirmed_channels,
)
from app.shipment_tracking.services.forwarder_binding import (
    ForwarderBinding,
    load_confirmed_forwarders,
)


@dataclass(frozen=True)
class ShippingSnapshot:
    source: IndexedShippingFile
    plan: ParsedTrackingPlan
    aggregated: tuple[AggregatedFBA, ...]


@dataclass(frozen=True)
class ShippingLoadResult:
    snapshots: tuple[ShippingSnapshot, ...]
    errors: tuple[str, ...]
    forwarders: dict[str, ForwarderBinding]
    channels: dict[str, ChannelBinding]


def load_shipping_snapshot(item: IndexedShippingFile) -> ShippingSnapshot:
    """一份发货单：Batch 身份 + FBA → Carton → SKU + FBA → SKU 合计。"""

    plan = parse_shipping_plan(item.path, store_code=item.store_code)
    return ShippingSnapshot(
        source=item,
        plan=plan,
        aggregated=aggregate_fba_sku_qty(plan),
    )


def load_store_snapshots(
    root,
    store_code: str | None = None,
    batch_root=None,
    merge_root=None,
    *,
    year: int | None = None,
    month: int | None = None,
    all_periods: bool = True,
    start_date: date | None = None,
    end_date: date | None = None,
) -> ShippingLoadResult:
    indexed = index_shipping_files(root, store_code=store_code)
    if start_date is not None and end_date is not None:
        items = [
            item
            for item in indexed
            if matches_date_range(item, start_date, end_date)
        ]
    else:
        items = [
            item
            for item in indexed
            if matches_period(item, year, month, all_periods=all_periods)
        ]
    snapshots: list[ShippingSnapshot] = []
    errors: list[str] = []
    for item in items:
        try:
            snapshots.append(load_shipping_snapshot(item))
        except Exception as exc:
            errors.append(f"{item.path.name}：{exc}")
    used_batch = batch_root if batch_root is not None else BATCH_ROOT
    used_merge = merge_root if merge_root is not None else MERGE_RESULT_ROOT
    forwarders = load_confirmed_forwarders(used_batch, store_code=store_code)
    channels = load_confirmed_channels(
        used_batch,
        used_merge,
        store_code=store_code,
    )
    return ShippingLoadResult(
        tuple(snapshots),
        tuple(errors),
        forwarders,
        channels,
    )
