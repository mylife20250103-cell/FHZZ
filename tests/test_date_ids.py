from __future__ import annotations

import pytest

from app.date_ids import (
    date_id_in_range,
    format_date_id_range,
    iter_date_ids,
    normalize_date_id_range,
    parse_date_id,
)


def test_iter_date_ids_inclusive_and_swaps():
    assert iter_date_ids("20260910", "20260911") == [
        "20260910",
        "20260911",
    ]
    assert iter_date_ids("20260911", "20260910") == [
        "20260910",
        "20260911",
    ]
    assert iter_date_ids("20260910", "20260910") == ["20260910"]


def test_normalize_and_format_range():
    assert normalize_date_id_range("20260911", "20260910") == (
        "20260910",
        "20260911",
    )
    assert format_date_id_range("20260910", "20260910") == "20260910"
    assert format_date_id_range("20260911", "20260910") == (
        "20260910 ~ 20260911"
    )


def test_date_id_in_range_and_invalid():
    assert date_id_in_range("20260911", "20260910", "20260912")
    assert not date_id_in_range("20260909", "20260910", "20260912")
    assert not date_id_in_range("bad", "20260910", "20260912")
    with pytest.raises(ValueError):
        parse_date_id("2026-09-10")
