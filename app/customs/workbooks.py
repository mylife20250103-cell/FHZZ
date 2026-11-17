"""货代模板识别、只读明细提取及局部写入验证。"""
from __future__ import annotations

import shutil
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

import olefile
import xlrd
from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter

from app.customs.models import CARRIERS, FIELDS, Invoice, InvoiceLine, Product
from app.customs.rules import text


PROFILES = {
    "MC": (".xlsx", "模板", 17, (8, 7, 11, 12), ("模板", "渠道列表", "地址库")),
    "KYD": (".xls", "模板", 29, (4, 3, 13, 10), ("模板", "服务", "地址库")),
    "HP": (".xls", "单票下单-填写表", 18, (3, 2, 13, 11), ("单票下单-填写表",)),
}
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS = {"s": MAIN_NS}


def _header(value):
    return "".join(text(value).split()).rstrip("*＊")


def detect_invoice(path: Path) -> Invoice:
    """用真实格式及各货代表头识别，不根据文件名选适配器。"""
    path = Path(path)
    with path.open('rb') as stream:
        signature = stream.read(8)
    actual_extension = '.xls' if signature == bytes.fromhex('d0cf11e0a1b11ae1') else '.xlsx' if signature.startswith(b'PK\x03\x04') else ''
    if not actual_extension or path.suffix.lower() != actual_extension:
        raise ValueError(f"{path.name}：真实文件格式与扩展名不一致或格式不受支持；请勿直接改后缀")
    found, errors = [], []
    for carrier, profile in PROFILES.items():
        if profile[0] != actual_extension:
            continue
        try:
            found.append(read_invoice(path, carrier))
        except ValueError as exc:
            errors.append(f"{CARRIERS[carrier]}：{exc}")
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise ValueError(f"{path.name}同时匹配多个货代模板，不能自动处理")
    raise ValueError(f"{path.name}：未识别到完整可用的货代模板。" + '；'.join(errors))


def read_invoice(path: Path, carrier: str) -> Invoice:
    path = Path(path)
    if carrier not in PROFILES:
        raise ValueError("不支持的货代")
    extension, sheet, header_row, columns, required = PROFILES[carrier]
    if path.suffix.lower() != extension:
        raise ValueError(f"{path.name}：当前选择的是{CARRIERS[carrier]}（{extension}），与文件格式不符。"
                         "快越达使用.xls，迈创使用.xlsx；请切换正确物流商或选择“自动识别”，不要改后缀或用Excel另存")
    wb = None
    try:
        if extension == ".xlsx":
            wb = load_workbook(path, read_only=True, data_only=False)
            names = wb.sheetnames
            if not all(n in names for n in required):
                raise ValueError("缺少货代模板工作表")
            ws = wb[sheet]
            grid = [list(row) for row in ws.iter_rows()]
            values = [[c.value for c in row] for row in grid]
            formulas = {(r + 1, c + 1) for r, row in enumerate(grid) for c, cell in enumerate(row) if cell.data_type in ("f", "e")}
        else:
            if carrier == "KYD":
                with olefile.OleFileIO(path, write_mode=False) as storage:
                    if any("CompObj" in name for stream in storage.listdir() for name in stream):
                        raise ValueError("含CompObj另存标记，快越达无法可靠识别图片，请重新生成合并文件")
            wb = xlrd.open_workbook(str(path), on_demand=True)
            names = wb.sheet_names()
            if not all(n in names for n in required):
                raise ValueError("缺少货代模板工作表")
            ws = wb.sheet_by_name(sheet)
            values = [ws.row_values(r) for r in range(ws.nrows)]
            cell_errors = {(r + 1, c) for r in range(ws.nrows) for c in columns
                           if c <= ws.ncols and ws.cell_type(r, c - 1) == xlrd.XL_CELL_ERROR}
            from app.customs.xls_patch import workbook_bytes
            from app.services import kyd_xls_io as biff
            data = workbook_bytes(path)
            start, end = biff.sheet_span_by_name(data, sheet)
            formulas = {(struct.unpack_from("<H", p)[0] + 1, struct.unpack_from("<H", p, 2)[0] + 1)
                        for pos, rec, ln, p in biff.iter_biff(data) if start <= pos < end and rec == biff.REC_FORMULA}
            formulas |= cell_errors
        if "_SystemMeta" in names or "_MergeMeta" in names:
            raise ValueError("检测到源发票元数据，请选择已合并的最终发票输出")
        if len(values) < header_row:
            raise ValueError("缺少产品表头")
        headers = [_header(v) for v in values[header_row - 1]]
        for field, col in zip(FIELDS, columns):
            if headers.count(field) != 1 or headers.index(field) != col - 1:
                raise ValueError(f"{field}表头缺失、重复或位置不符，请核对模板版本")
        lines = []
        for row, vals in enumerate(values[header_row:], header_row + 1):
            product = tuple(text(vals[c - 1]) if len(vals) >= c else "" for c in columns)
            if not any(product):
                continue
            if any((row, c) in formulas for c in columns):
                raise ValueError(f"第{row}行目标字段含公式或错误值，不能直接覆盖")
            if not product[0]:
                raise ValueError(f"第{row}行缺少产品中文品名，不能确定匹配对象")
            lines.append(InvoiceLine(row, product))
        return Invoice(path, carrier, sheet, columns, tuple(lines))
    except Exception as exc:
        raise ValueError(f"{path.name}：{exc}") from exc
    finally:
        if wb is not None:
            if extension == ".xlsx":
                wb.close()
            else:
                wb.release_resources()


def _sheet_member(z: ZipFile, sheet: str) -> str:
    workbook = ET.fromstring(z.read("xl/workbook.xml"))
    sheet_node = next(s for s in workbook.findall("s:sheets/s:sheet", NS) if s.get("name") == sheet)
    rid = sheet_node.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = next(r.get("Target") for r in rels if r.get("Id") == rid)
    import posixpath
    member = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
    if not member.startswith("xl/") or ".." in member.split("/"):
        raise ValueError("工作表关联路径异常")
    return member


def _patch_xlsx(source: Path, dest: Path, sheet: str, updates: dict[str, str]):
    # 仅替换目标 cell 片段，保留完整原XML，包括未知命名空间和校验扩展。
    # XML解析负责定位/验证，字节片段替换避免重新序列化整个工作表。
    import html
    import re
    with ZipFile(source) as original:
        member = _sheet_member(original, sheet)
        raw = original.read(member)
        node = ET.fromstring(raw)
        cells = {c.get("r"): c for c in node.findall("s:sheetData/s:row/s:c", NS)}
        for address, value in updates.items():
            cell = cells.get(address)
            if cell is not None and any(child.tag not in (f"{{{MAIN_NS}}}v", f"{{{MAIN_NS}}}is") for child in cell):
                raise ValueError(f"{address}为公式或含未知单元格结构，停止修改")
            pattern = rb'<(?P<tag>(?:[A-Za-z_][\w.-]*:)?c)\b(?P<attrs>[^>]*\br=["\x27]' + address.encode() + rb'["\x27][^>]*?)(?:/>|>.*?</(?P=tag)>)'
            matches = list(re.finditer(pattern, raw, flags=re.DOTALL))
            if len(matches) > 1:
                raise ValueError(f"无法唯一定位{address}的XML单元格")
            match = matches[0] if matches else None
            if match is None:
                row_number = re.search(r'\d+$', address).group()
                row_pattern = rb'<(?P<tag>(?:[A-Za-z_][\w.-]*:)?row)\b[^>]*\br=["\x27]' + row_number.encode() + rb'["\x27][^>]*>.*?</(?P=tag)>'
                row_matches = list(re.finditer(row_pattern, raw, flags=re.DOTALL))
                if len(row_matches) != 1:
                    raise ValueError(f"无法定位{address}所在的产品行")
                row_match = row_matches[0]
                tag = row_match.group("tag")[:-3] + b'c'
                attrs = b' r="' + address.encode() + b'"'
                from openpyxl.utils.cell import column_index_from_string
                target_col = column_index_from_string(re.sub(r'\d+', '', address))
                row_cells = list(re.finditer(rb'<(?:[A-Za-z_][\w.-]*:)?c\b[^>]*\br=["\x27]([A-Z]+)\d+["\x27][^>]*?(?:/>|>.*?</(?:[A-Za-z_][\w.-]*:)?c>)', row_match.group(), re.DOTALL))
                following = [m for m in row_cells if column_index_from_string(m.group(1).decode()) > target_col]
                insertion = row_match.start() + (following[0].start() if following else row_cells[-1].end() if row_cells else row_match.group().index(b'>') + 1)
                a = b = insertion
            else:
                tag = match.group("tag")
                attrs = re.sub(rb'\s+t=["\x27][^"\x27]*["\x27]', b"", match.group("attrs"))
                a, b = match.start(), match.end()
            prefix = tag[:-1]
            escaped = html.escape(value, quote=False).encode("utf-8")
            replacement = (b"<" + tag + attrs + b' t="inlineStr"><' + prefix + b'is><' + prefix +
                           b't xml:space="preserve">' + escaped + b"</" + prefix + b't></' + prefix + b'is></' + tag + b">")
            raw = raw[:a] + replacement + raw[b:]
        ET.fromstring(raw)
        with ZipFile(dest, "w") as output:
            output.comment = original.comment
            for info in original.infolist():
                output.writestr(info, raw if info.filename == member else original.read(info.filename))


def _without_targets(raw: bytes, addresses: set[str]) -> bytes:
    root = ET.fromstring(raw)
    for row in root.findall("s:sheetData/s:row", NS):
        for cell in list(row):
            if cell.get("r") in addresses:
                row.remove(cell)
    return ET.tostring(root)


def write_invoice(source: Path, dest: Path, invoice: Invoice, changes: dict[int, Product]) -> None:
    if source.resolve() == dest.resolve() or dest.exists():
        raise ValueError("必须写入尚不存在的副本路径")
    valid_rows = {line.row for line in invoice.lines}
    if not set(changes) <= valid_rows or any(len(v) != 4 or not all(v) for v in changes.values()):
        raise ValueError("修改内容不属于预览中的完整产品行")
    updates = {(r, c): v for r, vals in changes.items() for c, v in zip(invoice.columns, vals)}
    if source.suffix.lower() == ".xlsx":
        addresses = {f"{get_column_letter(c)}{r}": v for (r, c), v in updates.items()}
        _patch_xlsx(source, dest, invoice.sheet, addresses)
        with ZipFile(source) as a, ZipFile(dest) as b:
            member = _sheet_member(a, invoice.sheet)
            if a.namelist() != b.namelist():
                raise ValueError("XLSX内部文件清单变化")
            for name in a.namelist():
                left, right = a.read(name), b.read(name)
                if name == member:
                    original_cells = {c.get("r"): c for c in ET.fromstring(left).findall("s:sheetData/s:row/s:c", NS)}
                    revised_cells = {c.get("r"): c for c in ET.fromstring(right).findall("s:sheetData/s:row/s:c", NS)}
                    for address in addresses:
                        old = original_cells.get(address)
                        expected_attrs = {k: v for k, v in old.attrib.items() if k != "t"} if old is not None else {"r": address}
                        if {k: v for k, v in revised_cells[address].attrib.items() if k != "t"} != expected_attrs:
                            raise ValueError(f"目标单元格样式或属性变化：{address}")
                    left = _without_targets(left, set(addresses))
                    right = _without_targets(right, set(addresses))
                if left != right:
                    raise ValueError(f"非目标内容变化：{name}")
    else:
        from app.customs.xls_patch import patch_xls, semantic_records
        shutil.copyfile(source, dest)
        patch_xls(dest, invoice.sheet, updates)
        with olefile.OleFileIO(source) as a, olefile.OleFileIO(dest) as b:
            if a.listdir() != b.listdir():
                raise ValueError("OLE流清单变化")
            for stream in a.listdir():
                if stream != ["Workbook"] and a.openstream(stream).read() != b.openstream(stream).read():
                    raise ValueError(f"非目标OLE流变化：{stream}")
        if semantic_records(source, invoice.sheet, set(updates)) != semantic_records(dest, invoice.sheet, set(updates)):
            raise ValueError("非目标BIFF记录变化，停止发布")
    actual = read_invoice(dest, invoice.carrier)
    expected = {line.row: changes.get(line.row, line.values) for line in invoice.lines}
    if {line.row: line.values for line in actual.lines} != expected:
        raise ValueError("四项字段回读或其他产品行校验失败")
