from datetime import date

from app.shipment_tracking.services.watchlist import (
    WatchItem,
    add_watch_item,
    classify_shipment,
    load_watchlist,
    lookback_range,
    matches_watch_item,
    remove_watch_item,
    watch_result_sort_key,
)


def test_lookback_range_is_sixty_inclusive_days():
    start, end = lookback_range(60, today=date(2026, 9, 17))
    assert start == date(2026, 7, 20)
    assert end == date(2026, 9, 17)
    assert (end - start).days == 59


def test_name_contains_is_case_insensitive():
    item = WatchItem("美8", "盖片")
    assert matches_watch_item("美8", "LS8415-Silver", "硅胶盖片", item)
    assert matches_watch_item("美8", "LS8415-Silver", "盖片", item)
    assert not matches_watch_item("美8", "LS8415-Silver", "锅盖", item)
    assert not matches_watch_item("美3", "LS8415-Silver", "盖片", item)


def test_optional_sku_contains_narrows_match():
    item = WatchItem("美8", "盖片", "LS8415")
    assert matches_watch_item("美8", "LS8415-Silver", "盖片", item)
    assert not matches_watch_item("美8", "GP995-4P", "盖片", item)


def test_classify_shipment_buckets():
    assert classify_shipment("", "") == "无运单"
    assert classify_shipment("KYD123", "转运中 已发运") == "在途"
    assert classify_shipment("KYD123", "2026-09-10 已签收") == "已签收"


def test_watchlist_roundtrip_and_dedupe(tmp_path):
    path = tmp_path / "watchlist.json"
    item, created = add_watch_item("美8", "盖片", path=path)
    assert created is True
    assert item.label() == "美8｜盖片"
    again, created_again = add_watch_item("美8", " 盖片 ", path=path)
    assert created_again is False
    assert again == item
    loaded = load_watchlist(path)
    assert loaded == [item]
    assert remove_watch_item(item, path=path) is True
    assert load_watchlist(path) == []


def test_watch_result_sorts_store_then_name_then_date():
    rows = [
        ("美10", "袋盖", "2026-08-14"),
        ("美8", "盖片", "2026-08-21"),
        ("美8", "盖片", "2026-08-14"),
        ("美8", "袋盖", "2026-08-14"),
        ("EM", "大视野海绵", "2026-08-14"),
    ]
    ordered = sorted(rows, key=lambda item: watch_result_sort_key(*item))
    assert [item[0] for item in ordered] == [
        "EM",
        "美8",
        "美8",
        "美8",
        "美10",
    ]
    assert ordered[1][1] == "盖片"
    assert ordered[1][2] == "2026-08-14"
    assert ordered[2] == ("美8", "盖片", "2026-08-21")
    assert ordered[3][1] == "袋盖"
