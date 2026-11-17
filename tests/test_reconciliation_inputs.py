from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from app.reconciliation.invoices import scan_directory, suggest_directory
from app.reconciliation.parser import parse_reports


MC_HEADERS = ['货箱编号*', 'PO Number', '货箱重量(KG)*', '货箱长度(CM)*',
              '货箱宽度(CM)*', '货箱高度(CM)*']


def write_mc(path, boxes=None, *, channel='美速达快提卡派', warehouse='GYR3', count=None):
    boxes = boxes if boxes is not None else [
        ('FBA1U000001', 14.6, 40, 40, 40),
        ('FBA2U000001', 7.5, 40, 35, 35),
        ('FBA3U000001', 13.9, 60, 40, 40),
    ]
    w = Workbook(); s = w.active; s.title = '模板'
    s['B2'], s['B3'] = channel, warehouse
    s['B16'] = count if count is not None else len({b[0] for b in boxes})
    for c, value in enumerate(MC_HEADERS, 1): s.cell(17, c, value)
    for r, (number, weight, length, width, height) in enumerate(boxes, 18):
        for c, value in enumerate([number, 'PO', weight, length, width, height], 1):
            s.cell(r, c, value)
    w.save(path); w.close()
    return path


def test_supplied_seventeen_reports_and_notice():
    text = (Path(__file__).parent / 'fixtures/mc_reconciliation_example.txt').read_text(encoding='utf-8')
    result = parse_reports(text)
    assert len(result.reports) == 17
    assert len(result.ignored_lines) == 1
    assert all(not r.issues for r in result.reports)
    assert result.reports[0].order_number == 'MC010295345'
    assert set(result.reports[0].fba_ids) == {'FBA19W1Y2BQ0', 'FBA19W236CYF'}
    assert result.reports[14].billed_weight == D('129')


def test_fullwidth_parentheses_uppercase_units_and_no_space_before_weight():
    r = parse_reports('MC123（FBA1、FBA2） 美速达快提卡派39KG').reports[0]
    assert not r.issues and r.billed_weight == D('39')
    assert r.channel == '美速达快提卡派'


@pytest.mark.parametrize('line', [
    'MC1(FBA1) 渠道 -1kg', 'MC1(FBA1) 渠道 0kg', 'MC1(FBA1) 渠道 NaNkg',
    'MC1(FBA1,FBA1) 渠道 39kg', 'MC1(FBA1U000001) 渠道 39kg',
    'MC1(FBA1) 渠道', 'MC1() 渠道 3kg', 'MC1(FBA1,WRONG) 渠道 39kg',
])
def test_bad_report_remains_visible(line):
    result = parse_reports(line)
    assert len(result.reports) == 1 and result.reports[0].issues


def test_duplicate_orders_and_overlapping_fbas_block_both_reports():
    for text in ['MC1(FBA1) 渠道 3kg\nMC1(FBA2) 渠道 4kg',
                 'MC1(FBA1) 渠道 3kg\nMC2(FBA1,FBA2) 渠道 4kg']:
        assert all(r.issues for r in parse_reports(text).reports)


def test_malformed_report_keeps_identity_for_duplicate_detection():
    result=parse_reports('MC1(FBA1) channel 10kg\nMC1(FBA1) channel invalidkg')
    assert all(r.order_number=='MC1' and r.fba_ids==('FBA1',) for r in result.reports)
    assert all(any('重复' in issue for issue in r.issues) for r in result.reports)


def test_read_mc_deduplicates_products_and_uses_whole_shipment_max(tmp_path):
    p = write_mc(tmp_path/'MC_GYR3_3箱.xlsx')
    before = p.read_bytes()
    inv = scan_directory(tmp_path).invoices[0]
    assert not inv.issues
    assert inv.total_real == D('36')
    assert inv.tolerance_volume == D('40.159')
    assert inv.estimated_weight == D('36') and inv.approved_weight == D('41')
    assert len(inv.cartons) == 3 and len(inv.fba_ids) == 3
    assert p.read_bytes() == before
    boxes = [('FBA1U000001', 8.2, 40, 30, 30)] * 2
    write_mc(tmp_path/'MC_GYR3_1箱.xlsx', boxes)
    found = next(i for i in scan_directory(tmp_path).invoices if i.path.name.endswith('1箱.xlsx'))
    assert len(found.cartons) == 1 and found.total_real == D('8.2')


@pytest.mark.parametrize('boxes,count', [
    ([('FBA1U000001',8,40,30,30), ('FBA1U000001',9,40,30,30)],1),
    ([('FBA1U000001',8,None,30,30)],1),
    ([('FBA1U000001',8,0,30,30)],1),
    ([('not-a-carton',8,40,30,30)],1),
    ([('FBA1U000001',8,40,30,30)],2),
])
def test_bad_box_measurements_or_counts_are_not_calculated(tmp_path,boxes,count):
    write_mc(tmp_path/f'MC_GYR3_{count}箱.xlsx',boxes,count=count)
    inv = scan_directory(tmp_path).invoices[0]
    assert inv.issues and inv.approved_weight is None


def test_exact_integer_bound_does_not_gain_an_extra_kilogram(tmp_path):
    boxes=[(f'FBA{i}U000001',10,38,38,38) for i in (1,2,3)]
    write_mc(tmp_path/'MC_GYR3_3箱.xlsx',boxes)
    inv=scan_directory(tmp_path).invoices[0]
    assert inv.tolerance_volume==D('32')
    assert inv.approved_weight==D('32')


def test_header_and_warehouse_mismatch_visible(tmp_path):
    p = write_mc(tmp_path/'MC_GYR3_3箱.xlsx',warehouse='IND9')
    assert scan_directory(tmp_path).invoices[0].issues
    from openpyxl import load_workbook
    w = load_workbook(p); w['模板']['C17'] = '产品重量'; w.save(p); w.close()
    assert any('表头' in s for s in scan_directory(tmp_path).invoices[0].issues)


def test_corrupt_files_do_not_hide_good_ones_and_lock_files_skipped(tmp_path):
    write_mc(tmp_path/'MC_GYR3_3箱.xlsx')
    (tmp_path/'MC_IND9_1箱.xlsx').write_bytes(b'broken')
    (tmp_path/'~$MC_GYR3_3箱.xlsx').write_bytes(b'lock')
    (tmp_path/'content_merge_diagnose.txt').write_text('note')
    result=scan_directory(tmp_path)
    assert len(result.invoices)==2
    assert sum(bool(i.issues) for i in result.invoices)==1


def test_kyd_columns_using_read_only_xls_reader(tmp_path,monkeypatch):
    import xlrd
    cells={(3,1):'K18美西稳速达-卡派-包税',(4,1):'CLT2',(25,1):3}
    for col,header in [(0,'货箱编号（FBA）*'),(14,'货箱重量(KG)*'),(15,'货箱长度(CM)*'),
                       (16,'货箱宽度(CM)*'),(17,'货箱高度(CM)*')]: cells[28,col]=header
    for row,weight in enumerate([18.7,18.2,16.9],29):
        for col,val in [(0,f'FBA{row}U000001'),(14,weight),(15,50),(16,40),(17,40)]: cells[row,col]=val
    sheet=SimpleNamespace(nrows=32,ncols=20,cell_value=lambda r,c:cells.get((r,c),''))
    released=[]
    monkeypatch.setattr(xlrd,'open_workbook',lambda *a,**k:SimpleNamespace(
        sheet_by_name=lambda name:sheet,release_resources=lambda:released.append(True)))
    (tmp_path/'KYD_CLT2_3箱.xls').write_bytes(b'fixture-reader')
    inv=scan_directory(tmp_path).invoices[0]
    assert not inv.issues and inv.approved_weight == D('54')
    assert inv.total_real == D('53.8') and inv.tolerance_volume == D('45.864')
    assert released


def test_default_directory_uses_todays_latest_success_and_ignores_failures(tmp_path):
    import json
    outputs=tmp_path/'outputs'; batches=tmp_path/'batches'
    for n,status in [(1,'CONTENT_MERGED'),(2,'COMPLETED'),(3,'MERGE_PLAN_READY')]:
        name=f'20261117-B{n:04d}'
        folder=outputs/'20261117'/name;folder.mkdir(parents=True)
        (folder/'MC_GYR3_1箱.xlsx').write_bytes(b'placeholder')
        state=batches/'20261117'/name;state.mkdir(parents=True)
        (state/'status.json').write_text(json.dumps({'Status':status,'UpdatedAt':str(n)}))
    assert suggest_directory(outputs,batches,'20261117').name=='20261117-B0002'
