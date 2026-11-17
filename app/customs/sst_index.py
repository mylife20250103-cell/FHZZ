"""BIFF8 SST字符串位置索引，处理跨CONTINUE的字符、富文本与扩展数据。"""
from __future__ import annotations

import struct


def string_positions(book: bytes | bytearray) -> list[tuple[int, int]]:
    from app.services.kyd_xls_io import iter_biff
    segments = []
    active = False
    for pos, rec, ln, payload in iter_biff(book):
        if rec == 0xFC:
            active = True
        elif active and rec != 0x3C:
            break
        if active:
            segments.append((pos, payload))
    if not segments or len(segments[0][1]) < 8:
        raise ValueError("共享字符串池缺失或损坏")
    count = struct.unpack_from('<I', segments[0][1], 4)[0]
    seg, offset = 0, 8

    def ensure():
        nonlocal seg, offset
        while seg < len(segments) and offset == len(segments[seg][1]):
            seg += 1
            offset = 0
        if seg >= len(segments):
            raise ValueError("共享字符串池超出记录范围")

    def read(size):
        nonlocal offset
        result = bytearray()
        while size:
            ensure()
            n = min(size, len(segments[seg][1]) - offset)
            result.extend(segments[seg][1][offset:offset + n])
            offset += n
            size -= n
        return bytes(result)

    positions = []
    for _ in range(count):
        ensure()
        positions.append((segments[seg][0] + 4 + offset, 4 + offset))
        chars, flags = struct.unpack('<HB', read(3))
        runs = struct.unpack('<H', read(2))[0] if flags & 8 else 0
        extra = struct.unpack('<I', read(4))[0] if flags & 4 else 0
        wide = flags & 1
        while chars:
            if offset == len(segments[seg][1]):
                ensure()
                wide = read(1)[0] & 1  # 字符内容续包首字节指定新的字符宽度
            width = 2 if wide else 1
            available = (len(segments[seg][1]) - offset) // width
            if not available:
                raise ValueError("共享字符串字符跨包边界异常")
            n = min(chars, available)
            read(n * width)
            chars -= n
        read(runs * 4 + extra)
    return positions


def ext_sst_payload(book: bytes | bytearray) -> bytes:
    positions = string_positions(book)
    # MS-XLS 2.4.107；使用当前唯一字符串数重建索引，不沿用模板陈旧指针。
    dsst = max(len(positions) // 128 + 1, 8)
    return struct.pack('<H', dsst) + b''.join(struct.pack('<IHH', pos, cb, 0) for pos, cb in positions[::dsst])
