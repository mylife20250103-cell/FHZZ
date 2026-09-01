from __future__ import annotations

from app.shipment_tracking.domain.aggregated_plan import (
    AggregatedFBA,
    AggregatedSkuQty,
)
from app.shipment_tracking.domain.parsed_plan import ParsedTrackingPlan


def aggregate_fba_sku_qty(plan: ParsedTrackingPlan) -> tuple[AggregatedFBA, ...]:
    """
    FBA → SKU → TotalQty。
    只按同一个 FBA 下各箱数量求和，不把不同 FBA 的同一 SKU 加在一起。
    """

    result = []
    for fba in plan.fbas:
        totals: dict[str, list] = {}
        order: list[str] = []
        for carton in fba.cartons:
            for item in carton.items:
                if item.sku not in totals:
                    order.append(item.sku)
                    totals[item.sku] = [0, item.product_name, item.asin]
                totals[item.sku][0] += item.quantity
                if not totals[item.sku][1] and item.product_name:
                    totals[item.sku][1] = item.product_name
                if not totals[item.sku][2] and item.asin:
                    totals[item.sku][2] = item.asin
        result.append(
            AggregatedFBA(
                fba_id=fba.fba_id,
                destination_fc=fba.destination_fc,
                items=tuple(
                    AggregatedSkuQty(
                        sku=sku,
                        quantity=totals[sku][0],
                        product_name=totals[sku][1],
                        asin=totals[sku][2],
                    )
                    for sku in order
                ),
            )
        )
    return tuple(result)
