from app.shipment_tracking.services.tracking_overlay import (
    latest_event_for,
    load_tracking_overlay,
    tracking_for,
    upsert_tracking,
)


def test_upsert_and_load_by_fba(tmp_path):
    store = tmp_path / "fba_tracking.json"
    upsert_tracking("fba-a", " KYD123 ", path=store, source="manual")
    lookup = load_tracking_overlay(store)
    assert tracking_for("FBA-A", lookup) == "KYD123"
    assert tracking_for("FBA-MISSING", lookup) == ""


def test_upsert_keeps_other_fbas(tmp_path):
    store = tmp_path / "fba_tracking.json"
    upsert_tracking("FBA-A", "A1", path=store)
    upsert_tracking("FBA-B", "B2", path=store)
    lookup = load_tracking_overlay(store)
    assert tracking_for("FBA-A", lookup) == "A1"
    assert tracking_for("FBA-B", lookup) == "B2"


def test_upsert_stores_latest_event(tmp_path):
    store = tmp_path / "fba_tracking.json"
    upsert_tracking(
        "FBA-A",
        "MC010261217",
        path=store,
        source="mc",
        latest_event="2026-09-01 15:40:48 已提柜到海外仓，待拆柜",
    )
    lookup = load_tracking_overlay(store)
    assert latest_event_for("FBA-A", lookup) == "2026-09-01 15:40:48 已提柜到海外仓，待拆柜"
    upsert_tracking("FBA-A", "MC010261217", path=store, source="mc")
    lookup = load_tracking_overlay(store)
    assert latest_event_for("FBA-A", lookup) == "2026-09-01 15:40:48 已提柜到海外仓，待拆柜"


def test_missing_file_is_empty(tmp_path):
    assert load_tracking_overlay(tmp_path / "none.json") == {}
