from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass, field
from datetime import datetime
import json
import urllib.error
import urllib.request
from pathlib import Path

from app.invoice_config import FORWARDER_API_INI


@dataclass(frozen=True)
class NextslsConfig:
    provider_id: str
    name: str
    gateway: str
    token: str
    carrier_code: str


@dataclass(frozen=True)
class NextslsHit:
    fba_id: str
    tracking_number: str
    shipment_id: str
    status_text: str


class NextslsError(Exception):
    pass


STATUS_ZH = {
    "in_transit": "转运中",
    "delivered": "已签收",
    "draft": "草稿",
    "cancelled": "已取消",
    "exception": "异常",
    "pending": "待处理",
    "pickup": "已揽收",
}
COUNTRY_ZH = {
    "US": "美国",
    "GB": "英国",
    "DE": "德国",
    "JP": "日本",
    "CA": "加拿大",
    "AU": "澳大利亚",
    "FR": "法国",
    "IT": "意大利",
    "ES": "西班牙",
    "MX": "墨西哥",
}
TAXWITH_ZH = {0: "不包税", 1: "部分包税", 2: "包税"}
EXPORTWITH_ZH = {0: "", 1: "买单报关"}


@dataclass(frozen=True)
class ShipmentTrace:
    time_text: str
    info: str
    location: str


@dataclass(frozen=True)
class ShipmentParcelRow:
    carton_no: str
    client_weight: str
    picking: str
    declared_value: str
    status_text: str


@dataclass(frozen=True)
class ShipmentDetail:
    title: str
    service_name: str
    service_code: str
    country: str
    chargeable_weight: str
    status_text: str
    actual_weight: str
    volume_weight: str
    dim_factor: str
    volume: str
    parcel_count: str
    recipient: str
    po_number: str
    export_mode: str
    tax_mode: str
    currency: str
    ext_number: str
    product_name: str
    traces: tuple[ShipmentTrace, ...]
    parcels: tuple[ShipmentParcelRow, ...]


def load_nextsls_providers(path=None) -> tuple[NextslsConfig, ...]:
    ini_path = Path(path) if path is not None else FORWARDER_API_INI
    if not ini_path.exists():
        return ()
    parser = ConfigParser()
    parser.read(ini_path, encoding="utf-8-sig")
    found: list[NextslsConfig] = []
    for section in parser.sections():
        if not section.upper().startswith("NEXTSLS."):
            continue
        gateway = parser.get(section, "Gateway", fallback="").strip().rstrip("/")
        token = parser.get(section, "Token", fallback="").strip()
        if not gateway or not token:
            continue
        provider_id = section.split(".", 1)[-1].strip().upper()
        found.append(
            NextslsConfig(
                provider_id=provider_id,
                name=parser.get(section, "Name", fallback=provider_id).strip()
                or provider_id,
                gateway=gateway,
                token=token,
                carrier_code=parser.get(
                    section, "CarrierCode", fallback=""
                ).strip().upper(),
            )
        )
    return tuple(found)


def providers_grouped_by_carrier(
    path=None,
) -> dict[str, tuple[NextslsConfig, ...]]:
    grouped: dict[str, list[NextslsConfig]] = {}
    for item in load_nextsls_providers(path):
        if not item.carrier_code:
            continue
        grouped.setdefault(item.carrier_code, []).append(item)
    return {code: tuple(items) for code, items in grouped.items()}


def providers_by_carrier(path=None) -> dict[str, NextslsConfig]:
    """每个货代取第一个账号。多家下单账号请用 providers_grouped_by_carrier。"""

    return {
        code: items[0]
        for code, items in providers_grouped_by_carrier(path).items()
    }


def normalize_provider_map(
    providers: list[NextslsConfig]
    | dict[str, NextslsConfig | tuple[NextslsConfig, ...] | list[NextslsConfig]]
    | None = None,
    path=None,
) -> dict[str, tuple[NextslsConfig, ...]]:
    if providers is None:
        return providers_grouped_by_carrier(path)
    if isinstance(providers, dict):
        result: dict[str, tuple[NextslsConfig, ...]] = {}
        for key, value in providers.items():
            code = str(key or "").strip().upper()
            if not code:
                continue
            if isinstance(value, NextslsConfig):
                result[code] = (value,)
            else:
                result[code] = tuple(value)
        return result
    grouped: dict[str, list[NextslsConfig]] = {}
    for item in providers:
        if item.carrier_code:
            grouped.setdefault(item.carrier_code, []).append(item)
    return {code: tuple(items) for code, items in grouped.items()}


def prefer_account(
    configs: tuple[NextslsConfig, ...],
    source: str = "",
) -> tuple[NextslsConfig, ...]:
    wanted = (source or "").strip().lower()
    if not wanted or wanted == "manual":
        return configs
    preferred = [item for item in configs if item.provider_id.lower() == wanted]
    rest = [item for item in configs if item.provider_id.lower() != wanted]
    return tuple(preferred + rest)


def prefer_accounts_for_hint(
    configs: tuple[NextslsConfig, ...],
    hint: str = "",
    source: str = "",
) -> tuple[NextslsConfig, ...]:
    """上次命中的账号优先，再用文件名候选（迈创寻麓 → 寻麓者）排序。"""

    ordered = list(prefer_account(configs, source))
    text = (hint or "").strip()
    if not text or not ordered:
        return tuple(ordered)
    head: list[NextslsConfig] = []
    wanted = (source or "").strip().lower()
    if wanted and wanted != "manual" and ordered[0].provider_id.lower() == wanted:
        head.append(ordered.pop(0))
    ordered.sort(key=lambda item: -_account_hint_score(item, text))
    return tuple(head + ordered)


def _account_hint_score(config: NextslsConfig, hint: str) -> int:
    text = (hint or "").strip()
    if not text:
        return 0
    hay = f"{config.name}{config.provider_id}"
    if text in config.name:
        return 100
    core = text
    for prefix in ("迈创合德", "迈创", "快越达", "皓鹏", "利合"):
        core = core.replace(prefix, "")
    core = core.replace("-", "").strip()
    if len(core) < 2:
        return 0
    score = 0
    if core in hay:
        score += 40 + len(core)
    for size in range(len(core), 1, -1):
        if core[:size] in hay:
            score += size
            break
    return score


def query_by_fba(fba_id: str, config: NextslsConfig) -> NextslsHit | None:
    """用 FBA 查货代运单号。一票多单时用轨迹/转单号，并核对箱号是否含该 FBA。"""

    key = (fba_id or "").strip().upper()
    if not key:
        return None
    ext_payload = _lookup_payload(ext_numbers=key)
    body = _post(config, "/api/v5/shipment/get_info", ext_payload)
    if _usable_shipment(body, key):
        return _hit_from_body(body, key)
    nums = _try_post(config, "/api/v5/shipment/get_tracking_numbers", ext_payload)
    if _usable_shipment(nums, key):
        return _hit_from_body(nums, key)
    track = _try_tracking(config, ext_payload)
    if _usable_shipment(track, key):
        return _hit_from_body(track, key)
    body = _post(
        config,
        "/api/v5/shipment/get_info",
        _lookup_payload(client_reference=key),
    )
    if _usable_shipment(body, key):
        return _hit_from_body(body, key)
    return None


def load_shipment_detail(
    fba_id: str,
    carrier: str,
    *,
    channel_name: str = "",
    source: str = "",
    account_hint: str = "",
    providers: list[NextslsConfig]
    | dict[str, NextslsConfig | tuple[NextslsConfig, ...] | list[NextslsConfig]]
    | None = None,
) -> ShipmentDetail:
    """按确认货代查询运单详情。一家货代多个下单账号时按候选名优先尝试。"""

    key = (fba_id or "").strip().upper()
    code = (carrier or "").strip().upper()
    if not key:
        raise NextslsError("没有 FBA，无法查询详情")
    if not code:
        raise NextslsError("该行没有确认货代，无法查询详情")
    if code.startswith("冲突"):
        raise NextslsError("该 FBA 货代冲突，无法查询详情")
    configs = prefer_accounts_for_hint(
        normalize_provider_map(providers).get(code, ()),
        hint=account_hint,
        source=source,
    )
    if not configs:
        raise NextslsError(f"货代 {code} 尚未配置查询接口")
    last_error: NextslsError | None = None
    error_count = 0
    for config in configs:
        try:
            detail = query_shipment_detail(key, config, channel_name=channel_name)
        except NextslsError as exc:
            last_error = exc
            error_count += 1
            continue
        if detail is not None:
            return detail
    if error_count == len(configs) and last_error is not None:
        raise last_error
    raise NextslsError("货代后台未找到该运单")


def query_by_fba_accounts(
    fba_id: str,
    configs: tuple[NextslsConfig, ...],
) -> tuple[NextslsHit, NextslsConfig] | None:
    last_error: NextslsError | None = None
    error_count = 0
    for config in configs:
        try:
            hit = query_by_fba(fba_id, config)
        except NextslsError as exc:
            last_error = exc
            error_count += 1
            continue
        if hit is not None:
            return hit, config
    if error_count == len(configs) and last_error is not None:
        raise last_error
    return None


def query_shipment_detail(
    fba_id: str,
    config: NextslsConfig,
    *,
    channel_name: str = "",
) -> ShipmentDetail | None:
    key = (fba_id or "").strip().upper()
    if not key:
        return None
    ext_payload = _lookup_payload(ext_numbers=key)
    body = _post(config, "/api/v5/shipment/get_info", ext_payload)
    track = _try_tracking(config, ext_payload)
    nums = _try_post(config, "/api/v5/shipment/get_tracking_numbers", ext_payload)
    if not _usable_shipment(body, key):
        ref_payload = _lookup_payload(client_reference=key)
        body = _post(config, "/api/v5/shipment/get_info", ref_payload)
        if _usable_shipment(body, key):
            extra = _try_tracking(config, ref_payload)
            if _has_shipment(extra):
                track = extra
        elif _usable_shipment(nums, key):
            body = nums
        elif _usable_shipment(track, key):
            body = track
    if not _usable_shipment(body, key):
        return None
    return parse_shipment_detail(
        body,
        track,
        fba_id=key,
        channel_name=channel_name,
    )


def parse_shipment_detail(
    info_body: dict,
    track_body: dict | None = None,
    *,
    fba_id: str = "",
    channel_name: str = "",
) -> ShipmentDetail | None:
    data = (info_body or {}).get("data") or {}
    ship = data.get("shipment") if isinstance(data, dict) else {}
    if not isinstance(ship, dict) or not ship:
        return None
    shipment_id = str(ship.get("shipment_id") or "").strip()
    last_mile = str(ship.get("tracking_number") or "").strip()
    number = last_mile or shipment_id
    if not number:
        return None
    ext = _ext_number(ship, fba_id)
    status_raw = str(ship.get("status") or "").strip()
    to_addr = ship.get("to_address") if isinstance(ship.get("to_address"), dict) else {}
    country_code = str(to_addr.get("country") or "").strip().upper()
    parcels = ship.get("parcels") if isinstance(ship.get("parcels"), list) else []
    product = ""
    if parcels and isinstance(parcels[0], dict):
        declarations = parcels[0].get("declarations") or []
        if declarations and isinstance(declarations[0], dict):
            product = str(
                declarations[0].get("name_zh")
                or declarations[0].get("name_en")
                or ""
            ).strip()
    traces_raw = []
    track_ship = ((track_body or {}).get("data") or {}).get("shipment")
    if isinstance(track_ship, dict):
        traces_raw = track_ship.get("traces") or []
        if not status_raw:
            status_raw = str(track_ship.get("status") or "").strip()
    dim_factor = _dim_factor(parcels, ship.get("volume_weight"))
    currency = ""
    charges = ship.get("charge_list") if isinstance(ship.get("charge_list"), list) else []
    if charges and isinstance(charges[0], dict):
        currency = str(charges[0].get("currency") or "").strip()
    return ShipmentDetail(
        title=f"# {number}" + (f" / {ext}" if ext else ""),
        service_name=(channel_name or "").strip() or str(ship.get("service") or "").strip(),
        service_code=str(ship.get("service") or "").strip(),
        country=COUNTRY_ZH.get(country_code, country_code or "—"),
        chargeable_weight=_num(ship.get("chargeable_weight"), "KG"),
        status_text=STATUS_ZH.get(status_raw, status_raw or "—"),
        actual_weight=_num(ship.get("actual_volume"), "KG"),
        volume_weight=_num(ship.get("volume_weight"), "KG"),
        dim_factor=dim_factor,
        volume=_num(ship.get("volume"), "m³", places=3),
        parcel_count=str(ship.get("parcel_count") or len(parcels) or "—"),
        recipient=_format_address(to_addr),
        po_number=str(ship.get("amazon_ref_id") or "").strip() or "—",
        export_mode=EXPORTWITH_ZH.get(ship.get("exportwith"), str(ship.get("exportwith") or "—")),
        tax_mode=TAXWITH_ZH.get(ship.get("taxwith"), str(ship.get("taxwith") or "—")),
        currency=currency or "—",
        ext_number=ext or "—",
        product_name=product or "—",
        traces=tuple(_parse_traces(traces_raw)),
        parcels=tuple(_parse_parcels(parcels, STATUS_ZH.get(status_raw, status_raw))),
    )


def _lookup_payload(*, ext_numbers: str = "", client_reference: str = "") -> dict:
    return {
        "shipment": {
            "ext_numbers": ext_numbers,
            "client_reference": client_reference,
            "shipment_id": "",
            "tracking_number": "",
            "language": "zh",
        }
    }


def _has_shipment(body: dict | None) -> bool:
    if not isinstance(body, dict) or body.get("status") in (0, "0"):
        return False
    data = body.get("data")
    ship = data.get("shipment") if isinstance(data, dict) else None
    return isinstance(ship, dict) and bool(ship)


def _try_tracking(config: NextslsConfig, payload: dict) -> dict:
    return _try_post(config, "/api/v5/shipment/get_tracking", payload)


def _try_post(config: NextslsConfig, path: str, payload: dict) -> dict:
    try:
        return _post(config, path, payload)
    except NextslsError:
        return {}


def _usable_shipment(body: dict | None, fba_id: str) -> bool:
    if not _has_shipment(body):
        return False
    ship = ((body or {}).get("data") or {}).get("shipment") or {}
    parcels = ship.get("parcels") if isinstance(ship, dict) else None
    if not parcels:
        return True
    return _fba_in_shipment(ship, fba_id)


def _fba_in_shipment(ship: dict, fba_id: str) -> bool:
    key = (fba_id or "").strip().upper()
    if not key or not isinstance(ship, dict):
        return False
    blobs = [
        str(ship.get("shipment_id") or ""),
        str(ship.get("client_reference") or ""),
        _ext_number(ship, ""),
    ]
    for parcel in ship.get("parcels") or []:
        if not isinstance(parcel, dict):
            continue
        blobs.append(str(parcel.get("ext_number") or ""))
        blobs.append(str(parcel.get("item_number") or ""))
    return any(key in item.upper() for item in blobs if item)


def _hit_from_body(body: dict, fba_id: str) -> NextslsHit | None:
    detail = parse_shipment_detail(body, {}, fba_id=fba_id)
    if detail is None:
        return None
    ship = ((body.get("data") or {}).get("shipment") or {})
    number = detail.title.split("/")[0].replace("#", "").strip()
    ext = detail.ext_number if detail.ext_number != "—" else fba_id
    return NextslsHit(
        fba_id=ext,
        tracking_number=number,
        shipment_id=number,
        status_text=str(ship.get("status") or "").strip(),
    )


def _ext_number(ship: dict, fallback: str) -> str:
    parcels = ship.get("parcels") if isinstance(ship.get("parcels"), list) else []
    if parcels and isinstance(parcels[0], dict):
        raw = str(parcels[0].get("ext_number") or "").strip().upper()
        if raw:
            if "U" in raw:
                head, tail = raw.rsplit("U", 1)
                if tail.isdigit():
                    return head
            return raw
    return (fallback or "").strip().upper()


def _format_address(addr: dict) -> str:
    parts = [
        str(addr.get("company") or "").strip(),
        str(addr.get("name") or "").strip(),
        str(addr.get("address_1") or "").strip(),
        str(addr.get("address_2") or "").strip(),
        " ".join(
            part
            for part in (
                str(addr.get("city") or "").strip(),
                str(addr.get("state") or addr.get("state_code") or "").strip(),
                str(addr.get("postcode") or "").strip(),
            )
            if part
        ),
        str(addr.get("country") or "").strip(),
        str(addr.get("tel") or addr.get("mobile") or "").strip(),
    ]
    text = ", ".join(part for part in parts if part)
    return text or "暂无信息"


def _num(value, suffix: str, places: int = 2) -> str:
    if value in (None, ""):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"{value}{suffix}"
    return f"{number:.{places}f}{suffix}"


def _dim_factor(parcels: list, volume_weight) -> str:
    if not parcels or not isinstance(parcels[0], dict):
        return "—"
    try:
        vw = float(volume_weight)
        length = float(parcels[0].get("chargeable_length") or 0)
        width = float(parcels[0].get("chargeable_width") or 0)
        height = float(parcels[0].get("chargeable_height") or 0)
    except (TypeError, ValueError):
        return "—"
    if vw <= 0 or length <= 0:
        return "—"
    return str(int(round(length * width * height / vw)))


def _parse_traces(rows: list) -> list[ShipmentTrace]:
    traces = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        location = ""
        country = str(row.get("country") or "").strip()
        city = str(row.get("city") or "").strip()
        if country or city:
            location = f"[{country}, {city}]" if country and city else f"[{country or city}]"
        traces.append(
            ShipmentTrace(
                time_text=_unix_text(row.get("time")),
                info=str(row.get("info") or "").strip(),
                location=location,
            )
        )
    return traces


def _parse_parcels(rows: list, status_text: str) -> list[ShipmentParcelRow]:
    parcels = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        declared = 0.0
        for item in row.get("declarations") or []:
            if not isinstance(item, dict):
                continue
            try:
                declared += float(item.get("unit_value") or 0) * float(item.get("qty") or 0)
            except (TypeError, ValueError):
                continue
        actual = str(row.get("actual_weight") or "").strip()
        volumetric = ""
        try:
            length = float(row.get("chargeable_length") or 0)
            width = float(row.get("chargeable_width") or 0)
            height = float(row.get("chargeable_height") or 0)
            if length and width and height:
                volumetric = f"{length * width * height / 6000:.2f}"
        except (TypeError, ValueError):
            volumetric = ""
        picking = actual
        if volumetric:
            picking = f"{actual} / {volumetric}"
        parcels.append(
            ShipmentParcelRow(
                carton_no=str(row.get("number") or "").strip(),
                client_weight=f"{row.get('client_weight')}(kg)" if row.get("client_weight") not in (None, "") else "—",
                picking=picking or "—",
                declared_value=f"{declared:.0f}" if declared else "—",
                status_text=status_text or "—",
            )
        )
    return parcels


def _unix_text(value) -> str:
    try:
        stamp = int(value)
    except (TypeError, ValueError):
        return ""
    if stamp <= 0:
        return ""
    return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M:%S")


def _post(config: NextslsConfig, path: str, payload: dict) -> dict:
    label = config.name or config.provider_id
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        config.gateway + path,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Language": "zh-CN",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            raise NextslsError(f"{label}接口 HTTP {exc.code}") from exc
        info = str(body.get("info") or body.get("message") or f"HTTP {exc.code}")
        raise NextslsError(info)
    except urllib.error.URLError as exc:
        raise NextslsError(f"{label}接口连不上：{exc.reason}") from exc
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise NextslsError(f"{label}接口返回不是 JSON") from exc
    if not isinstance(body, dict):
        raise NextslsError(f"{label}接口返回格式不对")
    return body
