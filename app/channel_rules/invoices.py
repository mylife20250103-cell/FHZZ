"""只读模板头部和目的仓库；在新副本局部修改服务格。"""
from __future__ import annotations

import re
import shutil
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

import olefile
import xlrd
from openpyxl import load_workbook
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string, range_boundaries

from app.channel_rules.models import InvoiceHead
from app.channel_rules.rules import country_code, text
from app.customs.models import FIELDS
from app.customs.workbooks import PROFILES, _patch_xlsx, _sheet_member, _without_targets

CHANNEL_CELLS = {'MC': ('B2', 'B3'), 'KYD': ('B4', 'B5'), 'HP': ('B1', 'B2')}


def load_countries(path: Path) -> dict[str, dict[str, str]]:
    layouts = {'MC': ('迈创地址库', 1, 12), 'KYD': ('快越达地址库', 0, 11), 'HP': ('皓鹏地址库', 0, 12)}
    result = {}
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        for carrier, (name, code_col, country_col) in layouts.items():
            if name not in book.sheetnames:
                continue
            rows = book[name].iter_rows(max_col=country_col + 1, values_only=True)
            header = next(rows, ())
            if len(header) <= country_col or '地址编码' not in text(header[code_col]) or '国家' not in text(header[country_col]):
                raise ValueError(f'{name}缺少地址编码或国家表头')
            found = {}
            for row in rows:
                wh, country = text(row[code_col]).upper(), country_code(row[country_col])
                if not wh:
                    continue
                if len(country) != 2 or not country.isascii() or not country.isalpha() or country == 'EU':
                    country = ''
                found.setdefault(wh, set()).add(country)
            result[carrier] = {wh: next(iter(items)) if len(items) == 1 else '' for wh, items in found.items()}
    finally:
        book.close()
    return result


def cell_position(address: str, extension: str) -> tuple[int, int]:
    address = text(address).upper()
    if not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]*', address):
        raise ValueError('目标单元格必须是完整地址，例如B2')
    column, row = coordinate_from_string(address)
    col = column_index_from_string(column)
    max_row, max_col = (65536, 256) if extension == '.xls' else (1048576, 16384)
    if row > max_row or col > max_col:
        raise ValueError('目标单元格超出文件格式范围')
    return row, col


def read_head(path: Path, countries: dict, manual_cell: str = '') -> InvoiceHead:
    path = Path(path)
    with path.open('rb') as stream:
        magic = stream.read(8)
    extension = '.xls' if magic == bytes.fromhex('d0cf11e0a1b11ae1') else '.xlsx' if magic.startswith(b'PK\x03\x04') else ''
    if not extension or path.suffix.lower() != extension:
        raise ValueError(f'{path.name}真实格式与后缀不一致或不受支持')
    book = load_workbook(path, read_only=True, data_only=False) if extension == '.xlsx' else xlrd.open_workbook(str(path), on_demand=True, formatting_info=True)
    try:
        names = book.sheetnames if extension == '.xlsx' else book.sheet_names()
        if any(name in names for name in ('_SystemMeta', '_MergeMeta')):
            raise ValueError('检测到源发票元数据，请选择已合并或修订后的上传发票')
        found = []
        for carrier, profile in PROFILES.items():
            ext, sheet, header_row, columns, required = profile
            if ext != extension or not all(name in names for name in required):
                continue
            if extension == '.xlsx':
                ws = book[sheet]
                headers = next(ws.iter_rows(min_row=header_row, max_row=header_row, max_col=20, values_only=True), ())
            else:
                ws = book.sheet_by_name(sheet)
                headers = ws.row_values(header_row - 1) if ws.nrows >= header_row else ()
            clean = [''.join(text(v).split()).rstrip('*＊') for v in headers]
            if all(clean.count(field) == 1 and clean.index(field) == c - 1 for field, c in zip(FIELDS, columns)):
                found.append((carrier, ws, header_row, columns))
        if len(found) != 1:
            raise ValueError(f'{path.name}未能唯一识别货代模板，请核对模板版本')
        carrier, ws, header_row, columns = found[0]
        if carrier == 'KYD':
            with olefile.OleFileIO(path) as storage:
                if any('CompObj' in part for parts in storage.listdir() for part in parts):
                    raise ValueError('快越达文件含Excel另存标记，请重新生成')
        cell = text(manual_cell).upper() or CHANNEL_CELLS[carrier][0]
        rr, cc = cell_position(cell, extension)
        if rr >= header_row:
            raise ValueError('目标必须是表头区域的服务格，不能覆盖产品明细')
        if extension == '.xlsx':
            with ZipFile(path) as zipped:
                xml = ET.fromstring(zipped.read(_sheet_member(zipped, PROFILES[carrier][1])))
            merges = [range_boundaries(node.get('ref')) for node in xml.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}mergeCell')]
        else:
            merges = [(c0 + 1, r0 + 1, c1, r1) for r0, r1, c0, c1 in ws.merged_cells]
        if any(c0 <= cc <= c1 and r0 <= rr <= r1 and (rr, cc) != (r0, c0) for c0, r0, c1, r1 in merges):
            raise ValueError('目标是合并单元格的非首格，请选择合并区域左上角')

        def value(r, c):
            if extension == '.xlsx':
                return ws.cell(r, c).value
            return ws.cell_value(r - 1, c - 1) if r <= ws.nrows and c <= ws.ncols else None

        labels = [text(value(rr, c)) for c in range(max(1, cc - 3), cc)]
        nearest = next((v for v in reversed(labels) if v), '')
        normalized_label = re.sub(r'[\s*＊（）()/]', '', nearest)
        if normalized_label not in ('服务', '渠道', '服务渠道', '服务名称', '运输服务', '渠道名称'):
            raise ValueError(f'{cell}左侧没有服务或渠道标签，请核对目标位置')
        if extension == '.xlsx':
            if ws.cell(rr, cc).data_type in ('f', 'e'):
                raise ValueError('服务目标为公式或错误值，不能覆盖')
        else:
            if rr <= ws.nrows and cc <= ws.ncols and ws.cell_type(rr - 1, cc - 1) == xlrd.XL_CELL_ERROR:
                raise ValueError('服务目标为错误值，不能覆盖')
            from app.customs.xls_patch import workbook_bytes
            from app.services import kyd_xls_io as biff
            raw = workbook_bytes(path)
            start, end = biff.sheet_span_by_name(raw, ws.name)
            if any(start <= p < end and rec == biff.REC_FORMULA and struct.unpack_from('<HH', payload) == (rr - 1, cc - 1)
                   for p, rec, _, payload in biff.iter_biff(raw)):
                raise ValueError('服务目标为公式，不能覆盖')
        wr, wc = cell_position(CHANNEL_CELLS[carrier][1], extension)
        warehouse = text(value(wr, wc)).upper()
        country = countries.get(carrier, {}).get(warehouse, '')
        if not warehouse or not country:
            raise ValueError(f'{path.name}：中央地址库缺少仓库{warehouse}的唯一国家，请先维护地址库')
        # 模板含直接填写的国家时交叉核验；公式地址仍以中央地址库为准。
        for r in range(1, header_row):
            label = text(value(r, 1)).rstrip('*＊')
            direct = text(value(r, 2))
            if label == '国家' and direct and not direct.startswith('=') and country_code(direct) != country:
                raise ValueError(f'{path.name}：发票国家与中央仓库国家不一致')
        cn_col = columns[0]
        if extension == '.xlsx':
            has_products = any(text(row[0]) for row in ws.iter_rows(min_row=header_row + 1, min_col=cn_col, max_col=cn_col, values_only=True))
        else:
            has_products = any(text(value(r, cn_col)) for r in range(header_row + 1, ws.nrows + 1))
        return InvoiceHead(path.resolve(), path.name, carrier, country, warehouse, PROFILES[carrier][1], cell, text(value(rr, cc)), has_products)
    finally:
        if extension == '.xlsx':
            book.close()
        else:
            book.release_resources()


def valid_service_text(value: str):
    if not isinstance(value, str) or not value.strip() or len(value) > 32767 or value.startswith(('=', '+', '-', '@')) or re.search(r'[\x00-\x08\x0b-\x1f]', value):
        raise ValueError('服务填写值为空、过长或包含不安全字符')


def write_channel(source: Path, dest: Path, head: InvoiceHead, new_value: str) -> None:
    valid_service_text(new_value)
    if source.resolve() == dest.resolve() or dest.exists():
        raise ValueError('必须写入尚不存在的副本路径')
    r, c = cell_position(head.cell, source.suffix.lower())
    if source.suffix.lower() == '.xlsx':
        _patch_xlsx(source, dest, head.sheet, {head.cell: new_value})
        with ZipFile(source) as left, ZipFile(dest) as right:
            if left.namelist() != right.namelist():
                raise ValueError('XLSX文件清单变化')
            member = _sheet_member(left, head.sheet)
            for name in left.namelist():
                a, b = left.read(name), right.read(name)
                if name == member:
                    a, b = _without_targets(a, {head.cell}), _without_targets(b, {head.cell})
                if a != b:
                    raise ValueError('非目标XML或模板内容变化，停止发布')
        book = load_workbook(dest, read_only=True, data_only=False)
        try:
            actual = book[head.sheet][head.cell].value
        finally:
            book.close()
    else:
        from app.customs.xls_patch import patch_xls, semantic_records
        shutil.copyfile(source, dest)
        patch_xls(dest, head.sheet, {(r, c): new_value})
        with olefile.OleFileIO(source) as left, olefile.OleFileIO(dest) as right:
            if left.listdir() != right.listdir():
                raise ValueError('OLE流清单变化')
            for stream in left.listdir():
                if stream != ['Workbook'] and left.openstream(stream).read() != right.openstream(stream).read():
                    raise ValueError('非目标OLE流变化')
        if semantic_records(source, head.sheet, {(r, c)}) != semantic_records(dest, head.sheet, {(r, c)}):
            raise ValueError('非目标BIFF记录变化')
        book = xlrd.open_workbook(str(dest), on_demand=True)
        try:
            actual = book.sheet_by_name(head.sheet).cell_value(r - 1, c - 1)
        finally:
            book.release_resources()
    if actual != new_value:
        raise ValueError('服务格回读校验失败，停止发布')
