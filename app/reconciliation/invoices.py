from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook

from app.date_ids import today_date_id
from app.invoice_config import BATCH_ROOT, MERGE_RESULT_ROOT, is_excel_junk_file
from .models import Carton, InvoiceEstimate, ScanResult

NAME = re.compile(r'^(MC|KYD)_([^_]+)_(\d+)箱\.(xlsx|xls)$', re.IGNORECASE)
BOX = re.compile(r'^(FBA[A-Z0-9-]+)U(\d{6})$')
HEADERS = ['货箱重量(KG)', '货箱长度(CM)', '货箱宽度(CM)', '货箱高度(CM)']


def _text(value) -> str:
    return str(value).strip() if value is not None else ''


def _positive(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('重量和尺寸必须为有效数字') from None
    if not result.is_finite() or result <= 0:
        raise ValueError('重量和尺寸必须大于0')
    return result


def _read_rows(path: Path, carrier: str):
    """返回普通值后立即关闭工作簿；从不保存源工作簿。"""
    if carrier == 'MC':
        w = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        try:
            s = w['模板']
            rows = list(s.iter_rows(min_row=17, max_col=6, values_only=True))
            return s['B2'].value, s['B3'].value, s['B16'].value, rows[0], rows[1:]
        finally:
            w.close()
    import xlrd
    w = xlrd.open_workbook(str(path), on_demand=True)
    try:
        s = w.sheet_by_name('模板')
        def row(r):
            return tuple(s.cell_value(r, c) if c < s.ncols else '' for c in range(18))
        return s.cell_value(3,1), s.cell_value(4,1), s.cell_value(25,1), row(28), [row(r) for r in range(29,s.nrows)]
    finally:
        w.release_resources()


def read_invoice(path: Path) -> InvoiceEstimate:
    path = Path(path).resolve()
    carrier = path.name.split('_', 1)[0].upper()
    warehouse, channel, digest = '', '', ''
    issues, cartons = [], {}
    try:
        match = NAME.fullmatch(path.name)
        if not match:
            raise ValueError('文件名应为 MC/KYD_仓库_箱数箱.xlsx/xls')
        carrier, named_warehouse, named_count, extension = match.groups()
        carrier = carrier.upper()
        if extension.lower() != ('xlsx' if carrier == 'MC' else 'xls'):
            raise ValueError('文件扩展名与货代模板不匹配')
        with path.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        channel, warehouse, declared, headers, data = _read_rows(path, carrier)
        channel, warehouse = _text(channel), _text(warehouse).upper()
        if warehouse != named_warehouse.upper():
            issues.append('模板仓库与文件名不一致')
        if not channel:
            issues.append('模板渠道为空')
        weight_col = 2 if carrier == 'MC' else 14
        for col, expected in zip(range(weight_col, weight_col+4), HEADERS):
            if re.sub(r'[\s*]', '', _text(headers[col])).upper() != expected.upper():
                issues.append(f'第{col+1}列表头不符：应为{expected}')
        if '货箱编号' not in _text(headers[0]):
            issues.append('首列表头不是货箱编号')
        start = 18 if carrier == 'MC' else 30
        for row_number, values in enumerate(data, start):
            number = _text(values[0]).upper()
            # 产品行可能省略重复箱号；空箱号不当成一个新箱。
            if not number:
                continue
            box = BOX.fullmatch(number)
            if not box or int(box.group(2)) == 0:
                issues.append(f'第{row_number}行货箱编号无效：{number}')
                continue
            try:
                measurements = tuple(_positive(v) for v in values[weight_col:weight_col+4])
            except ValueError as exc:
                issues.append(f'第{row_number}行 {number}：{exc}')
                continue
            carton = Carton(number, box.group(1), *measurements, row_number)
            old = cartons.get(number)
            if old is not None:
                if (old.weight, old.length, old.width, old.height) != measurements:
                    issues.append(f'同箱重量/尺寸冲突：{number}')
            else:
                cartons[number] = carton
        if not cartons:
            issues.append('没有有效货箱数据')
        try:
            if _positive(declared) != len(cartons) or int(named_count) != len(cartons):
                issues.append('模板/文件名箱数与唯一货箱数量不一致')
        except ValueError:
            issues.append('模板总箱数无效')
    except Exception as exc:
        issues.append(f'文件无法核对：{exc}')
    return InvoiceEstimate(path, carrier, warehouse, channel, tuple(cartons.values()), tuple(issues), digest)


def scan_directory(directory: Path) -> ScanResult:
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f'结果目录不存在：{directory}')
    files = sorted(p for p in directory.rglob('*') if p.is_file()
                   and not is_excel_junk_file(p)
                   and p.suffix.lower() in {'.xls', '.xlsx'}
                   and p.name.upper().startswith(('MC_', 'KYD_')))
    return ScanResult(directory.resolve(), tuple(read_invoice(p) for p in files),
                      datetime.now().isoformat(timespec='seconds'))


def suggest_directory(result_root: Path = MERGE_RESULT_ROOT, batch_root: Path = BATCH_ROOT,
                      date_id: str | None = None) -> Path:
    date_id = date_id or today_date_id()
    today = Path(result_root) / date_id
    candidates = []
    for status_file in (Path(batch_root)/date_id).glob('*/status.json'):
        try:
            state = json.loads(status_file.read_text(encoding='utf-8'))
            folder = today / status_file.parent.name
            if (state.get('Status') in {'CONTENT_MERGED', 'CHECK_PASSED', 'COMPLETED'}
                    and folder.is_dir() and any(NAME.fullmatch(p.name) for p in folder.iterdir())):
                candidates.append((str(state.get('UpdatedAt','')), status_file.parent.name, folder))
        except (OSError, ValueError, AttributeError):
            continue
    return max(candidates)[2] if candidates else today
