import hashlib
import shutil
from pathlib import Path
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation


def mc_invoice(path, name="树脂发箍", english="headband"):
    wb = Workbook()
    ws = wb.active
    ws.title = "模板"
    for col, label in {7: "产品英文品名*", 8: "产品中文品名*", 11: "产品材质*", 12: "产品海关编码*"}.items():
        ws.cell(17, col, label)
    ws["B2"] = "保留渠道"
    ws["C5"] = "=SUM(1,2)"
    for c, v in {1: "FBA0001U000001", 7: english, 8: name, 11: "resin", 12: "9615190000", 9: 2, 10: 10}.items():
        ws.cell(18, c, v)
    dv = DataValidation(type="list", formula1='"A,B"')
    ws.add_data_validation(dv)
    dv.add("B2")
    wb.create_sheet("渠道列表")
    wb.create_sheet("地址库")
    wb.save(path)
    wb.close()
    with ZipFile(path, "a") as z:
        z.writestr("customXml/preserved.xml", b"<original>image-metadata</original>")
    return path


def test_xlsx_edits_only_target_cells_preserving_other_zip_members(tmp_path):
    from app.customs.workbooks import read_invoice, write_invoice
    source = mc_invoice(tmp_path / "MC.xlsx")
    raw = source.read_bytes()
    invoice = read_invoice(source, "MC")
    assert invoice.columns == (8, 7, 11, 12)
    assert invoice.lines[0].values == ("树脂发箍", "headband", "resin", "9615190000")
    dest = tmp_path / "new.xlsx"
    write_invoice(source, dest, invoice, {18: ("树脂发饰", "hair accessory", "resin", "0096151900")})
    assert source.read_bytes() == raw
    with ZipFile(source) as a, ZipFile(dest) as b:
        assert a.namelist() == b.namelist()
        for member in a.namelist():
            if member != "xl/worksheets/sheet1.xml":
                assert a.read(member) == b.read(member)
    wb = load_workbook(dest)
    assert wb["模板"]["B2"].value == "保留渠道"
    assert wb["模板"]["C5"].value == "=SUM(1,2)"
    assert wb["模板"]["L18"].value == "0096151900"
    assert len(wb["模板"].data_validations.dataValidation) == 1
    wb.close()


def test_formula_product_is_rejected(tmp_path):
    from app.customs.workbooks import read_invoice
    with pytest.raises(ValueError):
        read_invoice(mc_invoice(tmp_path / "MC.xlsx", english="=A1"), "MC")


def test_blank_original_english_can_be_filled_from_complete_rule(tmp_path):
    from app.customs.workbooks import read_invoice, write_invoice
    source = mc_invoice(tmp_path / "MC.xlsx", english="")
    invoice = read_invoice(source, "MC")
    dest = tmp_path / "revised.xlsx"
    write_invoice(source, dest, invoice, {18: ("树脂发饰", "hair accessory", "resin", "0096151900")})
    assert read_invoice(dest, "MC").lines[0].values[1] == "hair accessory"


def test_absent_xml_cell_can_be_filled_without_losing_following_cells(tmp_path):
    import re
    from app.customs.workbooks import read_invoice, write_invoice
    source = mc_invoice(tmp_path / "original.xlsx")
    members = {}
    with ZipFile(source) as z:
        members = {name: z.read(name) for name in z.namelist()}
    members['xl/worksheets/sheet1.xml'] = re.sub(rb'<c r="G18".*?</c>', b'', members['xl/worksheets/sheet1.xml'])
    missing = tmp_path / "missing.xlsx"
    with ZipFile(missing, 'w') as z:
        for name, raw in members.items():
            z.writestr(name, raw)
    invoice = read_invoice(missing, "MC")
    revised = tmp_path / "filled.xlsx"
    write_invoice(missing, revised, invoice, {18: ("树脂发饰", "hair accessory", "resin", "0096151900")})
    wb = load_workbook(revised)
    assert wb["模板"]["G18"].value == "hair accessory"
    assert wb["模板"]["I18"].value == 2
    assert wb["模板"]["J18"].value == 10
    wb.close()


def test_official_mc_copy_retains_validation_extensions_and_formula_xml(tmp_path):
    from app.customs.workbooks import _patch_xlsx, read_invoice, write_invoice
    template = Path(r'I:\OneDrive\OneDrive - Lion\【采购仓储】\【发货单】\【发票合并】\发票系统\模板\迈创发票模板.xlsx')
    if not template.exists():
        pytest.skip("缺少官方迈创模板")
    original_hash = hashlib.sha256(template.read_bytes()).hexdigest()
    sample = tmp_path / "MC.xlsx"
    _patch_xlsx(template, sample, "模板", {"G18": "headband", "H18": "树脂发箍", "K18": "resin", "L18": "9615190000"})
    invoice = read_invoice(sample, "MC")
    revised = tmp_path / "revised.xlsx"
    write_invoice(sample, revised, invoice, {18: ("树脂发饰", "hair accessory", "resin", "0096151900")})
    with ZipFile(sample) as a, ZipFile(revised) as b:
        original = a.read("xl/worksheets/sheet1.xml")
        updated = b.read("xl/worksheets/sheet1.xml")
        import re
        for pattern in (rb'<extLst\b.*?</extLst>', rb'<(?:\w+:)?dataValidations\b.*?</(?:\w+:)?dataValidations>'):
            assert re.findall(pattern, updated, re.DOTALL) == re.findall(pattern, original, re.DOTALL)
    assert hashlib.sha256(template.read_bytes()).hexdigest() == original_hash


def test_wrong_carrier_and_duplicate_header_rejected(tmp_path):
    from app.customs.workbooks import read_invoice
    p = mc_invoice(tmp_path / "MC.xlsx")
    with pytest.raises(ValueError):
        read_invoice(p, "HP")
    wb = load_workbook(p)
    wb["模板"]["M17"] = "产品中文品名*"
    wb.save(p)
    wb.close()
    with pytest.raises(ValueError):
        read_invoice(p, "MC")


def test_unmerged_source_with_system_meta_is_rejected(tmp_path):
    from app.customs.workbooks import read_invoice
    p = mc_invoice(tmp_path / 'source.xlsx')
    wb = load_workbook(p)
    wb.create_sheet('_SystemMeta')
    wb.save(p)
    wb.close()
    with pytest.raises(ValueError, match='源发票|已合并'):
        read_invoice(p, 'MC')


def test_kyd_resaved_compobj_file_is_rejected(tmp_path):
    import pythoncom
    from app.customs.workbooks import read_invoice
    from app.services.kyd_xls_io import write_named_stream
    template = Path(r'I:\OneDrive\OneDrive - Lion\【采购仓储】\【发货单】\【发票合并】\发票系统\模板\快越达发票模版.xls')
    if not template.exists():
        pytest.skip('缺少快越达官方模板')
    sample = tmp_path / 'resaved.xls'
    shutil.copyfile(template, sample)
    try:
        write_named_stream(sample, '\x01CompObj', b'incompatible-resave-marker')
    finally:
        pythoncom.CoUninitialize()
    with pytest.raises(ValueError, match='另存|CompObj'):
        read_invoice(sample, 'KYD')


def test_detect_carrier_uses_template_not_filename_or_extension_alone(tmp_path):
    from app.customs.workbooks import detect_invoice
    p = mc_invoice(tmp_path / 'KYD_misleading_name.xlsx')
    assert detect_invoice(p).carrier == 'MC'
    mislabeled = tmp_path / 'wrong.xls'
    mislabeled.write_bytes(p.read_bytes())
    with pytest.raises(ValueError, match='格式|扩展名'):
        detect_invoice(mislabeled)


def test_wrong_manual_carrier_tells_user_which_selection_is_wrong(tmp_path):
    from app.customs.workbooks import read_invoice
    p = tmp_path / 'KYD_example.xls'
    p.write_bytes(b'not-read-for-format-mismatch')
    with pytest.raises(ValueError, match='迈创.*快越达|迈创.*自动识别'):
        read_invoice(p, 'MC')


def test_uploaded_kyd_sample_preserves_all_non_target_values_and_picture_records(tmp_path):
    import struct
    import olefile
    import xlrd
    from app.customs.workbooks import read_invoice, write_invoice
    from app.customs.xls_patch import workbook_bytes
    from app.services.kyd_xls_io import iter_biff
    source = Path(r'I:\OneDrive\OneDrive - Lion\【采购仓储】\【发货单】\【发票合并】\发票系统\合并结果\20260904\20260904-B0001\KYD_BJC1_1箱.xls')
    if not source.exists():
        pytest.skip('缺少用户已上传快越达样本')
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    invoice = read_invoice(source, 'KYD')
    assert invoice.columns == (4, 3, 13, 10)
    assert invoice.lines[0].values == ('50个粘性夹', 'Sticky Clip', 'Plastic', '3924900000')
    dest = tmp_path / source.name
    new_values = ('测试粘性夹', 'adhesive clips test', 'Plastic', '3924900000')
    write_invoice(source, dest, invoice, {30: new_values})
    assert read_invoice(dest, 'KYD').lines[0].values == new_values
    a = xlrd.open_workbook(str(source), formatting_info=True)
    b = xlrd.open_workbook(str(dest), formatting_info=True)
    try:
        assert a.sheet_names() == b.sheet_names()
        for before, after in zip(a.sheets(), b.sheets()):
            assert (before.nrows, before.ncols) == (after.nrows, after.ncols)
            for r in range(before.nrows):
                for c in range(before.ncols):
                    assert before.cell_xf_index(r, c) == after.cell_xf_index(r, c)
                    if before.name == '模板' and r == 29 and c in (2, 3, 9, 12):
                        continue
                    assert before.cell_value(r, c) == after.cell_value(r, c)
    finally:
        a.release_resources()
        b.release_resources()
    picture_types = {0xEB, 0xEC, 0x5D, 0x7F, 0x1B6}
    assert [(rec, body) for _, rec, _, body in iter_biff(workbook_bytes(source)) if rec in picture_types] == [
        (rec, body) for _, rec, _, body in iter_biff(workbook_bytes(dest)) if rec in picture_types]
    with olefile.OleFileIO(source) as original, olefile.OleFileIO(dest) as revised:
        assert original.listdir() == revised.listdir()
        assert not any('CompObj' in part for stream in revised.listdir() for part in stream)
        for stream in original.listdir():
            if stream != ['Workbook']:
                assert original.openstream(stream).read() == revised.openstream(stream).read()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash


@pytest.mark.parametrize("carrier,template,sheet,start,cols", [
    ("HP", r"I:\OneDrive\OneDrive - Lion\【采购仓储】\【发货单】\发货单各源抓取\皓鹏国际-单票下单模板.xls", "单票下单-填写表", 19, (3, 2, 13, 11)),
    ("KYD", r"I:\OneDrive\OneDrive - Lion\【采购仓储】\【发货单】\【发票合并】\发票系统\模板\快越达发票模版.xls", "模板", 30, (4, 3, 13, 10)),
])
def test_real_xls_copy_preserves_ole_streams_drawings_and_other_cells(tmp_path, carrier, template, sheet, start, cols):
    import olefile
    from app.customs.xls_patch import patch_xls
    from app.customs.workbooks import read_invoice, write_invoice
    template = Path(template)
    if not template.exists():
        pytest.skip("本机缺少官方模板；不能据此认定货代兼容性通过")
    template_hash = hashlib.sha256(template.read_bytes()).hexdigest()
    source = tmp_path / (carrier + ".xls")
    shutil.copyfile(template, source)
    before = ("树脂发箍", "headband", "resin", "9615190000")
    patch_xls(source, sheet, {(start, c): v for c, v in zip(cols, before)})
    inv = read_invoice(source, carrier)
    assert inv.lines[0].values == before
    dest = tmp_path / (carrier + "_new.xls")
    after = ("树脂发饰", "hair accessory", "resin", "0096151900")
    write_invoice(source, dest, inv, {start: after})
    assert read_invoice(dest, carrier).lines[0].values == after
    with olefile.OleFileIO(source) as a, olefile.OleFileIO(dest) as b:
        assert a.listdir() == b.listdir()
        for stream in a.listdir():
            if stream != ["Workbook"]:
                assert a.openstream(stream).read() == b.openstream(stream).read()
    assert hashlib.sha256(template.read_bytes()).hexdigest() == template_hash


def test_xls_sst_growth_keeps_extsst_buckets_addressable(tmp_path):
    import math
    import struct
    import xlrd
    from app.customs.xls_patch import patch_xls, workbook_bytes
    from app.services.kyd_xls_io import iter_biff
    template = Path(r'I:\OneDrive\OneDrive - Lion\【采购仓储】\【发货单】\发货单各源抓取\皓鹏国际-单票下单模板.xls')
    if not template.exists():
        pytest.skip("缺少皓鹏官方模板")
    dest = tmp_path / "many_strings.xls"
    shutil.copyfile(template, dest)
    original = xlrd.open_workbook(str(dest), formatting_info=True)
    sheet = original.sheet_by_name("单票下单-填写表")
    cells = [(r + 1, c + 1) for r in range(18, sheet.nrows) for c in range(sheet.ncols) if sheet.cell_type(r, c) == 6][:240]
    original.release_resources()
    assert len(cells) >= 200
    patch_xls(dest, "单票下单-填写表", {(r, c): f"新增_{r}_{c}" for r, c in cells})
    book = workbook_bytes(dest)
    records = list(iter_biff(book))
    wb = xlrd.open_workbook(str(dest), on_demand=True, formatting_info=True)
    strings = list(wb._sharedstrings)
    wb.release_resources()
    ext = next(payload for _, rec, _, payload in records if rec == 0xFF)
    dsst = struct.unpack_from('<H', ext)[0]
    assert (len(ext) - 2) // 8 == math.ceil(len(strings) / dsst)
    for bucket, at in enumerate(range(2, len(ext), 8)):
        pointer, cb, reserved = struct.unpack_from('<IHH', ext, at)
        rec_pos, rec_type, rec_len, payload = next(v for v in records if v[0] + 4 <= pointer < v[0] + 4 + v[2])
        assert rec_type in (0xFC, 0x3C)
        assert pointer - rec_pos == cb
        count, flag = struct.unpack_from('<HB', book, pointer)
        if flag == 1 and pointer + 3 + count * 2 <= rec_pos + 4 + rec_len:
            assert book[pointer + 3:pointer + 3 + count * 2].decode('utf-16le') == strings[bucket * dsst]


def test_sst_positions_handle_continued_characters_and_rich_extensions():
    import struct
    from app.customs.sst_index import string_positions
    first = struct.pack('<IIHB', 4, 4, 4, 1) + "甲乙".encode('utf-16le')
    rest = b'\x01' + "丙丁".encode('utf-16le') + struct.pack('<HB', 1, 0) + b'A'
    rest += struct.pack('<HBHI', 2, 12, 1, 2) + b'BC' + bytes(4) + b'XY'
    rest += struct.pack('<HB', 1, 1) + 'Z'.encode('utf-16le')
    book = struct.pack('<HH', 0xFC, len(first)) + first + struct.pack('<HH', 0x3C, len(rest)) + rest
    assert string_positions(book) == [(12, 12), (28, 9), (32, 13), (49, 30)]


@pytest.mark.parametrize('error_cell', [False, True])
def test_xls_numeric_rk_or_error_hs_is_handled_explicitly(tmp_path, error_cell):
    import struct
    import pythoncom
    from app.customs.xls_patch import patch_xls, workbook_bytes
    from app.customs.workbooks import read_invoice, write_invoice
    from app.services import kyd_xls_io as biff
    template = Path(r'I:\OneDrive\OneDrive - Lion\【采购仓储】\【发货单】\发货单各源抓取\皓鹏国际-单票下单模板.xls')
    if not template.exists():
        pytest.skip('缺少皓鹏官方模板')
    source = tmp_path / 'numeric.xls'
    shutil.copyfile(template, source)
    patch_xls(source, '单票下单-填写表', {(19, 3): '树脂发箍', (19, 2): 'headband', (19, 13): 'resin', (19, 11): '96151900'})
    book = bytearray(workbook_bytes(source))
    start, end = biff.sheet_span_by_name(book, '单票下单-填写表')
    for pos, rt, ln, payload in biff.iter_biff(book):
        if start <= pos < end and rt == 0xFD and struct.unpack_from('<HH', payload) == (18, 10):
            xf = struct.unpack_from('<H', payload, 4)[0]
            replacement = biff.rec_bytes(0x205, struct.pack('<HHHBB', 18, 10, xf, 0x17, 1)) if error_cell else biff.rec_bytes(0x27E, struct.pack('<HHHI', 18, 10, xf, 96151900 * 4 + 2))
            book[pos:pos + 4 + ln] = replacement
            break
    biff.update_boundsheet_offsets(book)
    try:
        biff.write_workbook_stream(source, bytes(book))
    finally:
        pythoncom.CoUninitialize()
    if error_cell:
        with pytest.raises(ValueError, match='错误值'):
            read_invoice(source, 'HP')
    else:
        invoice = read_invoice(source, 'HP')
        assert invoice.lines[0].values[3] == '96151900'
        dest = tmp_path / 'revised.xls'
        write_invoice(source, dest, invoice, {19: ('树脂发饰', 'hair accessory', 'resin', '0096151900')})
        assert read_invoice(dest, 'HP').lines[0].values[3] == '0096151900'
