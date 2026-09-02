from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re

from app.invoice_config import is_excel_junk_file

SHIPPING_EXTENSIONS = {".xlsm", ".xlsx"}
SKIP_DIR_NAMES = {"标签"}
MONTH_FOLDER = re.compile(r"^(20\d{2})\.(0?[1-9]|1[0-2])$")
DATE_FOLDER = re.compile(r"^(\d{1,2})\.(\d{1,2})(.*)$")
FILENAME_DATE = re.compile(r"^(\d{2})(\d{2})-")
BATCH_FOLDER = re.compile(r"^([1-9]\d*)$")


@dataclass(frozen=True)
class IndexedShippingFile:
    path: Path
    store_code: str
    year: int | None
    month: int | None
    folder_day: int | None
    ship_date: date | None
    filename_month: int | None
    filename_day: int | None
    batch_no: int
    candidate_forwarder: str | None


def list_store_periods(
    root,
    store_code: str | None = None,
) -> tuple[tuple[int | None, int | None], ...]:
    """店铺下出现过的 (年, 月)，新的在前。store_code 为空则合并全部店铺。不打开 Excel。"""

    seen: set[tuple[int | None, int | None]] = set()
    ordered: list[tuple[int | None, int | None]] = []
    for item in index_shipping_files(root, store_code=store_code):
        key = (item.year, item.month)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    ordered.sort(
        key=lambda pair: (pair[0] is None, -(pair[0] or 0), -(pair[1] or 0))
    )
    return tuple(ordered)


def period_label(year: int | None, month: int | None) -> str:
    if year and month:
        return f"{year}.{month:02d}"
    if month:
        return f"{month}月（无年份）"
    return "未识别月份"


def matches_period(
    item: IndexedShippingFile,
    year: int | None,
    month: int | None,
    *,
    all_periods: bool = False,
) -> bool:
    if all_periods:
        return True
    return item.year == year and item.month == month


def matches_date_range(
    item: IndexedShippingFile,
    start: date,
    end: date,
) -> bool:
    """按发货日期过滤；没有具体日则看整个月份是否和区间重叠。"""

    if start > end:
        start, end = end, start
    if item.ship_date is not None:
        return start <= item.ship_date <= end
    if item.year and item.month:
        month_start = date(item.year, item.month, 1)
        month_end = date(item.year, item.month, monthrange(item.year, item.month)[1])
        return month_start <= end and month_end >= start
    return False


def index_shipping_files(
    root,
    store_code: str | None = None,
) -> tuple[IndexedShippingFile, ...]:
    """
    扫描装箱明细目录树，只索引路径层。
    不打开 Excel、不确认货代、不解析发货规划。
    """

    base = Path(root)
    if not base.exists():
        return ()

    wanted = (store_code or "").strip()
    found: list[IndexedShippingFile] = []
    for store_dir in _iter_dirs(base):
        current_store = store_dir.name
        if wanted and current_store != wanted:
            continue
        for child in _iter_dirs(store_dir):
            month_match = MONTH_FOLDER.fullmatch(child.name)
            if month_match:
                year = int(month_match.group(1))
                month = int(month_match.group(2))
                found.extend(
                    _index_month_dir(child, current_store, year, month)
                )
                continue
            found.extend(
                _index_date_or_files(
                    child,
                    store_code=current_store,
                    year=None,
                    month=None,
                )
            )
        found.extend(
            _collect_files(
                store_dir,
                store_code=current_store,
                year=None,
                month=None,
                folder_day=None,
                batch_no=1,
            )
        )
    return tuple(found)


def list_store_codes(root) -> tuple[str, ...]:

    base = Path(root)
    if not base.exists():
        return ()
    return tuple(child.name for child in _iter_dirs(base))


def _index_month_dir(
    month_dir: Path,
    store_code: str,
    year: int,
    month: int,
) -> list[IndexedShippingFile]:
    found: list[IndexedShippingFile] = []
    for child in _iter_dirs(month_dir):
        found.extend(
            _index_date_or_files(
                child,
                store_code=store_code,
                year=year,
                month=month,
            )
        )
    found.extend(
        _collect_files(
            month_dir,
            store_code=store_code,
            year=year,
            month=month,
            folder_day=None,
            batch_no=1,
        )
    )
    return found


def _index_date_or_files(
    path: Path,
    *,
    store_code: str,
    year: int | None,
    month: int | None,
) -> list[IndexedShippingFile]:
    parsed = _parse_date_folder(path.name)
    if parsed is None:
        return _collect_files(
            path,
            store_code=store_code,
            year=year,
            month=month,
            folder_day=None,
            batch_no=1,
        )
    folder_month, folder_day = parsed
    found: list[IndexedShippingFile] = []
    batch_dirs = [
        child
        for child in _iter_dirs(path)
        if BATCH_FOLDER.fullmatch(child.name)
    ]
    if batch_dirs:
        for child in batch_dirs:
            found.extend(
                _collect_files(
                    child,
                    store_code=store_code,
                    year=year,
                    month=folder_month,
                    folder_day=folder_day,
                    batch_no=int(child.name),
                )
            )
    found.extend(
        _collect_files(
            path,
            store_code=store_code,
            year=year,
            month=folder_month,
            folder_day=folder_day,
            batch_no=1,
        )
    )
    return found


def _collect_files(
    directory: Path,
    *,
    store_code: str,
    year: int | None,
    month: int | None,
    folder_day: int | None,
    batch_no: int,
) -> list[IndexedShippingFile]:
    items = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        if is_excel_junk_file(path):
            continue
        if path.suffix.lower() not in SHIPPING_EXTENSIONS:
            continue
        filename_month, filename_day, candidate = _parse_filename(path.name)
        items.append(
            IndexedShippingFile(
                path=path.resolve(),
                store_code=store_code,
                year=year,
                month=month,
                folder_day=folder_day,
                ship_date=_build_ship_date(year, month, folder_day),
                filename_month=filename_month,
                filename_day=filename_day,
                batch_no=batch_no,
                candidate_forwarder=candidate,
            )
        )
    return items


def _parse_date_folder(name: str) -> tuple[int, int] | None:
    match = DATE_FOLDER.fullmatch(name)
    if not match:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    if month < 1 or month > 12 or day < 1 or day > 31:
        return None
    return month, day


def _parse_filename(
    name: str,
) -> tuple[int | None, int | None, str | None]:
    stem = Path(name).stem
    match = FILENAME_DATE.match(stem)
    filename_month = filename_day = None
    rest = stem
    if match:
        filename_month = int(match.group(1))
        filename_day = int(match.group(2))
        if filename_month < 1 or filename_month > 12:
            filename_month = None
            filename_day = None
        rest = stem[match.end():]
    candidate = None
    if "-" in rest:
        candidate = rest.rsplit("-", 1)[-1].strip() or None
    elif rest.strip():
        candidate = rest.strip()
    return filename_month, filename_day, candidate


def _build_ship_date(
    year: int | None,
    month: int | None,
    day: int | None,
) -> date | None:
    if year is None or month is None or day is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _iter_dirs(path: Path):
    if not path.exists():
        return []
    return sorted(
        child
        for child in path.iterdir()
        if child.is_dir() and child.name not in SKIP_DIR_NAMES
    )
