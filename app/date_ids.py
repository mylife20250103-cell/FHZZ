from __future__ import annotations

from datetime import date, datetime, timedelta


def today_date_id() -> str:
    return datetime.now().strftime("%Y%m%d")


def parse_date_id(date_id: str) -> date:
    text = str(date_id or "").strip()
    return datetime.strptime(text, "%Y%m%d").date()


def normalize_date_id_range(
    start_date_id: str,
    end_date_id: str,
) -> tuple[str, str]:
    start = parse_date_id(start_date_id)
    end = parse_date_id(end_date_id)
    if start > end:
        start, end = end, start
    return (
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
    )


def iter_date_ids(
    start_date_id: str,
    end_date_id: str,
) -> list[str]:
    start_id, end_id = normalize_date_id_range(
        start_date_id,
        end_date_id,
    )
    start = parse_date_id(start_id)
    end = parse_date_id(end_id)
    days: list[str] = []
    current = start
    while current <= end:
        days.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return days


def date_id_in_range(
    date_id: str,
    start_date_id: str,
    end_date_id: str,
) -> bool:
    try:
        return date_id in set(
            iter_date_ids(start_date_id, end_date_id)
        )
    except ValueError:
        return False


def format_date_id_range(
    start_date_id: str,
    end_date_id: str,
) -> str:
    start_id, end_id = normalize_date_id_range(
        start_date_id,
        end_date_id,
    )
    if start_id == end_id:
        return start_id
    return f"{start_id} ~ {end_id}"
