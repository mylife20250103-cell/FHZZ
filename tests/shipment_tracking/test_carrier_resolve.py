from app.shipment_tracking.services.carrier_resolve import (
    carrier_code_from_name,
    resolve_carrier,
)


def test_candidate_maichuang_maps_to_mc():
    assert carrier_code_from_name("迈创合德") == "MC"
    assert carrier_code_from_name("迈创") == "MC"
    assert carrier_code_from_name("快越达") == "KYD"
    assert carrier_code_from_name("KYD") == "KYD"
    assert carrier_code_from_name("皓鹏正班") == "HP"
    assert carrier_code_from_name("皓鹏") == "HP"
    assert carrier_code_from_name("HP") == "HP"
    assert carrier_code_from_name("利合正班") == "LH"
    assert carrier_code_from_name("利合") == "LH"
    assert carrier_code_from_name("LH") == "LH"
    assert carrier_code_from_name("") == ""


def test_resolve_prefers_confirmed():
    assert resolve_carrier("KYD", "迈创合德") == "KYD"
    assert resolve_carrier("", "迈创合德") == "MC"
    assert resolve_carrier("", "皓鹏正班") == "HP"
    assert resolve_carrier("", "利合卡航递延") == "LH"
    assert resolve_carrier("冲突 KYD/MC", "迈创合德") == ""


def test_forwarder_api_name_does_not_need_invoice_config(tmp_path, monkeypatch):
    ini = tmp_path / "forwarder_api.ini"
    ini.write_text(
        "\n".join(
            [
                "[NextSLS.XX]",
                "Name=新货代-测试账号",
                "Gateway=http://example.test",
                "Token=secret",
                "CarrierCode=XX",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.shipment_tracking.services.carrier_resolve.FORWARDER_API_INI",
        ini,
    )
    monkeypatch.setattr(
        "app.shipment_tracking.services.carrier_resolve._FALLBACK_NAMES",
        (("快越达", "KYD"), ("迈创", "MC")),
    )
    assert carrier_code_from_name("新货代正班") == "XX"
    assert carrier_code_from_name("新货代-测试账号") == "XX"
