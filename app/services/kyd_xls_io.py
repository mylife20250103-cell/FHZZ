from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import stat
import struct
from dataclasses import dataclass
from pathlib import Path

import pythoncom
from win32com.storagecon import (
    STGM_CREATE,
    STGM_DIRECT,
    STGM_READWRITE,
    STGM_SHARE_EXCLUSIVE,
)


def _error(message: str):
    from app.services.invoice_adapters.base import AdapterError

    raise AdapterError(message)


MAX_BIFF = 8224
FILE_ATTRIBUTE_NORMAL = 0x80

REC_BOF = 0x0809
REC_EOF = 0x000A
REC_BOUNDSHEET = 0x0085
REC_SST = 0x00FC
REC_CONTINUE = 0x003C
REC_LABELSST = 0x00FD
REC_NUMBER = 0x0203
REC_BLANK = 0x0201
REC_MULBLANK = 0x00BE
REC_FORMULA = 0x0006
REC_SHRFMLA = 0x04BC
REC_STRING = 0x0207
REC_OBJ = 0x005D
REC_MSODRAWING = 0x00EC
REC_MSODRAWINGGROUP = 0x00EB
REC_INDEX = 0x020B
REC_DBCELL = 0x00D7
REC_ROW = 0x0208

PIC_COL = 18  # S 列，0-based
DATA_START_ROW = 29  # 第 30 行，0-based
LAST_DATA_COL = 19
ROW_RECORD_SIZE = 20  # 4 字节头 + 16 字节 ROW 体
CELL_RECS = {
    REC_LABELSST,
    REC_NUMBER,
    REC_BLANK,
    REC_MULBLANK,
    REC_FORMULA,
    0x0204,  # LABEL
    0x0205,  # BOOLERR
    0x00BD,  # MULRK
    0x027E,  # RK
}


@dataclass
class KydLine:
    cells: list[object]
    image_bytes: bytes | None
    image_kind: str


def iter_biff(data: bytes | bytearray):
    pos = 0
    n = 0
    while pos + 4 <= len(data):
        rec, ln = struct.unpack_from("<HH", data, pos)
        if ln > len(data) - pos - 4:
            break
        payload = bytes(data[pos + 4 : pos + 4 + ln])
        yield pos, rec, ln, payload
        pos += 4 + ln
        n += 1
        if n > 400000:
            break


def rec_bytes(rec: int, payload: bytes) -> bytes:
    return struct.pack("<HH", rec, len(payload)) + payload


def replace_bytes(book: bytearray, start: int, end: int, data: bytes) -> None:
    book[start:end] = data


def make_writable(path: Path) -> None:
    ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_NORMAL)
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def copy_template(template_path: Path, dest: Path) -> None:
    if not template_path.exists():
        raise _error(f"快越达发票模版不存在：{template_path}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        make_writable(dest)
        dest.unlink()

    shutil.copy2(template_path, dest)
    make_writable(dest)


def read_workbook_stream(path: Path) -> bytes:
    pythoncom.CoInitialize()
    stg = pythoncom.StgOpenStorage(
        str(path),
        None,
        STGM_DIRECT | STGM_READWRITE | STGM_SHARE_EXCLUSIVE,
        None,
        0,
    )
    try:
        stream = stg.OpenStream(
            "Workbook",
            None,
            STGM_DIRECT | STGM_READWRITE | STGM_SHARE_EXCLUSIVE,
            0,
        )
        size = stream.Stat()[2]
        stream.Seek(0, 0)
        return stream.Read(size)
    finally:
        stg = None


def write_workbook_stream(path: Path, data: bytes) -> None:
    pythoncom.CoInitialize()
    stg = pythoncom.StgOpenStorage(
        str(path),
        None,
        STGM_DIRECT | STGM_READWRITE | STGM_SHARE_EXCLUSIVE,
        None,
        0,
    )
    try:
        stream = stg.OpenStream(
            "Workbook",
            None,
            STGM_DIRECT | STGM_READWRITE | STGM_SHARE_EXCLUSIVE,
            0,
        )
        stream.SetSize(len(data))
        stream.Seek(0, 0)
        stream.Write(data)
        stream.Commit(0)
        stg.Commit(0)
    finally:
        stg = None


def write_named_stream(path: Path, name: str, data: bytes) -> None:
    pythoncom.CoInitialize()
    stg = pythoncom.StgOpenStorage(
        str(path),
        None,
        STGM_DIRECT | STGM_READWRITE | STGM_SHARE_EXCLUSIVE,
        None,
        0,
    )
    try:
        try:
            stream = stg.OpenStream(
                name,
                None,
                STGM_DIRECT | STGM_READWRITE | STGM_SHARE_EXCLUSIVE,
                0,
            )
        except Exception:
            stream = stg.CreateStream(
                name,
                STGM_DIRECT
                | STGM_READWRITE
                | STGM_SHARE_EXCLUSIVE
                | STGM_CREATE,
                0,
                0,
            )
        stream.SetSize(len(data))
        stream.Seek(0, 0)
        stream.Write(data)
        stream.Commit(0)
        stg.Commit(0)
    finally:
        stg = None


def prepare_kyd_picture(data: bytes, max_bytes: int = 1600) -> bytes:
    """压成快越达能识别的小尺寸渐进 JPEG。

    MSODRAWINGGROUP 首包只有 8224 字节。多箱时若整张图落到 CONTINUE 里，
    快越达会按「补上一张图的尾巴」来拼，多出来的图全部读空。
    """
    from io import BytesIO

    from PIL import Image

    try:
        source = Image.open(BytesIO(data))
    except Exception as exc:
        raise _error(f"无法读取产品图片：{exc}") from exc
    source = source.convert("RGB")
    limit = max(120, int(max_bytes))
    jpeg = b""
    for side, quality in (
        (58, 55),
        (52, 48),
        (46, 42),
        (40, 38),
        (34, 32),
        (28, 28),
        (24, 24),
    ):
        image = source.copy()
        image.thumbnail((side, side), Image.Resampling.LANCZOS)
        out = BytesIO()
        image.save(
            out,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
        )
        jpeg = out.getvalue()
        if 80 <= len(jpeg) <= limit:
            return jpeg
    if len(jpeg) < 80:
        raise _error("产品图片压缩失败")
    return jpeg


def _rebuild_index_dbcell(book: bytearray) -> None:
    """按当前单元格位置重算每张表的 INDEX / DBCELL 文件指针。"""
    bofs = sheet_bof_positions(book)
    if len(bofs) < 2:
        return
    sheet_starts = bofs[1:]
    for index, start in enumerate(sheet_starts):
        end = sheet_starts[index + 1] if index + 1 < len(sheet_starts) else len(book)
        index_pos = None
        index_ln = 0
        dbcell_pos: list[int] = []
        rows: dict[int, int] = {}
        first_cell: dict[int, int] = {}
        for pos, rec, ln, payload in iter_biff(book):
            if pos < start or pos >= end:
                continue
            if rec == REC_INDEX:
                index_pos = pos
                index_ln = ln
            elif rec == REC_DBCELL:
                dbcell_pos.append(pos)
            elif rec == REC_ROW and ln >= 2:
                row = struct.unpack_from("<H", payload, 0)[0]
                rows[row] = pos
            elif rec in CELL_RECS and ln >= 2:
                row = struct.unpack_from("<H", payload, 0)[0]
                first_cell[row] = min(pos, first_cell.get(row, pos))
        if index_pos is None or not dbcell_pos:
            continue
        reserved, rw_mic, rw_mac, reserved2 = struct.unpack_from(
            "<IIII", book, index_pos + 4
        )
        pointers = bytearray()
        for block_i, db_pos in enumerate(dbcell_pos):
            block_start = rw_mic + block_i * 32
            db_ln = struct.unpack_from("<H", book, db_pos + 2)[0]
            n_rows = (db_ln - 4) // 2
            block_rows = list(range(block_start, block_start + n_rows))
            if not block_rows or block_rows[0] not in rows:
                raise _error("DBCELL 找不到对应 ROW 记录")
            first_row_pos = rows[block_rows[0]]
            db_rtrw = db_pos - first_row_pos
            rg: list[int] = []
            prev = None
            for offset, row in enumerate(block_rows):
                cell = first_cell.get(row)
                if offset == 0:
                    rg.append(
                        (cell - (first_row_pos + ROW_RECORD_SIZE)) if cell is not None else 0
                    )
                    prev = cell
                    continue
                if cell is None or prev is None:
                    rg.append(0)
                else:
                    rg.append(cell - prev)
                if cell is not None:
                    prev = cell
            packed = struct.pack("<I", db_rtrw & 0xFFFFFFFF)
            packed += b"".join(
                struct.pack("<H", max(0, min(value, 0xFFFF))) for value in rg
            )
            if len(packed) != db_ln:
                raise _error("DBCELL 长度与行块不一致")
            book[db_pos + 4 : db_pos + 4 + db_ln] = packed
            pointers.extend(struct.pack("<I", db_pos))
        new_index = struct.pack("<IIII", reserved, rw_mic, rw_mac, reserved2) + pointers
        if len(new_index) != index_ln:
            raise _error("INDEX 长度与 DBCELL 数量不一致")
        book[index_pos + 4 : index_pos + 4 + index_ln] = new_index


def _grow_sheet_drawing_container(
    book: bytearray,
    start: int,
    end: int,
    extra_bytes: int,
    extra_shapes: int,
    last_spid: int,
) -> None:
    """把新插入的浮动图算进工作表 DgContainer / SpgrContainer 长度。"""
    if extra_bytes <= 0 or extra_shapes <= 0:
        return
    for pos, rec, ln, payload in iter_biff(book):
        if pos < start or pos >= end:
            continue
        if rec != REC_MSODRAWING or ln < 32:
            continue
        typ = struct.unpack_from("<H", payload, 2)[0]
        if typ != 0xF002:
            continue
        f002_ln = struct.unpack_from("<I", payload, 4)[0]
        f008_typ = struct.unpack_from("<H", payload, 10)[0]
        f003_typ = struct.unpack_from("<H", payload, 26)[0]
        if f008_typ != 0xF008 or f003_typ != 0xF003:
            raise _error("模板工作表绘图容器结构异常")
        book[pos + 8 : pos + 12] = struct.pack("<I", f002_ln + extra_bytes)
        csp, spid_cur = struct.unpack_from("<II", payload, 16)
        book[pos + 20 : pos + 28] = struct.pack(
            "<II",
            csp + extra_shapes,
            max(spid_cur, last_spid),
        )
        f003_ln = struct.unpack_from("<I", payload, 28)[0]
        book[pos + 32 : pos + 36] = struct.pack("<I", f003_ln + extra_bytes)
        return
    raise _error("模板工作表缺少绘图容器")


def sheet_bof_positions(book: bytes | bytearray) -> list[int]:
    return [pos for pos, rec, ln, payload in iter_biff(book) if rec == REC_BOF]


def template_sheet_span(book: bytes | bytearray) -> tuple[int, int]:
    bofs = sheet_bof_positions(book)
    if len(bofs) < 3:
        raise _error("快越达模版缺少工作表")
    return bofs[1], bofs[2]


def _decode_boundsheet_name(payload: bytes) -> str:
    if len(payload) < 2:
        return ""
    count = payload[0]
    flags = payload[1]
    if flags & 0x01:
        return payload[2 : 2 + count * 2].decode("utf-16le", errors="replace")
    return payload[2 : 2 + count].decode("latin-1", errors="replace")


def sheet_span_by_name(book: bytes | bytearray, sheet_name: str) -> tuple[int, int]:
    if not sheet_name or sheet_name == "模板":
        return template_sheet_span(book)

    bofs = sheet_bof_positions(book)
    sheet_bofs = bofs[1:]
    names = [
        _decode_boundsheet_name(payload[6:])
        for _pos, rec, ln, payload in iter_biff(book)
        if rec == REC_BOUNDSHEET and ln >= 8
    ]
    if sheet_name not in names:
        raise _error(f"找不到工作表【{sheet_name}】")
    index = names.index(sheet_name)
    if index >= len(sheet_bofs):
        raise _error(f"工作表【{sheet_name}】位置异常")
    start = sheet_bofs[index]
    end = sheet_bofs[index + 1] if index + 1 < len(sheet_bofs) else len(book)
    return start, end


def update_boundsheet_offsets(book: bytearray) -> None:
    bofs = sheet_bof_positions(book)
    sheet_bofs = bofs[1:]
    bounds = [
        pos
        for pos, rec, ln, payload in iter_biff(book)
        if rec == REC_BOUNDSHEET
    ]
    if len(bounds) != len(sheet_bofs):
        raise _error("BOUNDSHEET 与工作表数量不一致")
    for pos, offset in zip(bounds, sheet_bofs):
        book[pos + 4 : pos + 8] = struct.pack("<I", offset)


def _sst_span(book: bytes | bytearray) -> tuple[int, int, bytes]:
    start = None
    end = None
    payload = bytearray()
    started = False
    for pos, rec, ln, body in iter_biff(book):
        if rec == REC_SST:
            start = pos
            started = True
            payload.extend(body)
            end = pos + 4 + ln
            continue
        if started and rec == REC_CONTINUE:
            payload.extend(body)
            end = pos + 4 + ln
            continue
        if started:
            break
    if start is None or end is None:
        raise _error("快越达模版缺少 SST")
    return start, end, bytes(payload)


def _encode_sst_string(text: str) -> bytes:
    raw = text.encode("utf-16le")
    cch = len(raw) // 2
    return struct.pack("<HB", cch, 0x01) + raw


def sst_index(strings: list[str], text: str, added: list[str]) -> int:
    value = "" if text is None else str(text)
    try:
        return strings.index(value)
    except ValueError:
        strings.append(value)
        added.append(value)
        return len(strings) - 1


def pack_labelsst(row: int, col: int, xf: int, index: int) -> bytes:
    return rec_bytes(REC_LABELSST, struct.pack("<HHHI", row, col, xf, index))


def pack_number(row: int, col: int, xf: int, value: float) -> bytes:
    return rec_bytes(REC_NUMBER, struct.pack("<HHHd", row, col, xf, float(value)))


def pack_blank(row: int, col: int, xf: int) -> bytes:
    return rec_bytes(REC_BLANK, struct.pack("<HHH", row, col, xf))


def pack_string_cache(text: str) -> bytes:
    raw = text.encode("utf-16le")
    payload = struct.pack("<HB", len(raw) // 2, 0x01) + raw
    return rec_bytes(REC_STRING, payload)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _cell_records(
    row: int,
    col: int,
    xf: int,
    value,
    strings: list[str],
    added: list[str],
    total_holder: list[int],
) -> bytes:
    if value is None or value == "":
        return pack_blank(row, col, xf)
    if _is_number(value):
        return pack_number(row, col, xf, float(value))
    idx = sst_index(strings, str(value).strip() if col == 0 else str(value), added)
    total_holder[0] += 1
    return pack_labelsst(row, col, xf, idx)


def parse_mulblank(payload: bytes) -> tuple[int, int, int, list[int]]:
    row, first = struct.unpack_from("<HH", payload, 0)
    last = struct.unpack_from("<H", payload, len(payload) - 2)[0]
    xfs = [
        struct.unpack_from("<H", payload, 4 + index * 2)[0]
        for index in range(last - first + 1)
    ]
    return row, first, last, xfs


def pack_mulblank(row: int, first: int, last: int, xfs: list[int]) -> bytes:
    if last < first or not xfs:
        return b""
    if len(xfs) != last - first + 1:
        raise _error("MULBLANK 样式数量不一致")
    if first == last:
        return pack_blank(row, first, xfs[0])
    payload = struct.pack("<HH", row, first)
    payload += b"".join(struct.pack("<H", xf) for xf in xfs)
    payload += struct.pack("<H", last)
    return rec_bytes(REC_MULBLANK, payload)


def _records_in_row(book: bytes | bytearray, start: int, end: int, row: int):
    found = []
    for pos, rec, ln, payload in iter_biff(book):
        if pos < start or pos >= end:
            continue
        if rec in (
            REC_MULBLANK,
            REC_LABELSST,
            REC_NUMBER,
            REC_BLANK,
            REC_FORMULA,
        ) and len(payload) >= 4:
            rec_row = struct.unpack_from("<H", payload, 0)[0]
            if rec_row == row:
                found.append((pos, rec, ln, payload))
    return found


def _xf_map(records) -> dict[int, int]:
    mapping = {}
    for pos, rec, ln, payload in records:
        if rec == REC_MULBLANK:
            row, first, last, xfs = parse_mulblank(payload)
            for col, xf in zip(range(first, last + 1), xfs):
                mapping[col] = xf
        elif rec in (REC_LABELSST, REC_NUMBER, REC_BLANK, REC_FORMULA):
            row, col, xf = struct.unpack_from("<HHH", payload, 0)
            mapping[col] = xf
    return mapping


def _pack_art(typ: int, body: bytes, *, ver: int = 0, inst: int = 0) -> bytes:
    verinst = ((inst & 0xFFF) << 4) | (ver & 0xF)
    return struct.pack("<HHI", verinst, typ, len(body)) + body


def _build_bse(image: bytes, kind: str) -> bytes:
    uid = hashlib.md5(image).digest()
    if kind == "png":
        blip_type = 6
        rec = 0xF01E
        inst = 1760
    else:
        blip_type = 5
        rec = 0xF01D
        inst = 1130
    blip_body = uid + b"\xff" + image
    blip = _pack_art(rec, blip_body, ver=0, inst=inst)
    bse_head = (
        bytes([blip_type, blip_type])
        + uid
        + b"\xff\x00"
        + struct.pack("<I", len(blip))
        + struct.pack("<I", 1)
        + b"\x00" * 8
    )
    return _pack_art(0xF007, bse_head + blip, ver=2, inst=blip_type)


def _build_pic_drawing(spid: int, blip_id: int, row: int, name: str) -> bytes:
    fsp = struct.pack("<II", spid, 0x0A00)
    name_utf16 = (name + "\x00").encode("utf-16le")
    desc = b"\x00\x00"
    fopt_props = b"".join(
        [
            struct.pack("<HI", 0x007F, 0x00800080),
            struct.pack("<HI", 0x4104, blip_id),
            struct.pack("<HI", 0x01BF, 1114113),
            struct.pack("<HI", 0x01FF, 524288),
            struct.pack("<HI", 0x033F, 1048592),
            struct.pack("<HI", 0x8380, len(name_utf16)),
            struct.pack("<HI", 0x8381, len(desc)),
        ]
    )
    fopt = fopt_props + name_utf16 + desc
    anchor = struct.pack(
        "<9H",
        2,
        PIC_COL,
        315,
        row,
        20,
        PIC_COL,
        720,
        row,
        241,
    )
    inner = (
        _pack_art(0xF00A, fsp, ver=2, inst=75)
        + _pack_art(0xF00B, fopt, ver=3, inst=7)
        + _pack_art(0xF010, anchor)
        + _pack_art(0xF011, b"")
    )
    return _pack_art(0xF004, inner, ver=15, inst=0)


def _build_pic_obj(obj_id: int) -> bytes:
    payload = (
        struct.pack("<HHHHH", 21, 18, 8, obj_id, 0x6011)
        + b"\x00" * 12
        + struct.pack("<HHH", 7, 2, 0xFFFF)
        + struct.pack("<HHH", 8, 2, 0)
        + struct.pack("<HH", 0, 0)
    )
    return rec_bytes(REC_OBJ, payload)


def _walk_art(payload: bytes, handler) -> None:
    pos = 0
    while pos + 8 <= len(payload):
        verinst, typ, ln = struct.unpack_from("<HHI", payload, pos)
        ver = verinst & 0xF
        body = payload[pos + 8 : pos + 8 + min(ln, len(payload) - pos - 8)]
        handler(typ, body)
        if ver == 15:
            _walk_art(body, handler)
        pos += 8 + ln


def _collect_drawing_group(book: bytes | bytearray) -> tuple[int, int, bytes]:
    start = None
    end = None
    payload = bytearray()
    started = False
    for pos, rec, ln, body in iter_biff(book):
        if rec == REC_MSODRAWINGGROUP:
            start = pos
            started = True
            payload.extend(body)
            end = pos + 4 + ln
            continue
        if started and rec == REC_CONTINUE:
            payload.extend(body)
            end = pos + 4 + ln
            continue
        if started:
            break
    if start is None or end is None:
        raise _error("快越达模版缺少 MSODRAWINGGROUP")
    return start, end, bytes(payload)


def _split_big_record(rec: int, payload: bytes) -> bytes:
    out = bytearray()
    first = True
    pos = 0
    while pos < len(payload) or first:
        chunk = payload[pos : pos + MAX_BIFF]
        out.extend(rec_bytes(rec if first else REC_CONTINUE, chunk))
        pos += len(chunk)
        first = False
        if not chunk:
            break
    return bytes(out)


def _max_shape_ids(book: bytes | bytearray) -> tuple[int, int]:
    max_obj = 0
    max_spid = 0

    def on_art(typ, body):
        nonlocal max_spid
        if typ == 0xF00A and len(body) >= 4:
            max_spid = max(max_spid, struct.unpack_from("<I", body, 0)[0])

    for pos, rec, ln, payload in iter_biff(book):
        if rec == REC_OBJ and ln >= 8:
            _ft, _cb, _ot, oid = struct.unpack_from("<HHHH", payload, 0)
            max_obj = max(max_obj, oid)
        if rec == REC_MSODRAWING:
            _walk_art(payload, on_art)
    return max_obj, max_spid


def _insert_blips(
    dg: bytes,
    images: list[tuple[bytes, str]],
    extra_shapes: int | None = None,
) -> bytes:
    if dg[:8][2:4] != b"\x00\xf0" and struct.unpack_from("<H", dg, 2)[0] != 0xF000:
        # 正常 F000 在开头
        pass
    verinst, typ, ln = struct.unpack_from("<HHI", dg, 0)
    if typ != 0xF000:
        raise _error("MSODRAWINGGROUP 结构异常")
    inner = bytearray(dg[8 : 8 + ln])
    children = []
    pos = 0
    while pos + 8 <= len(inner):
        cvi, ctyp, cln = struct.unpack_from("<HHI", inner, pos)
        children.append((ctyp, bytes(inner[pos : pos + 8 + cln])))
        pos += 8 + cln

    f006 = None
    f00b = None
    f001_existing = None
    others = []
    for ctyp, rec in children:
        if ctyp == 0xF006:
            f006 = rec
        elif ctyp == 0xF00B:
            f00b = rec
        elif ctyp == 0xF001:
            f001_existing = rec
        else:
            others.append(rec)

    if f006 is None:
        raise _error("MSODRAWINGGROUP 缺少 FDGG")

    bses = [_build_bse(image, kind) for image, kind in images]
    existing_body = b""
    existing_count = 0
    if f001_existing:
        _vi, _t, eln = struct.unpack_from("<HHI", f001_existing, 0)
        existing_body = f001_existing[8 : 8 + eln]
        existing_count = (_vi >> 4) & 0xFFF

    store_body = existing_body + b"".join(bses)
    count = existing_count + len(bses)
    f001 = _pack_art(0xF001, store_body, ver=15, inst=count)

    f006_body = bytearray(f006[8:])
    spid_max, cidcl, csp, cdg = struct.unpack_from("<IIII", f006_body, 0)
    csp += extra_shapes if extra_shapes is not None else len(images)
    struct.pack_into("<I", f006_body, 8, csp)
    f006 = _pack_art(0xF006, bytes(f006_body), ver=0, inst=0)

    new_inner = f006 + f001 + (f00b or b"") + b"".join(others)
    return _pack_art(0xF000, new_inner, ver=15, inst=0)


def _sheet_eof(book: bytes | bytearray, start: int, end: int) -> int:
    last = None
    for pos, rec, ln, payload in iter_biff(book):
        if pos < start or pos >= end:
            continue
        if rec == REC_EOF:
            last = pos
    if last is None:
        raise _error("模板工作表缺少 EOF")
    return last


def _patch_formula_cache(
    book: bytearray,
    start: int,
    end: int,
    row: int,
    col: int,
    number: float | None = None,
    text: str | None = None,
) -> None:
    for pos, rec, ln, payload in iter_biff(book):
        if pos < start or pos >= end:
            continue
        if rec != REC_FORMULA:
            continue
        rec_row, rec_col, xf = struct.unpack_from("<HHH", payload, 0)
        if rec_row != row or rec_col != col:
            continue
        if number is not None:
            book[pos + 4 + 6 : pos + 4 + 14] = struct.pack("<d", float(number))
            return
        if text is None:
            return
        book[pos + 4 + 6 : pos + 4 + 14] = b"\x00\x00\x00\x00\x00\x00\xff\xff"
        nxt = pos + 4 + ln
        if nxt + 4 <= len(book):
            nrec, nln = struct.unpack_from("<HH", book, nxt)
            if nrec == REC_STRING:
                new_str = pack_string_cache(text)
                replace_bytes(book, nxt, nxt + 4 + nln, new_str)
                return
        new_str = pack_string_cache(text)
        replace_bytes(book, nxt, nxt, new_str)
        return
    raise _error(f"找不到公式单元格 r{row + 1}c{col + 1}")


def _set_labelsst(
    book: bytearray,
    start: int,
    end: int,
    row: int,
    col: int,
    index: int,
) -> bool:
    """写入 LABELSST。若该格是空白/MULBLANK，则插入新记录。返回是否新增了单元格引用。"""

    for pos, rec, ln, payload in iter_biff(book):
        if pos < start or pos >= end:
            continue
        if rec == REC_LABELSST and ln == 10:
            rec_row, rec_col, xf, _old = struct.unpack("<HHHI", payload)
            if rec_row == row and rec_col == col:
                book[pos + 4 : pos + 14] = struct.pack("<HHHI", row, col, xf, index)
                return False
        if rec == REC_BLANK and ln >= 6:
            rec_row, rec_col, xf = struct.unpack_from("<HHH", payload, 0)
            if rec_row == row and rec_col == col:
                replace_bytes(
                    book,
                    pos,
                    pos + 4 + ln,
                    pack_labelsst(row, col, xf, index),
                )
                return True
        if rec == REC_NUMBER and ln >= 14:
            rec_row, rec_col, xf = struct.unpack_from("<HHH", payload, 0)
            if rec_row == row and rec_col == col:
                replace_bytes(
                    book,
                    pos,
                    pos + 4 + ln,
                    pack_labelsst(row, col, xf, index),
                )
                return True
        if rec == REC_MULBLANK:
            rec_row, first, last, xfs = parse_mulblank(payload)
            if rec_row != row or col < first or col > last:
                continue
            offset = col - first
            xf = xfs[offset]
            left = pack_mulblank(row, first, col - 1, xfs[:offset])
            mid = pack_labelsst(row, col, xf, index)
            right = pack_mulblank(row, col + 1, last, xfs[offset + 1 :])
            replace_bytes(book, pos, pos + 4 + ln, left + mid + right)
            return True
    raise _error(f"找不到文本单元格 r{row + 1}c{col + 1}")


def _set_b26_count(
    book: bytearray,
    start: int,
    end: int,
    count: int,
) -> None:
    records = _records_in_row(book, start, end, 25)
    if not records:
        raise _error("找不到箱数单元格 B26")
    xf_map = _xf_map(records)
    xf = xf_map.get(1, 0)
    last = records[-1]
    last_end = last[0] + 4 + last[2]
    a_end = records[0][0]
    for pos, rec, ln, payload in records:
        rec_col = struct.unpack_from("<H", payload, 2)[0]
        if rec == REC_LABELSST and rec_col == 0:
            a_end = pos + 4 + ln
            continue
        break
    rebuilt = pack_number(25, 1, xf, float(count))
    rest = [
        pack_blank(25, col, xf_map.get(col, xf))
        for col in range(2, LAST_DATA_COL + 1)
    ]
    replace_bytes(book, a_end, last_end, rebuilt + b"".join(rest))


def _fill_data_row(
    book: bytearray,
    start: int,
    end: int,
    row: int,
    values: list[object],
    strings: list[str],
    added: list[str],
    total_holder: list[int],
) -> None:
    records = _records_in_row(book, start, end, row)
    if not records:
        raise _error(f"模板第 {row + 1} 行不存在")
    xf_map = _xf_map(records)
    first = records[0][0]
    last = records[-1]
    last_end = last[0] + 4 + last[2]
    out = bytearray()
    formula_i = None
    for pos, rec, ln, payload in records:
        if rec == REC_FORMULA:
            rec_row, rec_col, xf = struct.unpack_from("<HHH", payload, 0)
            if rec_col == 8:
                formula_i = bytearray(rec_bytes(rec, payload))
    for col in range(0, LAST_DATA_COL + 1):
        xf = xf_map.get(col, 0)
        if col == PIC_COL:
            out.extend(pack_blank(row, col, xf))
            continue
        if col == 8 and formula_i is not None:
            value = values[col] if col < len(values) else None
            # 模板从第 38 行起「总申报」是共享公式。原样写回会拆掉 SHRFMLA，
            # Excel/快越达会把同行海关编码看成空，10 箱时图也可能全部读空。
            # 1–6 箱走的是第 30–35 行，本来就没有这条公式，不受影响。
            if _is_number(value):
                out.extend(pack_number(row, col, xf, float(value)))
            else:
                out.extend(pack_blank(row, col, xf))
            continue
        value = values[col] if col < len(values) else None
        out.extend(
            _cell_records(
                row,
                col,
                xf,
                value,
                strings,
                added,
                total_holder,
            )
        )
    replace_bytes(book, first, last_end, bytes(out))


def _clear_shared_total_formulas(book: bytearray, start: int, end: int) -> None:
    """清掉模板里残留的「总申报」共享公式，避免填过第 38 行后公式定义丢失。"""
    ops: list[tuple[int, int, bytes]] = []
    for pos, rec, ln, payload in iter_biff(book):
        if pos < start or pos >= end:
            continue
        if rec == REC_SHRFMLA:
            ops.append((pos, pos + 4 + ln, b""))
            continue
        if rec == REC_FORMULA and len(payload) >= 6:
            row, col, xf = struct.unpack_from("<HHH", payload, 0)
            if col == 8 and row >= DATA_START_ROW:
                ops.append((pos, pos + 4 + ln, pack_blank(row, col, xf)))
    for pos, end_pos, data in reversed(ops):
        replace_bytes(book, pos, end_pos, data)


def fill_kyd_template(
    dest: Path,
    *,
    channel: str,
    warehouse: str,
    carton_count: int,
    lines: list[KydLine],
) -> None:
    if not lines:
        raise _error("KYD 合并没有明细行")

    from app.services.address_library import lookup_kyd_address

    address = lookup_kyd_address(warehouse)
    import xlrd

    wb = xlrd.open_workbook(str(dest), on_demand=True, formatting_info=True)
    strings = list(wb._sharedstrings or [])
    wb.release_resources()

    book = bytearray(read_workbook_stream(dest))
    _sst_start, _sst_end, sst_payload = _sst_span(book)
    total = struct.unpack_from("<I", sst_payload, 0)[0]
    added: list[str] = []
    total_holder = [total]

    channel_idx = sst_index(strings, channel, added)
    warehouse_idx = sst_index(strings, warehouse, added)

    jpeg_budget = 1600
    if len(lines) > 6:
        jpeg_budget = max(180, 6800 // len(lines) - 90)

    prepared_lines = []
    for line in lines:
        if not line.image_bytes:
            raise _error("产品图片不能为空")
        prepared_lines.append(
            KydLine(
                cells=line.cells,
                image_bytes=prepare_kyd_picture(line.image_bytes, jpeg_budget),
                image_kind="jpeg",
            )
        )
    lines = prepared_lines

    images = []
    image_index_by_key = {}
    for line in lines:
        key = hashlib.md5(line.image_bytes).hexdigest()
        if key not in image_index_by_key:
            image_index_by_key[key] = len(images) + 1
            images.append((line.image_bytes, "jpeg"))

    if images:
        dg_start, dg_end, dg = _collect_drawing_group(book)
        new_dg = _split_big_record(
            REC_MSODRAWINGGROUP,
            _insert_blips(dg, images, extra_shapes=len(lines)),
        )
        replace_bytes(book, dg_start, dg_end, new_dg)

    start, end = template_sheet_span(book)
    if _set_labelsst(book, start, end, 3, 1, channel_idx):
        total_holder[0] += 1
    start, end = template_sheet_span(book)
    if _set_labelsst(book, start, end, 4, 1, warehouse_idx):
        total_holder[0] += 1

    start, end = template_sheet_span(book)
    _patch_formula_cache(book, start, end, 5, 1, text=address.contact or warehouse)
    start, end = template_sheet_span(book)
    _patch_formula_cache(book, start, end, 6, 1, text=address.company)
    start, end = template_sheet_span(book)
    _patch_formula_cache(book, start, end, 7, 1, text=address.address1)
    start, end = template_sheet_span(book)
    _patch_formula_cache(book, start, end, 9, 1, text=address.city)
    start, end = template_sheet_span(book)
    _patch_formula_cache(book, start, end, 10, 1, text=address.state)
    start, end = template_sheet_span(book)
    if address.zip_code is None:
        raise _error(f"地址库 {warehouse} 没有邮编")
    _patch_formula_cache(book, start, end, 11, 1, number=address.zip_code)
    start, end = template_sheet_span(book)
    _patch_formula_cache(book, start, end, 12, 1, text=address.country)
    start, end = template_sheet_span(book)
    if address.phone is not None:
        _patch_formula_cache(book, start, end, 13, 1, number=address.phone)

    start, end = template_sheet_span(book)
    _set_b26_count(book, start, end, carton_count)

    for offset, line in enumerate(lines):
        start, end = template_sheet_span(book)
        _fill_data_row(
            book,
            start,
            end,
            DATA_START_ROW + offset,
            line.cells,
            strings,
            added,
            total_holder,
        )

    start, end = template_sheet_span(book)
    _clear_shared_total_formulas(book, start, end)

    if images:
        start, end = template_sheet_span(book)
        max_obj, max_spid = _max_shape_ids(book)
        pic_records = bytearray()
        dg_start, dg_end, dg = _collect_drawing_group(book)
        _vi, _t, _ln = struct.unpack_from("<HHI", dg, 0)
        # 统计 F001 inst
        inner = dg[8 : 8 + struct.unpack_from("<I", dg, 4)[0]]
        pos = 0
        blip_base = 0
        while pos + 8 <= len(inner):
            cvi, ctyp, cln = struct.unpack_from("<HHI", inner, pos)
            if ctyp == 0xF001:
                blip_base = (cvi >> 4) & 0xFFF
                blip_base -= len(images)
            pos += 8 + cln
        if blip_base < 0:
            blip_base = 0

        extra_draw = 0
        last_spid = max_spid
        for offset, line in enumerate(lines):
            key = hashlib.md5(line.image_bytes).hexdigest()
            local_id = image_index_by_key[key]
            blip_id = blip_base + local_id
            obj_id = max_obj + offset + 1
            spid = max_spid + offset + 1
            last_spid = spid
            image_id = hashlib.md5(line.image_bytes + bytes([offset])).hexdigest().upper()
            name = "ID_" + image_id
            drawing = _build_pic_drawing(spid, blip_id, DATA_START_ROW + offset, name)
            extra_draw += len(drawing)
            pic_records.extend(rec_bytes(REC_MSODRAWING, drawing))
            pic_records.extend(_build_pic_obj(obj_id))

        eof = _sheet_eof(book, start, end)
        replace_bytes(book, eof, eof, bytes(pic_records))
        start, end = template_sheet_span(book)
        _grow_sheet_drawing_container(
            book,
            start,
            end,
            extra_draw,
            len(lines),
            last_spid,
        )

        # 更新 spidMax
        dg_start, dg_end, dg = _collect_drawing_group(book)
        verinst, typ, ln = struct.unpack_from("<HHI", dg, 0)
        inner = bytearray(dg[8 : 8 + ln])
        pos = 0
        while pos + 8 <= len(inner):
            cvi, ctyp, cln = struct.unpack_from("<HHI", inner, pos)
            if ctyp == 0xF006 and cln >= 4:
                spid_max = struct.unpack_from("<I", inner, pos + 8)[0]
                new_max = max(spid_max, max_spid + len(lines) + 1)
                struct.pack_into("<I", inner, pos + 8, new_max)
                break
            pos += 8 + cln
        new_dg = _pack_art(0xF000, bytes(inner), ver=15, inst=0)
        replace_bytes(
            book,
            dg_start,
            dg_end,
            _split_big_record(REC_MSODRAWINGGROUP, new_dg),
        )

    if added or total_holder[0] != total:
        sst_start, sst_end, sst_payload = _sst_span(book)
        orig_total, orig_unique = struct.unpack_from("<II", sst_payload, 0)
        book[sst_start + 4 : sst_start + 8] = struct.pack("<I", total_holder[0])
        book[sst_start + 8 : sst_start + 12] = struct.pack(
            "<I",
            orig_unique + len(added),
        )
        if added:
            extra = bytearray()
            current = b""
            for text in added:
                encoded = _encode_sst_string(text)
                if current and len(current) + len(encoded) > MAX_BIFF:
                    extra.extend(rec_bytes(REC_CONTINUE, current))
                    current = encoded
                else:
                    current += encoded
            if current:
                extra.extend(rec_bytes(REC_CONTINUE, current))
            replace_bytes(book, sst_end, sst_end, bytes(extra))

    _rebuild_index_dbcell(book)
    update_boundsheet_offsets(book)
    write_workbook_stream(dest, bytes(book))


def _append_sst_strings(book: bytearray, added: list[str], new_total: int) -> None:
    if not added and new_total <= 0:
        return
    sst_start, sst_end, sst_payload = _sst_span(book)
    orig_total, orig_unique = struct.unpack_from("<II", sst_payload, 0)
    book[sst_start + 4 : sst_start + 8] = struct.pack(
        "<I",
        new_total if new_total else orig_total,
    )
    book[sst_start + 8 : sst_start + 12] = struct.pack(
        "<I",
        orig_unique + len(added),
    )
    if not added:
        return
    extra = bytearray()
    current = b""
    for text in added:
        encoded = _encode_sst_string(text)
        if current and len(current) + len(encoded) > MAX_BIFF:
            extra.extend(rec_bytes(REC_CONTINUE, current))
            current = encoded
        else:
            current += encoded
    if current:
        extra.extend(rec_bytes(REC_CONTINUE, current))
    replace_bytes(book, sst_end, sst_end, bytes(extra))


def set_kyd_text_cell(
    path: Path,
    sheet_name: str,
    row: int,
    col: int,
    value: str,
) -> None:
    """
    只改 Workbook 流里的一个文本单元格，不经 Excel / WPS。
    用于合并后的快越达 .xls，避免另存出 CompObj 导致上传失败。
    """

    import xlrd

    text = "" if value is None else str(value)
    wb = xlrd.open_workbook(str(path), on_demand=True, formatting_info=True)
    strings = list(wb._sharedstrings or [])
    wb.release_resources()

    book = bytearray(read_workbook_stream(path))
    added: list[str] = []
    index = sst_index(strings, text, added)
    start, end = sheet_span_by_name(book, sheet_name)
    inserted = _set_labelsst(book, start, end, row, col, index)

    if added or inserted:
        _sst_start, _sst_end, sst_payload = _sst_span(book)
        orig_total = struct.unpack_from("<I", sst_payload, 0)[0]
        _append_sst_strings(
            book,
            added,
            orig_total + (1 if inserted else 0),
        )
        _rebuild_index_dbcell(book)
        update_boundsheet_offsets(book)

    write_workbook_stream(path, bytes(book))
