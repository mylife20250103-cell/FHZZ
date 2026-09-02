from __future__ import annotations

from dataclasses import dataclass, field

from app.shipment_tracking.providers.nextsls import (
    NextslsConfig,
    NextslsError,
    normalize_provider_map,
    prefer_accounts_for_hint,
    query_by_fba_accounts,
)
from app.shipment_tracking.services.tracking_overlay import (
    load_tracking_overlay,
    upsert_tracking,
)


@dataclass
class TrackingPullResult:
    found: int = 0
    missing: int = 0
    skipped_manual: int = 0
    skipped_no_api: int = 0
    errors: list[str] = field(default_factory=list)


def pull_forwarder_tracking(
    items: list[tuple[str, str] | tuple[str, str, str]],
    *,
    overlay_path=None,
    providers: list[NextslsConfig]
    | dict[str, NextslsConfig | tuple[NextslsConfig, ...] | list[NextslsConfig]]
    | None = None,
) -> TrackingPullResult:
    """
    按确认货代把 FBA 交给对应 NextSLS 账号。
    文件名候选（如 迈创寻麓）优先匹配下单账号；同一次拉取里记住刚命中的账号。
    不覆盖人工登记；没有配置接口的货代跳过。
    """

    result = TrackingPullResult()
    by_carrier = normalize_provider_map(providers)
    if not by_carrier:
        result.errors.append("未配置货代接口（公共配置/forwarder_api.ini）")
        return result
    overlay = load_tracking_overlay(overlay_path)
    seen: set[str] = set()
    sticky: dict[str, str] = {}
    for raw in items:
        fba_id = (raw[0] or "").strip().upper()
        carrier = (raw[1] or "").strip().upper()
        candidate = raw[2].strip() if len(raw) > 2 and raw[2] else ""
        if not fba_id or fba_id in seen:
            continue
        seen.add(fba_id)
        if carrier.startswith("冲突"):
            result.skipped_no_api += 1
            continue
        configs = by_carrier.get(carrier)
        if not configs:
            result.skipped_no_api += 1
            continue
        existing = overlay.get(fba_id)
        if existing and existing.source == "manual":
            result.skipped_manual += 1
            continue
        hint_key = candidate or carrier
        source = (existing.source if existing else "") or sticky.get(hint_key, "")
        try:
            matched = query_by_fba_accounts(
                fba_id,
                prefer_accounts_for_hint(configs, hint=candidate, source=source),
            )
        except NextslsError as exc:
            result.errors.append(f"{fba_id}：{exc}")
            continue
        if matched is None:
            result.missing += 1
            continue
        hit, config = matched
        sticky[hint_key] = config.provider_id.lower()
        upsert_tracking(
            fba_id,
            hit.tracking_number,
            source=config.provider_id.lower(),
            path=overlay_path,
        )
        result.found += 1
    return result
