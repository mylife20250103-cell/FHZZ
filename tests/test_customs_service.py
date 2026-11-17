from pathlib import Path

import pytest

from tests.test_customs_rules import row, rule_file
from tests.test_customs_workbooks import mc_invoice


def scanned(tmp_path, rows=None):
    from app.customs.service import scan_batch
    root = tmp_path / "batch"
    root.mkdir()
    mc_invoice(root / "MC.xlsx")
    rules = rule_file(tmp_path / "rules.xlsx", rows or [row()])
    return scan_batch(root, rules, "MC", "US", 95)


def test_revision_keeps_whole_batch_original_names_and_source_bytes(tmp_path):
    from app.customs.service import apply_revision, scan_batch
    scan = scanned(tmp_path)
    sub = scan.root / "warehouse"
    sub.mkdir()
    mc_invoice(sub / "MC.xlsx", name="未匹配产品")
    scan = scan_batch(scan.root, scan.rules.path, "MC", "US", 95)
    originals = {p.relative_to(scan.root): p.read_bytes() for p in scan.root.rglob("*.xlsx")}
    dest = apply_revision(scan, {scan.rows[0].key: 0}, tmp_path / "out")
    assert (dest / "上传发票" / "MC.xlsx").exists()
    assert (dest / "上传发票" / "warehouse" / "MC.xlsx").read_bytes() == originals[Path("warehouse/MC.xlsx")]
    assert (dest / "修改记录" / "修改记录.json").exists()
    for relative, raw in originals.items():
        assert (scan.root / relative).read_bytes() == raw


@pytest.mark.parametrize("mutation", ["change", "add", "delete", "rules"])
def test_stale_preview_cannot_publish(tmp_path, mutation):
    from app.customs.service import apply_revision
    scan = scanned(tmp_path)
    if mutation == "change":
        mc_invoice(scan.root / "MC.xlsx", name="已变化")
    elif mutation == "add":
        mc_invoice(scan.root / "new.xlsx")
    elif mutation == "delete":
        (scan.root / "MC.xlsx").unlink()
    else:
        rule_file(scan.rules.path, [row(after="已变化")])
    with pytest.raises(ValueError, match="变化|重新扫描"):
        apply_revision(scan, {scan.rows[0].key: 0}, tmp_path / "out")
    assert not list((tmp_path / "out").rglob("修改记录.json"))


def test_unselected_conflicting_match_is_copied_unchanged(tmp_path):
    from app.customs.service import apply_revision
    scan = scanned(tmp_path, [row(), row("美2", after="头饰")])
    assert len(scan.rows[0].candidates) == 2
    dest = apply_revision(scan, {}, tmp_path / "out")
    assert (dest / "上传发票" / "MC.xlsx").read_bytes() == (scan.root / "MC.xlsx").read_bytes()


def test_failure_never_publishes_complete_revision(tmp_path, monkeypatch):
    from app.customs import service
    scan = scanned(tmp_path)
    def fail(*args):
        raise OSError("模拟磁盘写入失败")
    monkeypatch.setattr(service, "write_invoice", fail)
    with pytest.raises(OSError):
        service.apply_revision(scan, {scan.rows[0].key: 0}, tmp_path / "out")
    assert not list((tmp_path / "out").rglob("修改记录.json"))
    assert (scan.root / "MC.xlsx").exists()


def test_source_output_overlap_and_arbitrary_selection_rejected(tmp_path):
    from app.customs.service import apply_revision
    scan = scanned(tmp_path)
    with pytest.raises(ValueError):
        apply_revision(scan, {scan.rows[0].key: 0}, scan.root / "out")
    with pytest.raises(ValueError):
        apply_revision(scan, {"forged-row": 0}, tmp_path / "out")
    with pytest.raises(ValueError):
        apply_revision(scan, {scan.rows[0].key: -1}, tmp_path / "out")


def test_auto_carrier_pins_detected_template_for_revision(tmp_path):
    from app.customs.service import scan_batch
    original = scanned(tmp_path)
    auto = scan_batch(original.root, original.rules.path, 'AUTO', 'US', 95)
    assert auto.carrier == 'MC'
    assert auto.invoices[0].carrier == 'MC'


def test_auto_carrier_rejects_mixed_carrier_batch(tmp_path):
    import shutil
    from app.customs.service import scan_batch
    original = scanned(tmp_path)
    sample = Path(r'I:\OneDrive\OneDrive - Lion\【采购仓储】\【发货单】\【发票合并】\发票系统\合并结果\20260904\20260904-B0001\KYD_BJC1_1箱.xls')
    if not sample.exists():
        pytest.skip('缺少快越达上传样本')
    shutil.copyfile(sample, original.root / sample.name)
    with pytest.raises(ValueError, match='不同物流商|混合货代'):
        scan_batch(original.root, original.rules.path, 'AUTO', 'US', 95)


def test_uploaded_kyd_batch_can_publish_complete_revision_to_test_directory(tmp_path):
    import hashlib
    import olefile
    from app.customs.service import apply_revision, scan_batch
    from app.customs.workbooks import read_invoice
    root = Path(r'I:\OneDrive\OneDrive - Lion\【采购仓储】\【发货单】\【发票合并】\发票系统\合并结果\20260904\20260904-B0001')
    rules = Path(r'I:\OneDrive\OneDrive - Lion\【采购仓储】\【发货单】\【发票合并】\发票系统\报关信息替换\途鱼报关信息_20261021.xlsx')
    if not root.exists() or not rules.exists():
        pytest.skip('缺少本机快越达历史批次或用户规则表')
    scan = scan_batch(root, rules, 'AUTO', 'US', 95)
    assert scan.carrier == 'KYD'
    assert len(scan.invoices) == 19
    assert len(scan.rows) == 115
    selected = {r.key: 0 for r in scan.rows if len(r.candidates) == 1}
    assert selected, '样本未命中规则，不能把仅复制文件当作修改验证'
    result = apply_revision(scan, selected, tmp_path / 'revisions')
    assert len(list((result / '上传发票').rglob('*.xls'))) == 19
    for invoice in scan.invoices:
        relative = invoice.path.relative_to(root)
        revised = result / '上传发票' / relative
        changes = {r.line.row: r.candidates[0].rule.after for r in scan.rows if r.relative == relative.as_posix() and r.key in selected}
        actual = read_invoice(revised, 'KYD')
        assert {r.row: r.values for r in actual.lines} == {r.row: changes.get(r.row, r.values) for r in invoice.lines}
        with olefile.OleFileIO(invoice.path) as before, olefile.OleFileIO(revised) as after:
            assert before.listdir() == after.listdir()
            assert not any('CompObj' in part for stream in after.listdir() for part in stream)
        if not changes:
            assert hashlib.sha256(revised.read_bytes()).hexdigest() == dict(scan.hashes)[relative.as_posix()]
    for relative, original_hash in scan.hashes:
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == original_hash
