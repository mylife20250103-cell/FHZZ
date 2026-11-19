from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
import hashlib
import shutil

import pytest

from app.reconciliation.models import Carton, InvoiceEstimate, ScanResult
from app.reconciliation.parser import parse_reports
from app.reconciliation.service import reconcile
from app.reconciliation.invoices import scan_directory
from app.reconciliation.export import export_results


CHANNEL = '加拿大海运美转加合德/以星21日达-卡派按公斤'
SECOND_CHANNEL = '加拿大海运美转加美森17日达-卡派'
NOTICE = '麻烦请确认订单的数据、出货渠道以及地址信息是否有误，若有疑议请及时@助理反馈处理，无反馈默认正常安排出货，请知悉！'


def hp_report(order='HPT12247356', fbas='FBA19XC954T9/FBA19XC954T9',
              weight='159.00', channel=CHANNEL):
    return (f'{order}/{fbas}\n D14787XJY小鲸渔XK-皓鹏 {channel} '
            f'报关方式非单证报关 收费重{weight}KG')


def hp_invoice(tmp_path, *, weight='20.1', fbas=('FBA19XC954T9',), channel=CHANNEL):
    return InvoiceEstimate(tmp_path/'皓鹏上传.xls', 'HP', 'YYZ9', channel,
        tuple(Carton(f'{fba}U000001', fba, D(weight), D(10), D(10), D(10), r)
              for r, fba in enumerate(fbas, 19)))


def test_two_supplied_hp_blocks_deduplicate_fba_keep_channels_and_raw_text():
    first = hp_report()
    second = hp_report('HPT12225678', 'FBA19VZW5C5K/FBA19VZW5C5K', '340.00', SECOND_CHANNEL)
    parsed = parse_reports(first+'\n'+NOTICE+'\n\n'+second+'\n'+NOTICE)
    assert len(parsed.reports) == 2 and len(parsed.ignored_lines) == 2
    a, b = parsed.reports
    assert not a.issues and not b.issues
    assert a.carrier == b.carrier == 'HP'
    assert a.order_number == 'HPT12247356' and b.order_number == 'HPT12225678'
    assert a.fba_ids == ('FBA19XC954T9',) and b.fba_ids == ('FBA19VZW5C5K',)
    assert a.channel == CHANNEL and b.channel == SECOND_CHANNEL
    assert a.billed_weight == D('159.00') and b.billed_weight == D('340.00')
    assert a.raw_text == first and b.raw_text == second
    assert a.line_number == 1 and b.line_number == 5


def test_hp_wrapped_fields_and_mixed_mc_messages_stay_separate():
    raw = hp_report(fbas='FBA1 / FBA2 / FBA1', weight='21.01').replace(
        '报关方式非单证报关 收费重', '报关方式\n非单证报关\n收费重')
    parsed = parse_reports(raw+'\nMC1(FBA1) 美速达快提卡派 13kg')
    assert len(parsed.reports) == 2
    assert all(not r.issues for r in parsed.reports)
    assert parsed.reports[0].fba_ids == ('FBA1', 'FBA2')
    assert parsed.reports[0].billed_weight == D('21.01')
    assert parsed.reports[1].carrier == 'MC'


@pytest.mark.parametrize('weight', ['0', '-1', 'NaN', 'Infinity', 'invalid', ''])
def test_hp_invalid_weight_keeps_identity_and_blocks_duplicate_order(weight):
    parsed = parse_reports(hp_report(weight=weight)+'\n'+hp_report())
    assert len(parsed.reports) == 2
    assert all(r.order_number == 'HPT12247356' and r.fba_ids == ('FBA19XC954T9',)
               for r in parsed.reports)
    assert all(r.issues and any('重复' in issue for issue in r.issues) for r in parsed.reports)


def test_hp_cross_order_duplicate_fba_blocks_both_but_mc_local_duplicate_still_invalid():
    parsed = parse_reports(hp_report()+'\n'+hp_report(order='HPT2'))
    assert len(parsed.reports) == 2 and all(r.issues for r in parsed.reports)
    assert parse_reports('MC1(FBA1,FBA1) 渠道 21kg').reports[0].issues


@pytest.mark.parametrize('raw', [
    hp_report(fbas='FBA1/WRONG'), hp_report(fbas='FBA1U000001'),
    hp_report().replace('皓鹏', '未知'), hp_report().replace('报关方式非单证报关', ''),
    hp_report().replace(CHANNEL, ''), hp_report()+' 收费重160KG',
    'HPT12247356/FBA19XC954T9\n'+NOTICE,
])
def test_hp_missing_or_invalid_fields_remain_visible(raw):
    parsed = parse_reports(raw)
    assert len(parsed.reports) == 1 and parsed.reports[0].issues


@pytest.mark.parametrize('raw', [hp_report()+'\n收费重160KG',
    hp_report().replace('报关方式非单证报关','报关方式')])
def test_hp_duplicate_weight_on_next_line_and_empty_declaration_do_not_pass(raw):
    parsed = parse_reports(raw)
    assert len(parsed.reports) == 1 and parsed.reports[0].issues


@pytest.mark.parametrize('header', ['HPT1/FBA1 FBA2', 'HPT1/FBA1 /#', 'HPT1/FBA1/FBA2,'])
def test_hp_entire_identity_must_validate_and_bad_identity_still_blocks_other_orders(header):
    bad = header+'\n皓鹏 渠道 报关方式非单证报关 收费重21KG'
    assert parse_reports(bad).reports[0].issues
    parsed = parse_reports(bad+'\n'+hp_report(order='HPT2',fbas='FBA1',weight='21'))
    assert len(parsed.reports) == 2 and all(r.issues for r in parsed.reports)
    assert 'FBA1' in parsed.reports[0].fba_ids
    assert all(any('重复' in issue for issue in r.issues) for r in parsed.reports)


def test_order_like_text_in_channels_never_changes_carrier_or_splits_block():
    parsed = parse_reports('MC1(FBA1) HPT2 快递 10kg\n'+hp_report(channel='MC1快线'))
    assert len(parsed.reports) == 2 and all(not r.issues for r in parsed.reports)
    assert [r.carrier for r in parsed.reports] == ['MC','HP']
    assert parsed.reports[0].channel == 'HPT2 快递' and parsed.reports[1].channel == 'MC1快线'


def test_blank_lines_after_completed_hp_block_do_not_attach_unrelated_footer():
    parsed = parse_reports(hp_report()+'\n\n收到，谢谢')
    assert len(parsed.reports) == 1 and not parsed.reports[0].issues
    assert '收到，谢谢' in parsed.ignored_lines


@pytest.mark.parametrize('real,billed,approved,remeasure', [
    ('8', '21', '21', False), ('8', '22', '21', True),
    ('20.1', '21', '21', False), ('20.1', '21.01', '21', True),
    ('21', '21', '21', False), ('21.01', '22', '22', False),
])
def test_hp_whole_ticket_minimum_and_ceiling_boundary(tmp_path,real,billed,approved,remeasure):
    invoice = hp_invoice(tmp_path,weight=real)
    parsed = parse_reports(hp_report(weight=billed))
    row = reconcile(ScanResult(tmp_path,(invoice,),''), parsed)[0]
    assert invoice.approved_weight == D(approved)
    assert invoice.estimated_weight == D(real)
    assert row.status == ('需申请重测' if remeasure else '重量在允许范围')
    assert row.needs_remeasure is remeasure and row.difference == D(billed)-D(approved)
    assert replace(invoice,carrier='MC').approved_weight == D(real).to_integral_value(rounding='ROUND_CEILING')
    assert replace(invoice,carrier='KYD').approved_weight == D(real).to_integral_value(rounding='ROUND_CEILING')


def test_hp_partial_match_includes_unlisted_cartons_and_stays_within_carrier(tmp_path):
    invoice = hp_invoice(tmp_path,weight='12.1',fbas=('FBA19XC954T9','FBA2','FBA3'))
    mc = replace(invoice,carrier='MC',path=tmp_path/'MC_other.xlsx')
    rows = reconcile(ScanResult(tmp_path,(invoice,mc),''),parse_reports(hp_report(weight='37')))
    row = rows[0]
    assert row.match_method == '部分FBA辅助关联' and row.unlisted_fbas == ('FBA2','FBA3')
    assert row.invoice.approved_weight == D(37) and len(row.invoice.cartons) == 3
    assert not row.needs_remeasure and row.difference == 0
    assert rows[1].status == '待货代报数'


def test_hp_partial_cross_file_or_duplicate_source_never_passes(tmp_path):
    first = hp_invoice(tmp_path)
    other = hp_invoice(tmp_path,fbas=('FBA2',))
    other = replace(other,path=tmp_path/'other.xls')
    parsed = parse_reports(hp_report(fbas='FBA19XC954T9/FBA2',weight='21'))
    rows = reconcile(ScanResult(tmp_path,(first,other),''),parsed)
    assert {r.status for r in rows} == {'待货代报数','未匹配'}
    rows = reconcile(ScanResult(tmp_path,(first,replace(first,path=other.path)),''),parse_reports(hp_report(weight='21')))
    assert all(r.status == '匹配冲突' and r.difference is None for r in rows)


HP_TEMPLATE = Path(r'I:\OneDrive\OneDrive - Lion\【采购仓储】\【发货单】\发货单各源抓取\皓鹏国际-单票下单模板.xls')


def write_hp(path, *, boxes=None, count=None, overrides=None):
    """只修改临时副本，以官方BIFF模板验证真实读取边界。"""
    if not HP_TEMPLATE.exists():
        pytest.skip('缺少皓鹏官方模板；不能据此宣称实票验收通过')
    from app.customs.xls_patch import patch_xls
    boxes = boxes if boxes is not None else [('FBA19XC954T9U000001', '8', '10', '10', '10')]
    shutil.copyfile(HP_TEMPLATE,path)
    updates = {(1,2):CHANNEL,(2,2):'YYZ9',(14,2):str(count if count is not None else len({b[0] for b in boxes}))}
    for row,box in enumerate(boxes,19):
        for col,value in zip((1,7,8,9,10),box):
            updates[row,col] = str(value)
    updates.update(overrides or {})
    patch_xls(path,'单票下单-填写表',updates)
    return path


def test_hp_real_template_columns_nonstandard_name_counts_and_original_read_only(tmp_path):
    before_template = hashlib.sha256(HP_TEMPLATE.read_bytes()).hexdigest() if HP_TEMPLATE.exists() else ''
    boxes = [('FBA19XC954T9U000001','8.2','40','30','30')]*2+[
             ('FBA19XC954T9U000002','7.8','40','30','30')]
    path = write_hp(tmp_path/'加拿大本次上传.xls',boxes=boxes)
    before = path.read_bytes()
    scanned = scan_directory(tmp_path)
    assert len(scanned.invoices) == 1
    invoice = scanned.invoices[0]
    assert not invoice.issues and invoice.carrier == 'HP'
    assert invoice.channel == CHANNEL and invoice.warehouse == 'YYZ9'
    assert len(invoice.cartons) == 2 and invoice.fba_ids == ('FBA19XC954T9',)
    assert invoice.total_real == D(16) and invoice.tolerance_volume == D('14.336')
    assert invoice.approved_weight == D(21)
    assert path.read_bytes() == before
    assert hashlib.sha256(HP_TEMPLATE.read_bytes()).hexdigest() == before_template


@pytest.mark.parametrize('overrides', [
    {(18,7):'产品重量'}, {(14,2):'2'}, {(19,8):'0'}, {(19,7):'invalid'},
    {(19,1):'FBA19XC954T9'}, {(1,2):''}, {(2,2):''},
])
def test_hp_bad_headers_counts_dimensions_or_missing_heads_block_weight(tmp_path,overrides):
    write_hp(tmp_path/'HP_YYZ9_1箱.xls',overrides=overrides)
    invoice = scan_directory(tmp_path).invoices[0]
    assert invoice.issues and invoice.approved_weight is None


def test_hp_duplicate_carton_measurement_conflict_visible(tmp_path):
    write_hp(tmp_path/'HP_YYZ9_1箱.xls',boxes=[
        ('FBA19XC954T9U000001','8','10','10','10'),
        ('FBA19XC954T9U000001','9','10','10','10')])
    invoice = scan_directory(tmp_path).invoices[0]
    assert any('冲突' in issue for issue in invoice.issues) and invoice.approved_weight is None


def test_corrupt_unknown_xls_cannot_interrupt_other_valid_invoices(tmp_path):
    write_hp(tmp_path/'加拿大上传.xls')
    (tmp_path/'损坏.xls').write_bytes(bytes.fromhex('d0cf11e0a1b11ae1'))
    assert len(scan_directory(tmp_path).invoices) == 1


def test_hp_invalid_measurement_keeps_identity_for_cross_file_conflicts(tmp_path):
    write_hp(tmp_path/'加拿大上传.xls')
    write_hp(tmp_path/'坏数据.xls',overrides={(19,7):'?'})
    rows = reconcile(scan_directory(tmp_path),parse_reports(hp_report(weight='21')))
    assert all(r.status == '匹配冲突' and r.difference is None for r in rows)


def test_hp_export_minimum_whole_cartons_raw_and_source_overwrite_guard(tmp_path):
    from openpyxl import load_workbook
    source = write_hp(tmp_path/'加拿大下单.xls')
    scan = scan_directory(tmp_path)
    raw = hp_report(weight='22')+'\n'+NOTICE
    rows = reconcile(scan,parse_reports(raw))
    dest = export_results(rows,tmp_path/'核对.xlsx',raw_text=raw,source_directory=tmp_path)
    book = load_workbook(dest,data_only=True)
    try:
        summary = book['货件核对']
        values = {cell.value:summary.cell(7,cell.column).value for cell in summary[6]}
        assert values['货代'] == 'HP' and values['核准上限(kg)'] == 21
        assert values['超限差额(kg)'] == 1 and values['箱数'] == 1
        assert '21' in str(summary['A5'].value) and '皓鹏' in str(summary['A5'].value)
        assert book['货箱明细'].max_row == 2
        assert [book['货代原文'].cell(r,2).value for r in range(2,5)] == raw.splitlines()
    finally:
        book.close()
    before = source.read_bytes()
    with pytest.raises(ValueError,match='源发票'):
        export_results(rows,source,raw_text=raw,source_directory=tmp_path)
    # 导出会追加xlsx后缀；错误扩展名HP候选同样不能被覆盖。
    protected = tmp_path/'HP_YYZ9_1箱.xlsx'
    protected.write_bytes(b'protected')
    with pytest.raises(ValueError,match='源发票'):
        export_results([],protected,raw_text='',source_directory=tmp_path)
    assert source.read_bytes() == before and protected.read_bytes() == b'protected'
