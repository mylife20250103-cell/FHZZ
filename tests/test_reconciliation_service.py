from dataclasses import replace
from decimal import Decimal as D

import pytest
from openpyxl import load_workbook

from app.reconciliation.invoices import scan_directory
from app.reconciliation.parser import parse_reports
from app.reconciliation.service import reconcile
from app.reconciliation.export import export_results
from tests.test_reconciliation_inputs import write_mc


def scanned(tmp_path):
    write_mc(tmp_path/'MC_GYR3_3箱.xlsx')
    return scan_directory(tmp_path)


def test_exact_sets_reordered_and_rounding_boundary(tmp_path):
    scan=scanned(tmp_path)
    for billed,expected in [(41,False),(42,True)]:
        rows=reconcile(scan,parse_reports(f'MC1(FBA3,FBA1,FBA2) 美速达快提卡派 {billed}kg'))
        assert len(rows)==1 and rows[0].needs_remeasure is expected
        assert rows[0].difference==D(billed)-41
        assert rows[0].status==('需申请重测' if expected else '重量在允许范围')
        assert rows[0].match_method=='完整FBA匹配'
        assert rows[0].unlisted_fbas==()


@pytest.mark.parametrize('billed,remeasure', [(40,False),(41,False),(42,True)])
def test_unique_partial_fbas_use_all_cartons_and_whole_ticket_rounding(tmp_path,billed,remeasure):
    rows=reconcile(scanned(tmp_path),parse_reports(f'MC1(FBA1) 美速达快提卡派 {billed}kg'))
    assert len(rows)==1
    row=rows[0]
    assert row.invoice.approved_weight==D(41)
    assert len(row.invoice.cartons)==3
    assert row.match_method=='部分FBA辅助关联'
    assert row.unlisted_fbas==('FBA2','FBA3')
    assert row.difference==D(billed)-41 and row.needs_remeasure is remeasure


def test_unlisted_carton_real_weight_is_included(tmp_path):
    write_mc(tmp_path/'MC_GYR3_4箱.xlsx',[
        ('FBA1U000001',1,10,10,10),('FBA2U000001',1,10,10,10),
        ('FBA3U000001',1,10,10,10),('FBA4U000001',60,10,10,10)])
    row=reconcile(scan_directory(tmp_path),parse_reports('MC1(FBA1,FBA2,FBA3) 美速达快提卡派 63kg'))[0]
    assert row.status=='重量在允许范围'
    assert row.invoice.approved_weight==D(63) and row.difference==0
    assert row.unlisted_fbas==('FBA4',)


@pytest.mark.parametrize('add_other_file',[False,True])
def test_every_reported_fba_must_belong_to_one_invoice(tmp_path,add_other_file):
    scan=scanned(tmp_path)
    if add_other_file:
        write_mc(tmp_path/'MC_IND9_1箱.xlsx',[('FBA9U000001',8,30,30,30)],warehouse='IND9')
        scan=scan_directory(tmp_path)
    rows=reconcile(scan,parse_reports('MC1(FBA1,FBA9) 美速达快提卡派 42kg'))
    assert sum(r.status=='未匹配' for r in rows)==1
    assert all(r.status in {'待货代报数','未匹配'} and r.difference is None for r in rows)


def test_partial_set_with_multiple_source_candidates_blocks_all(tmp_path):
    write_mc(tmp_path/'MC_GYR3_2箱.xlsx',[
        ('FBA1U000001',8,30,30,30),('FBA2U000001',9,30,30,30)])
    write_mc(tmp_path/'MC_IND9_2箱.xlsx',[
        ('FBA1U000001',8,30,30,30),('FBA3U000001',9,30,30,30)],warehouse='IND9')
    rows=reconcile(scan_directory(tmp_path),parse_reports('MC1(FBA1) 美速达快提卡派 42kg'))
    assert len(rows)==3
    assert all(r.status=='匹配冲突' and r.difference is None and not r.needs_remeasure for r in rows)


@pytest.mark.parametrize('second_fbas',['FBA2','FBA1,FBA2,FBA3'])
def test_multiple_partial_or_exact_reports_cannot_split_one_invoice(tmp_path,second_fbas):
    rows=reconcile(scanned(tmp_path),parse_reports(
        f'MC1(FBA1) 美速达快提卡派 20kg\nMC2({second_fbas}) 美速达快提卡派 21kg'))
    source=next(r for r in rows if r.invoice)
    assert source.status=='匹配冲突'
    assert all(r.difference is None and not r.needs_remeasure for r in rows)


@pytest.mark.parametrize('source_error,billed,status',[
    (True,'42','源数据异常'),(False,'0','报数异常')])
def test_partial_association_preserves_source_and_report_validation(tmp_path,source_error,billed,status):
    scan=scanned(tmp_path)
    if source_error:
        scan=replace(scan,invoices=(replace(scan.invoices[0],issues=('同箱尺寸冲突',)),))
    rows=reconcile(scan,parse_reports(f'MC1(FBA1) 美速达快提卡派 {billed}kg'))
    assert len(rows)==1 and rows[0].status==status
    assert rows[0].report is not None and rows[0].difference is None and not rows[0].needs_remeasure


def test_partial_matching_does_not_cross_carrier_or_enable_kyd_protocol(tmp_path):
    scan=scanned(tmp_path)
    other=replace(scan,invoices=(replace(scan.invoices[0],carrier='KYD'),))
    parsed=parse_reports('MC1(FBA1) 美速达快提卡派 42kg')
    assert {r.status for r in reconcile(other,parsed)}=={'待货代报数','未匹配'}
    kyd=replace(parsed,reports=(replace(parsed.reports[0],carrier='KYD'),))
    assert {r.status for r in reconcile(other,kyd)}=={'待货代报数','未匹配'}


def test_repeated_order_on_disjoint_partial_invoices_blocks_both(tmp_path):
    scanned(tmp_path)
    write_mc(tmp_path/'MC_IND9_2箱.xlsx',[
        ('FBA9U000001',8,30,30,30),('FBA10U000001',9,30,30,30)],warehouse='IND9')
    rows=reconcile(scan_directory(tmp_path),parse_reports(
        'MC1(FBA1) 美速达快提卡派 42kg\nMC1(FBA9) 美速达快提卡派 20kg'))
    assert len(rows)==2
    assert all(r.invoice and r.report and r.status=='报数异常' and r.difference is None
               and not r.needs_remeasure for r in rows)


def test_partial_channel_warning_does_not_hide_remeasurement(tmp_path):
    row=reconcile(scanned(tmp_path),parse_reports('MC1(FBA2,FBA1) 美速达美东卡派 42kg'))[0]
    assert row.needs_remeasure and row.status=='需申请重测'
    assert '渠道' in row.message and 'FBA3' in row.message
    assert row.unlisted_fbas==('FBA3',)


def test_partial_export_preserves_whole_invoice_and_original_short_report(tmp_path):
    scan=scanned(tmp_path)
    raw='MC1(FBA1) 美速达快提卡派 42kg'
    rows=reconcile(scan,parse_reports(raw))
    p=export_results(rows,tmp_path/'辅助关联.xlsx',raw_text=raw,source_directory=scan.directory)
    w=load_workbook(p,data_only=True)
    try:
        sheet=w['货件核对'];headers=[c.value for c in sheet[6]]
        values={label:sheet.cell(7,i+1).value for i,label in enumerate(headers)}
        assert values['关联方式']=='部分FBA辅助关联'
        assert values['报数未列FBA']=='FBA2\nFBA3'
        assert values['箱数']==3 and values['核准上限(kg)']==41
        assert values['超限差额(kg)']==1
        assert values['所含FBA']=='FBA1\nFBA2\nFBA3'
        assert {w['货箱明细'].cell(r,3).value for r in range(2,5)}=={'FBA1','FBA2','FBA3'}
        assert w['货代原文']['B2'].value==raw
    finally:
        w.close()


def test_overlapping_source_boxes_across_history_cannot_pass(tmp_path):
    first=tmp_path/'old';second=tmp_path/'new'
    first.mkdir();second.mkdir()
    box=('FBA1U000001',8,40,30,30)
    write_mc(first/'MC_GYR3_1箱.xlsx',[box])
    write_mc(second/'MC_GYR3_2箱.xlsx',[box,('FBA2U000001',9,40,30,30)])
    rows=reconcile(scan_directory(tmp_path),parse_reports('MC1(FBA1) 美速达快提卡派 8kg'))
    assert all(r.status=='匹配冲突' and r.difference is None for r in rows)


def test_invalid_duplicate_identity_blocks_otherwise_valid_weight(tmp_path):
    rows=reconcile(scanned(tmp_path),parse_reports(
        'MC1(FBA1,FBA2,FBA3) 美速达快提卡派 41kg\nMC1(FBA1,FBA2,FBA3) 美速达快提卡派 invalidkg'))
    assert not any(r.status=='重量在允许范围' for r in rows)


def test_duplicate_source_set_and_duplicate_messages_do_not_pass(tmp_path):
    scan=scanned(tmp_path)
    report=parse_reports('MC1(FBA1,FBA2,FBA3) 美速达快提卡派 41kg')
    duplicate=replace(scan,invoices=scan.invoices+(replace(scan.invoices[0],path=tmp_path/'other.xlsx'),))
    assert all(r.status=='匹配冲突' for r in reconcile(duplicate,report))
    repeated=parse_reports('MC1(FBA1,FBA2,FBA3) 美速达快提卡派 41kg\nMC2(FBA1,FBA2,FBA3) 美速达快提卡派 41kg')
    assert all(r.status!='重量在允许范围' for r in reconcile(scan,repeated))


def test_channel_difference_is_visible_and_overweight_filter_still_works(tmp_path):
    scan=scanned(tmp_path)
    row=reconcile(scan,parse_reports('MC1(FBA1,FBA2,FBA3) 美速达美东卡派 41kg'))[0]
    assert row.status=='渠道待核对' and '渠道' in row.message
    row=reconcile(scan,parse_reports('MC1(FBA1,FBA2,FBA3) 美速达美东卡派 42kg'))[0]
    assert row.needs_remeasure and '渠道' in row.message


def test_invalid_source_blocks_weight_verdict(tmp_path):
    scan=scanned(tmp_path)
    scan=replace(scan,invoices=(replace(scan.invoices[0],issues=('同箱尺寸冲突',)),))
    row=reconcile(scan,parse_reports('MC1(FBA1,FBA2,FBA3) 美速达快提卡派 41kg'))[0]
    assert row.status=='源数据异常' and row.difference is None


def test_no_reports_keeps_all_invoices_pending(tmp_path):
    rows=reconcile(scanned(tmp_path),parse_reports(''))
    assert len(rows)==1 and rows[0].status=='待货代报数'


def test_export_keeps_complete_box_snapshot_raw_text_and_numeric_weights(tmp_path):
    scan=scanned(tmp_path)
    raw='MC1(FBA1,FBA2,FBA3) 美速达快提卡派 42kg\n=HYPERLINK("bad")'
    rows=reconcile(scan,parse_reports(raw))
    p=export_results(rows,tmp_path/'核对结果.xlsx',raw_text=raw,source_directory=scan.directory,
                     scanned_at=scan.scanned_at)
    w=load_workbook(p,data_only=False)
    assert w.sheetnames==['货件核对','货箱明细','货代原文']
    s=w['货件核对'];headers=[c.value for c in s[6]]
    assert s.cell(7,headers.index('核准上限(kg)')+1).value==41
    assert s.cell(7,headers.index('货代计费重(kg)')+1).value==42
    assert s.cell(7,headers.index('超限差额(kg)')+1).value==1
    assert w['货箱明细'].max_row==4
    assert w['货代原文']['B3'].value=='=HYPERLINK("bad")'
    assert w['货代原文']['B3'].data_type=='s'
    w.close()


def test_export_cannot_overwrite_any_scanned_invoice(tmp_path):
    scan=scanned(tmp_path); source=scan.invoices[0].path; before=source.read_bytes()
    with pytest.raises(ValueError,match='源发票'):
        export_results([],source,raw_text='',source_directory=scan.directory,
                       protected_paths=[source])
    assert source.read_bytes()==before


def test_export_cannot_overwrite_invoice_in_a_different_batch(tmp_path):
    other=tmp_path/'other';other.mkdir()
    source=write_mc(other/'MC_GYR3_3箱.xlsx');before=source.read_bytes()
    with pytest.raises(ValueError,match='源发票'):
        export_results([],source,raw_text='',source_directory=tmp_path)
    assert source.read_bytes()==before


def test_unknown_and_malformed_reports_survive_export(tmp_path):
    scan=scanned(tmp_path)
    raw='MC99(FBA9) 不同渠道 39kg\nMC100(FBA8) 缺重量'
    rows=reconcile(scan,parse_reports(raw))
    assert len(rows)==3 and any(r.status=='报数异常' for r in rows)
    p=export_results(rows,tmp_path/'异常.xlsx',raw_text=raw,source_directory=scan.directory)
    w=load_workbook(p,data_only=True)
    assert w['货件核对'].max_row==9
    w.close()
