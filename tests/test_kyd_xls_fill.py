from __future__ import annotations

from app.invoice_config import KYD_TEMPLATE_PATH
from app.services.invoice_adapters.kyd_adapter import KydAdapter
from app.services.kyd_xls_io import KydLine, copy_template, fill_kyd_template


# 最小合法 JPEG，仅用于结构测试。
MINI_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00"
    + bytes([1] * 64)
    + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x7f\xff\xd9"
)


def test_kyd_adapter_keeps_source_sheet_and_xls_output():

    adapter = KydAdapter()
    cfg = adapter.template_config()
    assert cfg.sheet_name == "快越达发票"
    assert adapter.OUTPUT_SHEET == "模板"
    assert adapter.output_extension() == ".xls"


def test_fill_official_template_without_excel(tmp_path):

    if not KYD_TEMPLATE_PATH.exists():
        return

    dest = tmp_path / "KYD_GYR2_1箱.xls"
    copy_template(KYD_TEMPLATE_PATH, dest)

    fill_kyd_template(
        dest,
        channel="K18美西稳速达-卡派-包税",
        warehouse="GYR2",
        carton_count=1,
        lines=[
            KydLine(
                cells=[
                    "FBA33U000001",
                    "C",
                    "daisy necklace",
                    "雏菊项链",
                    1,
                    0.8,
                    70,
                    70,
                    56.0,
                    7113119090,
                    "无",
                    "无",
                    "alloy",
                    "日用",
                    16,
                    50,
                    40,
                    40,
                    None,
                    None,
                ],
                image_bytes=MINI_JPEG,
                image_kind="jpeg",
            )
        ],
    )

    import olefile
    import xlrd

    ole = olefile.OleFileIO(str(dest))
    streams = ["/".join(item) for item in ole.listdir()]
    assert not any("CompObj" in name for name in streams)
    book = ole.openstream(["Workbook"]).read()
    ole.close()

    wb = xlrd.open_workbook(str(dest))
    assert wb.sheet_names()[:3] == ["模板", "服务", "地址库"]
    ws = wb.sheet_by_name("模板")
    assert str(ws.cell_value(4, 1)).strip() == "GYR2"
    assert str(ws.cell_value(5, 1)).strip() == "GYR2"
    assert int(float(ws.cell_value(11, 1))) == 85395
    assert int(float(ws.cell_value(25, 1))) == 1
    assert str(ws.cell_value(29, 0)).strip() == "FBA33U000001"
    assert ws.cell_value(29, 2) == "daisy necklace"

    addr = wb.sheet_by_name("地址库")
    codes = [str(addr.cell_value(row, 0)).strip().upper() for row in range(addr.nrows)]
    assert codes.count("BJC1") == 1
    assert codes.count("GYR2") == 1

    import struct
    from app.services.kyd_xls_io import iter_biff

    pics = 0
    indexes = 0
    dbcells = 0
    for _pos, rec, ln, payload in iter_biff(book):
        if rec == 0x020B:
            indexes += 1
        if rec == 0x00D7:
            dbcells += 1
        if rec == 0x005D and ln >= 8:
            _ft, _cb, ot, _oid = struct.unpack_from("<HHHH", payload, 0)
            if ot == 8:
                pics += 1
    assert pics >= 1
    assert indexes == 3
    assert dbcells >= 6
    recs = list(iter_biff(book))
    db_pos = [pos for pos, rec, _ln, _payload in recs if rec == 0x00D7]
    for _pos, rec, ln, payload in recs:
        if rec != 0x020B or ln < 20:
            continue
        count = (ln - 16) // 4
        pointers = struct.unpack_from("<" + "I" * count, payload, 16)
        for pointer in pointers:
            assert pointer in db_pos

    # 产品图必须算进工作表 DgContainer，否则快越达会直接报请求错误。
    bofs = [pos for pos, rec, ln, _payload in recs if rec == 0x0809]
    sheet_start, sheet_end = bofs[1], bofs[2]
    draws = []
    for pos, rec, ln, payload in recs:
        if pos < sheet_start or pos >= sheet_end:
            continue
        if rec == 0x00EC:
            draws.append(payload)
    concat = b"".join(draws)
    f002_ln = struct.unpack_from("<I", concat, 4)[0]
    assert f002_ln + 8 == len(concat)

    # 产品图必须是小尺寸渐进 JPEG，不能塞原图 800px。
    dg = bytearray()
    for i, (_pos, rec, ln, payload) in enumerate(recs):
        if rec == 0x00EB:
            dg.extend(payload)
            j = i + 1
            while j < len(recs) and recs[j][1] == 0x003C:
                dg.extend(recs[j][3])
                j += 1
            break
    soi = bytes(dg).find(b"\xff\xd8")
    eoi = bytes(dg).rfind(b"\xff\xd9")
    jpeg = bytes(dg)[soi : eoi + 2]
    assert 80 < len(jpeg) < 8000
    assert b"\xff\xc2" in jpeg


def test_merge_group_copies_central_template(tmp_path, monkeypatch):

    if not KYD_TEMPLATE_PATH.exists():
        return

    from openpyxl import Workbook
    import app.services.invoice_adapters.kyd_adapter as ka

    source = tmp_path / "GYR2_FBA33U000001.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "快越达发票"
    ws["B4"] = "K18美西稳速达-卡派-包税"
    ws["B5"] = "GYR2"
    ws["A30"] = "FBA33U000001"
    ws["C30"] = "daisy necklace"
    ws["D30"] = "雏菊项链"
    ws["F30"] = 0.8
    ws["G30"] = 70
    ws["S30"] = "https://example.com/demo.jpg"
    wb.save(source)
    wb.close()

    monkeypatch.setattr(
        ka,
        "download_product_image",
        lambda url, name: (MINI_JPEG, "jpeg"),
    )

    dest = tmp_path / "KYD_GYR2_1箱.xls"
    adapter = KydAdapter()
    group = {
        "batch_id": "TEST",
        "carrier_code": "KYD",
        "template_version": "1.0",
        "warehouse_code": "GYR2",
        "input_count": 1,
        "input_files": [str(source)],
        "carton_numbers": ["FBA33U000001"],
        "source_ids": ["x"],
        "merge_plan_hash": "h",
        "date_id": "20260820",
    }
    adapter.merge_group(group, dest)
    assert dest.exists()
    assert adapter.validate_output(dest, group) == []

