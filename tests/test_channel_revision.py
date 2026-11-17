import json
import shutil
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook

from tests.test_channel_rules import catalog, rule_file


def mc_file(path, warehouse='SCK4'):
    book = Workbook()
    sheet = book.active
    sheet.title = '模板'
    sheet['A2'], sheet['B2'] = '服务*', '原服务'
    sheet['A3'], sheet['B3'] = '地址库编码', warehouse
    sheet['C5'] = '=1+2'
    for column, label in {7:'产品英文品名*',8:'产品中文品名*',11:'产品材质*',12:'产品海关编码*'}.items():
        sheet.cell(17,column,label)
    sheet['H18'], sheet['G18'] = '发箍', 'headband'
    book.create_sheet('渠道列表')
    book.create_sheet('地址库')
    book.save(path)
    book.close()
    return path


def addresses(path):
    book = Workbook()
    for sheet_name,code_col,country_col in [('迈创地址库',2,13),('快越达地址库',1,12),('皓鹏地址库',1,13)]:
        sheet=book.create_sheet(sheet_name)
        sheet.cell(1,code_col,'地址编码*')
        sheet.cell(1,country_col,'国家*')
        for index,(wh,country) in enumerate([('SCK4','US'),('GYR3','US'),('YVR2','CA'),('BJC1','US'),('DTM2-44145','DE')],2):
            sheet.cell(index,code_col,wh)
            sheet.cell(index,country_col,country)
    book.save(path)
    book.close()
    return path


def scan_fixture(tmp_path, two=False):
    from app.channel_rules.service import scan_batch
    root=tmp_path/'batch';root.mkdir()
    mc_file(root/'任意重命名.xlsx')
    if two:
        mc_file(root/'other.xlsx','GYR3')
    rules=rule_file(tmp_path/'rules.xlsx')
    address=addresses(tmp_path/'address.xlsx')
    return scan_batch(root,rules,catalog(),address_path=address)


def test_head_identifies_from_content_and_rejects_non_service_override(tmp_path):
    from app.channel_rules.invoices import read_head
    path=mc_file(tmp_path/'KYD_misleading_name.xlsx')
    head=read_head(path, {'MC': {'SCK4':'US'}})
    assert (head.carrier,head.warehouse,head.country,head.sheet,head.cell,head.current_value)==('MC','SCK4','US','模板','B2','原服务')
    with pytest.raises(ValueError,match='服务|渠道'):
        read_head(path, {'MC': {'SCK4':'US'}}, manual_cell='B3')
    with pytest.raises(ValueError):
        read_head(path, {'MC': {}})


def test_formula_target_and_source_metadata_are_rejected(tmp_path):
    from app.channel_rules.invoices import read_head
    path=mc_file(tmp_path/'invoice.xlsx')
    book=load_workbook(path);book['模板']['B2']='=A1';book.save(path);book.close()
    with pytest.raises(ValueError,match='公式'):
        read_head(path,{'MC':{'SCK4':'US'}})


def test_service_text_in_neighboring_value_cannot_authorize_wrong_cell(tmp_path):
    from app.channel_rules.invoices import read_head
    path=mc_file(tmp_path/'invoice.xlsx')
    with pytest.raises(ValueError,match='服务|渠道'):
        read_head(path,{'MC':{'SCK4':'US'}},manual_cell='C2')


def test_merged_non_anchor_cell_cannot_be_selected_as_service(tmp_path):
    from app.channel_rules.invoices import read_head
    path=mc_file(tmp_path/'invoice.xlsx')
    book=load_workbook(path);book['模板'].merge_cells('B2:C2');book.save(path);book.close()
    with pytest.raises(ValueError,match='合并'):
        read_head(path,{'MC':{'SCK4':'US'}},manual_cell='C2')


def test_direct_country_conflict_is_rejected(tmp_path):
    from app.channel_rules.invoices import read_head
    path=mc_file(tmp_path/'invoice.xlsx')
    book=load_workbook(path);book['模板']['A12']='国家*';book['模板']['B12']='CA';book.save(path);book.close()
    with pytest.raises(ValueError,match='国家'):
        read_head(path,{'MC':{'SCK4':'US'}})


@pytest.mark.parametrize('country,expected',[('Canada','CA'),('United States of America','US')])
def test_existing_central_country_aliases_remain_compatible(tmp_path,country,expected):
    from app.channel_rules.invoices import load_countries,read_head
    address=addresses(tmp_path/'address.xlsx')
    book=load_workbook(address);book['迈创地址库'].cell(2,13,country);book.save(address);book.close()
    path=mc_file(tmp_path/'invoice.xlsx')
    assert read_head(path,load_countries(address)).country==expected


def test_duplicate_warehouse_with_missing_country_remains_unresolved(tmp_path):
    from app.channel_rules.invoices import load_countries,read_head
    address=addresses(tmp_path/'address.xlsx')
    book=load_workbook(address);book['迈创地址库'].cell(20,2,'SCK4');book.save(address);book.close()
    with pytest.raises(ValueError,match='唯一国家'):
        read_head(mc_file(tmp_path/'invoice.xlsx'),load_countries(address))
    path=mc_file(tmp_path/'source.xlsx')
    book=load_workbook(path);book.create_sheet('_SystemMeta');book.save(path);book.close()
    with pytest.raises(ValueError,match='源发票'):
        read_head(path,{'MC':{'SCK4':'US'}})


def test_scanning_rejects_mixed_countries_and_wrong_carrier(tmp_path):
    from app.channel_rules.service import scan_batch
    scan=scan_fixture(tmp_path)
    mc_file(scan.root/'CA.xlsx','YVR2')
    with pytest.raises(ValueError,match='国家|混国'):
        scan_batch(scan.root,scan.rules.path,catalog(),address_path=scan.address_path)
    (scan.root/'CA.xlsx').unlink()
    with pytest.raises(ValueError,match='物流商'):
        scan_batch(scan.root,scan.rules.path,catalog(),carrier='KYD',address_path=scan.address_path)


def test_revision_is_per_file_copies_unselected_and_changes_only_service_cell(tmp_path):
    from app.channel_rules.service import suggest_edit,apply_revision
    scan=scan_fixture(tmp_path,two=True)
    head=next(h for h in scan.heads if h.warehouse=='SCK4')
    edit=suggest_edit(scan,head,'美国合德','包税','卡派')
    assert edit.status=='唯一匹配' and edit.new_value=='美速达快提卡派'
    assert not edit.selected
    edit.selected=True
    originals={r:(scan.root/r).read_bytes() for r,_ in scan.hashes}
    output=apply_revision(scan,[edit],tmp_path/'output')
    assert all((scan.root/r).read_bytes()==raw for r,raw in originals.items())
    for relative,raw in originals.items():
        dest=output/'上传发票'/relative
        if relative != head.relative:
            assert dest.read_bytes()==raw
        else:
            with ZipFile(scan.root/relative) as a,ZipFile(dest) as b:
                assert a.namelist()==b.namelist()
                for member in a.namelist():
                    if member!='xl/worksheets/sheet1.xml':assert a.read(member)==b.read(member)
            book=load_workbook(dest)
            assert book['模板']['B2'].value=='美速达快提卡派'
            assert book['模板']['C5'].value=='=1+2'
            assert book['模板']['B3'].value=='SCK4'
            book.close()
    audit=json.loads((output/'修改记录'/'渠道修改记录.json').read_text(encoding='utf-8'))
    assert audit['changes'][0]['provider_id']=='MC.A'
    assert audit['changes'][0]['tax']=='包税'
    assert (output/'修改记录'/'原件'/head.relative).read_bytes()==originals[head.relative]


@pytest.mark.parametrize('changed',['invoice','added','rules','address','catalog'])
def test_stale_preview_cannot_publish(tmp_path,changed):
    from app.channel_rules.service import suggest_edit,apply_revision
    from app.channel_rules.catalog import save_catalog
    from app.channel_rules.models import Catalog
    scan=scan_fixture(tmp_path)
    edit=suggest_edit(scan,scan.heads[0],'美国合德','包税','卡派');edit.selected=True
    cache=tmp_path/'cache.json';save_catalog(cache,catalog())
    if changed=='invoice':mc_file(scan.heads[0].path,'GYR3')
    elif changed=='added':mc_file(scan.root/'added.xlsx')
    elif changed=='rules':scan.rules.path.write_bytes(b'changed')
    elif changed=='address':scan.address_path.write_bytes(b'changed')
    else:save_catalog(cache,Catalog())
    with pytest.raises(ValueError,match='变化|重扫|重新扫描'):
        apply_revision(scan,[edit],tmp_path/'output',catalog_path=cache)
    assert not list((tmp_path/'output').rglob('修订_*'))


def test_conflict_and_retired_service_cannot_be_silently_selected(tmp_path):
    from app.channel_rules.service import suggest_edit,apply_revision
    from app.channel_rules.models import Catalog
    scan=scan_fixture(tmp_path)
    retired=replace(scan,catalog=Catalog())
    edit=suggest_edit(retired,retired.heads[0],'美国合德','包税','卡派')
    assert not edit.new_value and not edit.selected
    edit.selected=True
    with pytest.raises(ValueError):apply_revision(retired,[edit],tmp_path/'output')


def test_failed_copy_never_changes_sources_or_publishes_result(tmp_path,monkeypatch):
    from app.channel_rules.service import suggest_edit,apply_revision
    scan=scan_fixture(tmp_path)
    edit=suggest_edit(scan,scan.heads[0],'美国合德','包税','卡派');edit.selected=True
    original=scan.heads[0].path.read_bytes()
    def fail(*args):raise OSError('simulated disk failure')
    monkeypatch.setattr('app.channel_rules.service.write_channel',fail)
    with pytest.raises(OSError):apply_revision(scan,[edit],tmp_path/'output')
    assert scan.heads[0].path.read_bytes()==original
    assert not list((tmp_path/'output').rglob('修订_*'))


@pytest.mark.parametrize('kind',['records','parent','unfinished'])
def test_audit_originals_and_unpublished_directories_are_not_upload_sources(tmp_path,kind):
    from app.channel_rules.service import scan_batch
    rules=rule_file(tmp_path/'rules.xlsx');address=addresses(tmp_path/'addresses.xlsx')
    if kind=='records':
        root=tmp_path/'revision'/'修改记录'/'原件';root.mkdir(parents=True)
        mc_file(root/'original.xlsx')
    elif kind=='parent':
        root=tmp_path/'results';(root/'revision'/'修改记录'/'原件').mkdir(parents=True)
        mc_file(root/'revision'/'修改记录'/'原件'/'original.xlsx')
    else:
        root=tmp_path/'.进行中_abc'/'上传发票';root.mkdir(parents=True)
        mc_file(root/'original.xlsx')
    with pytest.raises(ValueError,match='修改记录|暂存|未发布|单个'):
        scan_batch(root,rules,catalog(),address_path=address)


def test_revision_root_selects_upload_files_and_not_its_original_snapshots(tmp_path):
    from app.channel_rules.service import scan_batch
    root=tmp_path/'revision';(root/'上传发票').mkdir(parents=True);(root/'修改记录'/'原件').mkdir(parents=True)
    mc_file(root/'上传发票'/'new.xlsx');mc_file(root/'修改记录'/'原件'/'old.xlsx')
    rules=rule_file(tmp_path/'rules.xlsx');address=addresses(tmp_path/'addresses.xlsx')
    scan=scan_batch(root,rules,catalog(),address_path=address)
    assert [head.relative for head in scan.heads]==['new.xlsx']
    assert scan.root==root/'上传发票'


@pytest.mark.parametrize('carrier,template,sheet,cell,warehouse,country',[
    ('KYD',r'I:\OneDrive\OneDrive - Lion\【采购仓储】\【发货单】\【发票合并】\发票系统\模板\快越达发票模版.xls','模板','B4','BJC1','US'),
    ('HP',r'I:\OneDrive\OneDrive - Lion\【采购仓储】\【发货单】\发货单各源抓取\皓鹏国际-单票下单模板.xls','单票下单-填写表','B1','DTM2-44145','DE'),
])
def test_real_xls_service_patch_preserves_other_streams_and_cells(tmp_path,carrier,template,sheet,cell,warehouse,country):
    from app.channel_rules.invoices import read_head,write_channel
    from app.channel_rules.models import digest
    import olefile,xlrd
    template=Path(template)
    if not template.exists():pytest.skip('缺少真实模板，仍需货代上传验收')
    before=digest(template)
    source=tmp_path/'original.xls';shutil.copyfile(template,source)
    head=read_head(source,{carrier:{warehouse:country}})
    assert (head.carrier,head.cell)==(carrier,cell)
    dest=tmp_path/'revised.xls'
    write_channel(source,dest,head,'已确认的新服务-卡派')
    left=xlrd.open_workbook(str(source),formatting_info=True)
    right=xlrd.open_workbook(str(dest),formatting_info=True)
    target_row=int(cell[1:])-1
    for name in left.sheet_names():
        a,b=left.sheet_by_name(name),right.sheet_by_name(name)
        for r in range(a.nrows):
            for c in range(a.ncols):
                if name==sheet and (r,c)==(target_row,1):
                    assert b.cell_value(r,c)=='已确认的新服务-卡派'
                else:assert a.cell_value(r,c)==b.cell_value(r,c)
    left.release_resources();right.release_resources()
    with olefile.OleFileIO(source) as a,olefile.OleFileIO(dest) as b:
        assert a.listdir()==b.listdir()
        for stream in a.listdir():
            if stream!=['Workbook']:assert a.openstream(stream).read()==b.openstream(stream).read()
    assert digest(template)==before
