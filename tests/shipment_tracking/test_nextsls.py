from __future__ import annotations

import json

from app.shipment_tracking.providers.nextsls import (
    NextslsConfig,
    NextslsError,
    NextslsHit,
    load_nextsls_providers,
    load_shipment_detail,
    parse_shipment_detail,
    prefer_accounts_for_hint,
    providers_by_carrier,
    providers_grouped_by_carrier,
    query_by_fba,
)
from app.shipment_tracking.services.tracking_overlay import (
    load_tracking_overlay,
    upsert_tracking,
)
from app.shipment_tracking.services.tracking_pull import pull_forwarder_tracking


def _config(carrier: str = "KYD") -> NextslsConfig:
    return NextslsConfig(
        provider_id=carrier,
        name="快越达" if carrier == "KYD" else "途鱼科技",
        gateway="http://example.test",
        token="secret",
        carrier_code=carrier,
    )


class _FakeResponse:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_query_by_fba_uses_ext_numbers(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout=20):
        calls.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse(
            {
                "status": 1,
                "data": {
                    "shipment": {
                        "tracking_number": "KYD123",
                        "shipment_id": "S1",
                        "status": "in_transit",
                    }
                },
            }
        )

    monkeypatch.setattr(
        "app.shipment_tracking.providers.nextsls.urllib.request.urlopen",
        fake_urlopen,
    )
    hit = query_by_fba("FBA-A", _config())
    assert hit is not None
    assert hit.tracking_number == "KYD123"
    assert calls[0]["shipment"]["ext_numbers"] == "FBA-A"


def test_kyd_truck_uses_shipment_id_when_no_last_mile(monkeypatch):
    def fake_urlopen(request, timeout=20):
        return _FakeResponse(
            {
                "status": 1,
                "info": "请求成功的完成",
                "data": {
                    "shipment": {
                        "tracking_number": None,
                        "shipment_id": "KYD10382GF",
                        "status": "in_transit",
                        "parcels": [
                            {
                                "tracking_number": "",
                                "ext_number": "FBA19MHDCGMPU000001",
                            }
                        ],
                    }
                },
            }
        )

    monkeypatch.setattr(
        "app.shipment_tracking.providers.nextsls.urllib.request.urlopen",
        fake_urlopen,
    )
    hit = query_by_fba("FBA19MHDCGMP", _config())
    assert hit is not None
    assert hit.tracking_number == "KYD10382GF"
    assert hit.status_text == "in_transit"


def test_query_falls_back_to_client_reference(monkeypatch):
    def fake_urlopen(request, timeout=20):
        body = json.loads(request.data.decode("utf-8"))
        shipment = body["shipment"]
        if shipment.get("ext_numbers"):
            return _FakeResponse({"status": 0, "info": "找不到运单", "data": []})
        return _FakeResponse(
            {
                "status": 1,
                "data": {"shipment": {"tracking_number": "KYD999"}},
            }
        )

    monkeypatch.setattr(
        "app.shipment_tracking.providers.nextsls.urllib.request.urlopen",
        fake_urlopen,
    )
    hit = query_by_fba("FBA-A", _config())
    assert hit is not None
    assert hit.tracking_number == "KYD999"


def test_multiple_shipments_falls_back_to_tracking(monkeypatch):
    def fake_urlopen(request, timeout=20):
        if request.full_url.endswith("get_tracking"):
            return _FakeResponse(
                {
                    "status": 1,
                    "data": {
                        "shipment": {
                            "shipment_id": "MC010251034",
                            "tracking_number": "",
                            "status": "delivered",
                            "traces": [{"info": "已签收", "time": 1}],
                        }
                    },
                }
            )
        return _FakeResponse(
            {
                "status": 0,
                "info": "FBA19HB9N07Z 对应多个运单，请使用系统单号",
                "data": [],
            }
        )

    monkeypatch.setattr(
        "app.shipment_tracking.providers.nextsls.urllib.request.urlopen",
        fake_urlopen,
    )
    hit = query_by_fba("FBA19HB9N07Z", _config("MC"))
    assert hit is not None
    assert hit.tracking_number == "MC010251034"
    from app.shipment_tracking.providers.nextsls import query_shipment_detail

    detail = query_shipment_detail("FBA19HB9N07Z", _config("MC"))
    assert detail is not None
    assert detail.title.startswith("# MC010251034")
    assert detail.status_text == "已签收"
    assert detail.traces[0].info == "已签收"


def test_load_providers_maps_carrier(tmp_path):
    ini = tmp_path / "forwarder_api.ini"
    ini.write_text(
        "\n".join(
            [
                "[NextSLS.MC.TUYU]",
                "Name=迈创-途鱼科技",
                "Gateway=http://tuyu.example",
                "Token=tuyu-token",
                "CarrierCode=MC",
                "",
                "[NextSLS.MC.CHIYI]",
                "Name=迈创-赤蚁",
                "Gateway=http://tuyu.example",
                "Token=chiyi-token",
                "CarrierCode=MC",
                "",
                "[NextSLS.KYD]",
                "Name=快越达-小鲸渔",
                "Gateway=http://kyd.example",
                "Token=kyd-token",
                "CarrierCode=KYD",
            ]
        ),
        encoding="utf-8",
    )
    providers = load_nextsls_providers(ini)
    assert {item.provider_id for item in providers} == {"MC.TUYU", "MC.CHIYI", "KYD"}
    by_carrier = providers_by_carrier(ini)
    grouped = providers_grouped_by_carrier(ini)
    assert "KYD" in by_carrier
    assert "MC" in grouped
    assert "TUYU" not in by_carrier
    assert by_carrier["KYD"].gateway == "http://kyd.example"
    assert [item.provider_id for item in grouped["MC"]] == ["MC.TUYU", "MC.CHIYI"]


def test_pull_routes_by_carrier_and_skips_manual(tmp_path, monkeypatch):
    store = tmp_path / "fba_tracking.json"
    upsert_tracking("FBA-MANUAL", "KEEP", path=store, source="manual")
    used: list[str] = []

    def fake_query(fba_id, config):
        used.append(config.carrier_code)
        if fba_id == "FBA-A":
            return NextslsHit(fba_id, "API-1", "S1", "in_transit")
        return None

    monkeypatch.setattr(
        "app.shipment_tracking.providers.nextsls.query_by_fba",
        fake_query,
    )
    result = pull_forwarder_tracking(
        [
            ("FBA-A", "KYD"),
            ("FBA-MISSING", "KYD"),
            ("FBA-MANUAL", "KYD"),
            ("FBA-OTHER", "MC"),
        ],
        overlay_path=store,
        providers=[_config("KYD")],
    )
    lookup = load_tracking_overlay(store)
    assert result.found == 1
    assert result.missing == 1
    assert result.skipped_manual == 1
    assert result.skipped_no_api == 1
    assert used == ["KYD", "KYD"]
    assert lookup["FBA-A"].tracking_number == "API-1"
    assert lookup["FBA-A"].source == "kyd"
    assert lookup["FBA-MANUAL"].tracking_number == "KEEP"


def test_pull_tries_each_account_for_same_carrier(tmp_path, monkeypatch):
    store = tmp_path / "fba_tracking.json"
    used: list[str] = []
    tuyu = NextslsConfig("MC.TUYU", "途鱼科技", "http://tuyu.test", "t1", "MC")
    chiyi = NextslsConfig("MC.CHIYI", "赤蚁", "http://tuyu.test", "t2", "MC")

    def fake_query(fba_id, config):
        used.append(config.provider_id)
        if config.provider_id == "MC.CHIYI":
            return NextslsHit(fba_id, "MC-99", "S9", "in_transit")
        return None

    monkeypatch.setattr(
        "app.shipment_tracking.providers.nextsls.query_by_fba",
        fake_query,
    )
    result = pull_forwarder_tracking(
        [("FBA-MC", "MC")],
        overlay_path=store,
        providers=[tuyu, chiyi],
    )
    lookup = load_tracking_overlay(store)
    assert result.found == 1
    assert used == ["MC.TUYU", "MC.CHIYI"]
    assert lookup["FBA-MC"].tracking_number == "MC-99"
    assert lookup["FBA-MC"].source == "mc.chiyi"


def test_prefer_xunlu_account_from_filename_hint():
    tuyu = NextslsConfig("MC.TUYU", "迈创-途鱼科技", "http://t.test", "t1", "MC")
    xunlu = NextslsConfig("MC.XUNLUZHE", "迈创-寻麓者", "http://t.test", "t2", "MC")
    ranked = prefer_accounts_for_hint((tuyu, xunlu), hint="迈创寻麓")
    assert ranked[0].provider_id == "MC.XUNLUZHE"


def test_pull_queries_hint_account_first(tmp_path, monkeypatch):
    store = tmp_path / "fba_tracking.json"
    used: list[str] = []
    tuyu = NextslsConfig("MC.TUYU", "迈创-途鱼科技", "http://t.test", "t1", "MC")
    xunlu = NextslsConfig("MC.XUNLUZHE", "迈创-寻麓者", "http://t.test", "t2", "MC")

    def fake_query(fba_id, config):
        used.append(config.provider_id)
        if config.provider_id == "MC.XUNLUZHE":
            return NextslsHit(fba_id, "MC-X", "S1", "delivered")
        return None

    monkeypatch.setattr(
        "app.shipment_tracking.providers.nextsls.query_by_fba",
        fake_query,
    )
    result = pull_forwarder_tracking(
        [("FBA19G251B4H", "MC", "迈创寻麓")],
        overlay_path=store,
        providers=[tuyu, xunlu],
    )
    assert result.found == 1
    assert used[0] == "MC.XUNLUZHE"
    assert load_tracking_overlay(store)["FBA19G251B4H"].tracking_number == "MC-X"


def test_pull_prefers_last_hit_account(tmp_path, monkeypatch):
    store = tmp_path / "fba_tracking.json"
    upsert_tracking("FBA-MC", "OLD", path=store, source="mc.chiyi")
    used: list[str] = []
    tuyu = NextslsConfig("MC.TUYU", "途鱼科技", "http://tuyu.test", "t1", "MC")
    chiyi = NextslsConfig("MC.CHIYI", "赤蚁", "http://tuyu.test", "t2", "MC")

    def fake_query(fba_id, config):
        used.append(config.provider_id)
        return NextslsHit(fba_id, "MC-1", "S1", "in_transit")

    monkeypatch.setattr(
        "app.shipment_tracking.providers.nextsls.query_by_fba",
        fake_query,
    )
    pull_forwarder_tracking(
        [("FBA-MC", "MC")],
        overlay_path=store,
        providers=[tuyu, chiyi],
    )
    assert used[0] == "MC.CHIYI"


def test_parse_shipment_detail_maps_kyd_payload():
    info = {
        "status": 1,
        "data": {
            "shipment": {
                "tracking_number": None,
                "shipment_id": "KYD10382GF",
                "status": "in_transit",
                "service": "US-MXWSD-KP-K18",
                "chargeable_weight": 16,
                "actual_volume": 15.29,
                "volume_weight": 15.05,
                "volume": 0.09,
                "parcel_count": 1,
                "amazon_ref_id": "3GQRUGHT",
                "taxwith": 2,
                "exportwith": 1,
                "to_address": {
                    "company": "AVP1",
                    "name": "AMAZON.COM SERVICES, INC.",
                    "address_1": "550 Oak Ridge Road",
                    "city": "Hazle Township",
                    "state": "PA",
                    "postcode": "18202",
                    "country": "US",
                    "tel": "1234657981",
                },
                "charge_list": [{"currency": "USD"}],
                "parcels": [
                    {
                        "number": "KYD10382GFU001",
                        "ext_number": "FBA19MHDCGMPU000001",
                        "client_weight": 15.3,
                        "actual_weight": 15.29,
                        "chargeable_length": 60,
                        "chargeable_width": 50,
                        "chargeable_height": 30.1,
                        "declarations": [
                            {
                                "name_zh": "钢丝锯",
                                "unit_value": 88,
                                "qty": 2,
                            }
                        ],
                    }
                ],
            }
        },
    }
    track = {
        "status": 1,
        "data": {
            "shipment": {
                "traces": [
                    {
                        "info": "航班已于8-31起飞",
                        "time": 1756695306,
                        "country": "CN",
                        "city": "SHENZHEN",
                    }
                ]
            }
        },
    }
    detail = parse_shipment_detail(
        info, track, fba_id="FBA19MHDCGMP", channel_name="K18美西稳速达-卡派-包税"
    )
    assert detail is not None
    assert detail.title == "# KYD10382GF / FBA19MHDCGMP"
    assert detail.service_name == "K18美西稳速达-卡派-包税"
    assert detail.country == "美国"
    assert detail.status_text == "转运中"
    assert detail.chargeable_weight == "16.00KG"
    assert detail.actual_weight == "15.29KG"
    assert detail.volume_weight == "15.05KG"
    assert detail.dim_factor == "6000"
    assert detail.volume == "0.090m³"
    assert detail.parcel_count == "1"
    assert "AVP1" in detail.recipient
    assert "550 Oak Ridge Road" in detail.recipient
    assert detail.po_number == "3GQRUGHT"
    assert detail.export_mode == "买单报关"
    assert detail.tax_mode == "包税"
    assert detail.currency == "USD"
    assert detail.ext_number == "FBA19MHDCGMP"
    assert detail.product_name == "钢丝锯"
    assert len(detail.traces) == 1
    assert detail.traces[0].info == "航班已于8-31起飞"
    assert detail.traces[0].location == "[CN, SHENZHEN]"
    assert detail.parcels[0].carton_no == "KYD10382GFU001"
    assert detail.parcels[0].declared_value == "176"
    assert detail.parcels[0].status_text == "转运中"


def test_load_shipment_detail_tries_second_account(monkeypatch):
    tuyu = NextslsConfig("MC.TUYU", "途鱼科技", "http://tuyu.test", "t1", "MC")
    chiyi = NextslsConfig("MC.CHIYI", "赤蚁", "http://tuyu.test", "t2", "MC")
    used: list[str] = []

    def fake_urlopen(request, timeout=20):
        token = request.headers.get("Authorization") or request.get_header("Authorization")
        used.append(token)
        if "t2" in token:
            return _FakeResponse(
                {
                    "status": 1,
                    "data": {"shipment": {"shipment_id": "MC88", "status": "in_transit"}},
                }
            )
        return _FakeResponse({"status": 0, "info": "找不到运单", "data": []})

    monkeypatch.setattr(
        "app.shipment_tracking.providers.nextsls.urllib.request.urlopen",
        fake_urlopen,
    )
    detail = load_shipment_detail(
        "FBA-MC",
        "MC",
        providers={"MC": (tuyu, chiyi)},
    )
    assert detail.title.startswith("# MC88")
    assert any("t2" in item for item in used)


def test_load_shipment_detail_requires_configured_carrier():
    try:
        load_shipment_detail("FBA-A", "MC", providers={"KYD": _config()})
    except NextslsError as exc:
        assert "尚未配置" in str(exc)
    else:
        raise AssertionError("expected NextslsError")


def test_query_shipment_detail_calls_tracking(monkeypatch):
    from app.shipment_tracking.providers.nextsls import query_shipment_detail

    paths = []

    def fake_urlopen(request, timeout=20):
        paths.append(request.full_url)
        if request.full_url.endswith("get_info"):
            return _FakeResponse(
                {
                    "status": 1,
                    "data": {
                        "shipment": {
                            "shipment_id": "KYD10382GF",
                            "status": "in_transit",
                        }
                    },
                }
            )
        return _FakeResponse(
            {
                "status": 1,
                "data": {
                    "shipment": {
                        "traces": [
                            {"info": "已下单", "time": 1, "country": "CN", "city": "GUANGZHOU"}
                        ]
                    }
                },
            }
        )

    monkeypatch.setattr(
        "app.shipment_tracking.providers.nextsls.urllib.request.urlopen",
        fake_urlopen,
    )
    detail = query_shipment_detail("FBA19MHDCGMP", _config())
    assert detail is not None
    assert detail.traces[0].info == "已下单"
    assert any(path.endswith("get_tracking") for path in paths)
