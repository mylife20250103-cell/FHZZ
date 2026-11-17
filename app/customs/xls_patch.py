"""在副本上局部修改 BIFF 文本；不通过 Excel 另存或重建工作簿。"""
from __future__ import annotations

import struct
from pathlib import Path

import olefile
import xlrd


def workbook_bytes(path: Path) -> bytes:
    with olefile.OleFileIO(path, write_mode=False) as ole:
        return ole.openstream("Workbook").read()


def patch_xls(path: Path, sheet: str, updates: dict[tuple[int, int], str]) -> None:
    # 复用现有经过上传修复的字符串/偏移处理，不调用其读写权限的读取函数。
    from app.services import kyd_xls_io as biff

    wb = xlrd.open_workbook(str(path), formatting_info=True, on_demand=True)
    try:
        strings = list(wb._sharedstrings or [])
    finally:
        wb.release_resources()
    book = workbook_bytes(path)
    records = list(biff.iter_biff(book))
    start, end = biff.sheet_span_by_name(book, sheet)
    pending = {(r - 1, c - 1): value for (r, c), value in updates.items()}
    added = []
    inserted_count = 0
    edits = []
    for pos, rec, ln, payload in records:
        if not start <= pos < end or rec not in biff.CELL_RECS or len(payload) < 4:
            continue
        rr, cc = struct.unpack_from("<HH", payload)
        multi = rec in (biff.REC_MULBLANK, 0x00BD)
        last = struct.unpack_from("<H", payload, len(payload) - 2)[0] if multi else cc
        if not any((rr, c) in pending for c in range(cc, last + 1)):
            continue
        if rec == biff.REC_FORMULA:
            raise ValueError("目标字段为公式，不能覆盖")
        replacement = bytearray()
        for offset, c in enumerate(range(cc, last + 1)):
            if rec == biff.REC_MULBLANK:
                xf = struct.unpack_from("<H", payload, 4 + offset * 2)[0]
                old = biff.pack_blank(rr, c, xf)
            elif rec == 0x00BD:
                xf, rk = struct.unpack_from("<HI", payload, 4 + offset * 6)
                old = biff.rec_bytes(0x027E, struct.pack("<HHHI", rr, c, xf, rk))
            else:
                xf = struct.unpack_from("<H", payload, 4)[0]
                old = book[pos:pos + 4 + ln]
            if (rr, c) in pending:
                value = pending.pop((rr, c))
                index = biff.sst_index(strings, value, added)
                replacement.extend(biff.pack_labelsst(rr, c, xf, index))
                inserted_count += rec != biff.REC_LABELSST
            else:
                replacement.extend(old)
        edits.append((pos, pos + 4 + ln, bytes(replacement)))
    if pending:
        raise ValueError("目标单元格不存在，不能安全写入")
    sst_start, sst_end, sst = biff._sst_span(book)
    temp = bytearray(book)
    biff._append_sst_strings(temp, added, struct.unpack_from("<I", sst)[0] + inserted_count)
    extra_size = len(temp) - len(book)
    edits.append((sst_start + 4, sst_start + 12, bytes(temp[sst_start + 4:sst_start + 12])))
    if extra_size:
        edits.append((sst_end, sst_end, bytes(temp[sst_end:sst_end + extra_size])))
    from app.customs.sst_index import ext_sst_payload
    ext_payload = ext_sst_payload(temp)
    for pos, rec, ln, payload in records:
        if rec == 0xFF:
            if pos < sst_end:
                raise ValueError("EXTSST顺序异常，不能安全写入")
            edits.append((pos, pos + 4 + ln, biff.rec_bytes(0xFF, ext_payload)))
    edits.sort()

    def moved(offset):
        return offset + sum(len(new) - (b - a) for a, b, new in edits if b <= offset)

    result = bytearray()
    cursor = 0
    for a, b, replacement in edits:
        result.extend(book[cursor:a])
        result.extend(replacement)
        cursor = b
    result.extend(book[cursor:])
    # 逐个迁移原文件指针，不假定每32个ROW的行号连续；皓鹏辅助表有稀疏行。
    for pos, rec, ln, payload in records:
        out = moved(pos)
        if rec == biff.REC_BOUNDSHEET:
            pointer = struct.unpack_from("<I", payload)[0]
            struct.pack_into("<I", result, out + 4, moved(pointer))
        elif rec == biff.REC_INDEX:
            for at in range(16, ln, 4):
                pointer = struct.unpack_from("<I", payload, at)[0]
                if pointer:
                    struct.pack_into("<I", result, out + 4 + at, moved(pointer))
        elif rec == biff.REC_DBCELL:
            first_row = pos - struct.unpack_from("<I", payload)[0]
            struct.pack_into("<I", result, out + 4, out - moved(first_row))
            anchor = first_row + biff.ROW_RECORD_SIZE
            for at in range(4, ln, 2):
                distance = struct.unpack_from("<H", payload, at)[0]
                target = anchor + distance
                new_distance = moved(target) - moved(anchor)
                if not 0 <= new_distance <= 65535:
                    raise ValueError("行块偏移超出BIFF范围，不能安全写入")
                struct.pack_into("<H", result, out + 4 + at, new_distance)
                anchor = target
    try:
        biff.write_workbook_stream(path, bytes(result))
    finally:
        # 旧写入函数内部额外CoInitialize；只在本调用处平衡，不改变既有服务。
        biff.pythoncom.CoUninitialize()


def semantic_records(path: Path, sheet: str, changed: set[tuple[int, int]]) -> tuple:
    """忽略允许变化的字符串池/索引，逐记录比较图片、公式及其他内容。"""
    from app.services import kyd_xls_io as biff

    data = workbook_bytes(path)
    start, end = biff.sheet_span_by_name(data, sheet)
    result = []
    skip_continue = False
    for pos, rec, ln, payload in biff.iter_biff(data):
        if rec == biff.REC_SST:
            skip_continue = True
            continue
        if rec == biff.REC_CONTINUE and skip_continue:
            continue
        skip_continue = False
        if rec in (biff.REC_INDEX, biff.REC_DBCELL, 0xFF):
            continue
        if rec == biff.REC_BOUNDSHEET:
            result.append((rec, payload[4:]))
            continue
        if start <= pos < end and rec in biff.CELL_RECS:
            rr, cc = struct.unpack_from("<HH", payload)
            if rec in (biff.REC_MULBLANK, 0x00BD):
                last = struct.unpack_from("<H", payload, len(payload) - 2)[0]
                for offset, col in enumerate(range(cc, last + 1)):
                    if (rr + 1, col + 1) in changed:
                        continue
                    if rec == biff.REC_MULBLANK:
                        xf = struct.unpack_from("<H", payload, 4 + 2 * offset)[0]
                        result.append((biff.REC_BLANK, struct.pack("<HHH", rr, col, xf)))
                    else:
                        xf, rk = struct.unpack_from("<HI", payload, 4 + 6 * offset)
                        result.append((0x027E, struct.pack("<HHHI", rr, col, xf, rk)))
                continue
            if (rr + 1, cc + 1) in changed:
                continue
        result.append((rec, payload))
    return tuple(result)
