from app.shipment_tracking.services.carrier_resolve import (
    carrier_code_from_name,
    resolve_carrier,
)


def test_candidate_maichuang_maps_to_mc():
    assert carrier_code_from_name("迈创合德") == "MC"
    assert carrier_code_from_name("迈创") == "MC"
    assert carrier_code_from_name("快越达") == "KYD"
    assert carrier_code_from_name("KYD") == "KYD"
    assert carrier_code_from_name("") == ""


def test_resolve_prefers_confirmed():
    assert resolve_carrier("KYD", "迈创合德") == "KYD"
    assert resolve_carrier("", "迈创合德") == "MC"
    assert resolve_carrier("冲突 KYD/MC", "迈创合德") == ""
