"""按仓库生成建议，确认后在隔离副本发布整批，不回写原发票。"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from app.channel_rules.catalog import load_catalog
from app.channel_rules.invoices import load_countries, read_head, valid_service_text, write_channel
from app.channel_rules.models import CARRIERS, DELIVERIES, TAXES, Catalog, ChannelEdit, ChannelScan, digest
from app.channel_rules.rules import match_rules, read_rules, tax_code, text
from app.customs.service import _reject_links, inventory
from app.invoice_config import CENTRAL_ADDRESS_PATH


def verify_snapshot(scan: ChannelScan, catalog_path: Path | None = None):
    try:
        for path in (scan.root, scan.rules.path, scan.address_path):
            _reject_links(path)
        if (digest(scan.rules.path) != scan.rules.sha256 or inventory(scan.root) != scan.hashes
                or digest(scan.address_path) != scan.address_sha256
                or catalog_path is not None and load_catalog(catalog_path).version != scan.catalog.version):
            raise ValueError()
    except (OSError, ValueError):
        raise ValueError('发票、规则、地址库或服务目录已变化/不可访问，请重新扫描') from None


def scan_batch(root: Path, rules_path: Path, catalog: Catalog, carrier='AUTO', manual_cell='', address_path=None) -> ChannelScan:
    root, rules_path = Path(root).absolute(), Path(rules_path).absolute()
    _reject_links(root)
    if '修改记录' in root.parts or any(p.startswith('.进行中_') for p in root.parts):
        raise ValueError('不能扫描修改记录、原件快照或未发布暂存目录，请选择正式上传发票')
    if (root / '上传发票').is_dir():
        root = root / '上传发票'
    _reject_links(root)
    _reject_links(rules_path)
    address_path = Path(address_path or CENTRAL_ADDRESS_PATH).absolute()
    _reject_links(address_path)
    address_sha256 = digest(address_path)
    countries = load_countries(address_path)
    rules = read_rules(rules_path)
    hashes = inventory(root)
    if any('修改记录' in Path(relative).parts or any(p.startswith('.进行中_') for p in Path(relative).parts) for relative, _ in hashes):
        raise ValueError('目录包含修改记录或未发布结果，请选择单个批次的上传发票目录')
    heads = []
    for relative, _ in hashes:
        head = read_head(root / relative, countries, manual_cell)
        if carrier != 'AUTO' and head.carrier != carrier:
            raise ValueError(f'{relative}实际物流商为{CARRIERS[head.carrier]}，与所选物流商不符')
        if not head.has_products:
            raise ValueError(f'{relative}没有产品明细，请勿将空白模板当作发票')
        heads.append(replace(head, relative=relative))
    if len({head.carrier for head in heads}) != 1 or len({head.country for head in heads}) != 1:
        raise ValueError('批次包含不同物流商或国家，请分别选择，禁止混国处理')
    scan = ChannelScan(root.resolve(), rules, catalog, tuple(heads), hashes, address_path.resolve(), address_sha256)
    verify_snapshot(scan)
    return scan


def choose_rule(edit: ChannelEdit, rule, catalog: Catalog):
    service = catalog.find(rule.provider_id, rule.service_code)
    if service is None or service.carrier_code != edit.head.carrier:
        raise ValueError('规则服务不在该账号的有效目录中，请同步或修正规则')
    valid_service_text(rule.invoice_value)
    edit.chosen = rule
    edit.provider_id, edit.service_code, edit.new_value = rule.provider_id, rule.service_code, rule.invoice_value
    edit.status, edit.manual = '唯一匹配' if len(edit.candidates) == 1 else '已选候选', False


def suggest_edit(scan: ChannelScan, head, category, tax, delivery) -> ChannelEdit:
    edit = ChannelEdit(head, text(category), tax_code(tax), text(delivery))
    edit.candidates = match_rules(scan.rules.rules, head.carrier, head.country, head.warehouse, edit.category, edit.tax, edit.delivery)
    if not edit.category or edit.tax not in TAXES or edit.delivery not in DELIVERIES:
        edit.status = '请补齐渠道、税费和派送方式'
    elif not edit.candidates:
        edit.status = '未配置规则，可人工选择已核实的服务'
    elif len(edit.candidates) > 1:
        edit.status = '多条规则，请选择候选'
    else:
        try:
            choose_rule(edit, edit.candidates[0], scan.catalog)
        except ValueError as exc:
            edit.status = str(exc)
    return edit


def validate_edit(scan: ChannelScan, edit: ChannelEdit):
    if edit.head not in scan.heads:
        raise ValueError('修改行不属于本次预览')
    if not edit.category or edit.tax not in TAXES or edit.delivery not in DELIVERIES:
        raise ValueError('所选行缺少渠道、税费或派送条件')
    service = scan.catalog.find(edit.provider_id, edit.service_code)
    if service is None or service.carrier_code != edit.head.carrier:
        raise ValueError('所选行没有该货代账号下的有效服务')
    valid_service_text(edit.new_value)
    if not edit.manual:
        matches = match_rules(scan.rules.rules, edit.head.carrier, edit.head.country, edit.head.warehouse,
                             edit.category, edit.tax, edit.delivery)
        if edit.chosen not in matches or (edit.provider_id, edit.service_code, edit.new_value) != (
                edit.chosen.provider_id, edit.chosen.service_code, edit.chosen.invoice_value):
            raise ValueError('建议与规则不一致，请重新扫描或明确人工调整')


def apply_revision(scan: ChannelScan, edits: list[ChannelEdit], output_root: Path, *, catalog_path: Path | None = None) -> Path:
    selected = [edit for edit in edits if edit.selected]
    if not selected:
        raise ValueError('请先勾选要修改的发票')
    if len({e.head.relative for e in selected}) != len(selected):
        raise ValueError('同一文件重复选择，停止处理')
    for edit in selected:
        validate_edit(scan, edit)
    verify_snapshot(scan, catalog_path)
    output_root = Path(output_root).absolute()
    _reject_links(output_root)
    output_root = output_root.resolve()
    if output_root.is_relative_to(scan.root) or scan.root.is_relative_to(output_root):
        raise ValueError('输出根目录与源目录不能相同或互相包含')
    revision = datetime.now().strftime('%H%M%S') + '_' + uuid.uuid4().hex[:12]
    batch = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', scan.root.parent.name if scan.root.name == '上传发票' else scan.root.name)[:60].rstrip('. ') or '批次'
    parent = output_root / datetime.now().strftime('%Y%m%d') / scan.heads[0].carrier / ('批次_' + batch)
    _reject_links(parent)
    parent.mkdir(parents=True, exist_ok=True)
    stage, final = parent / ('.进行中_' + revision), parent / ('修订_' + revision)
    stage.mkdir()
    indexed = {e.head.relative: e for e in selected}
    try:
        uploads, reports = stage / '上传发票', stage / '修改记录'
        uploads.mkdir(); reports.mkdir()
        output_hashes, changes = {}, []
        for relative, expected_hash in scan.hashes:
            source, dest = scan.root / relative, uploads / relative
            raw = source.read_bytes()
            import hashlib
            if hashlib.sha256(raw).hexdigest() != expected_hash:
                raise ValueError('源件已变化，请重新扫描')
            dest.parent.mkdir(parents=True, exist_ok=True)
            edit = indexed.get(relative)
            if edit:
                original = reports / '原件' / relative
                original.parent.mkdir(parents=True, exist_ok=True)
                original.write_bytes(raw)
                write_channel(original, dest, edit.head, edit.new_value)
                changes.append({'file': relative, 'sheet': edit.head.sheet, 'cell': edit.head.cell,
                                'carrier': edit.head.carrier, 'country': edit.head.country, 'warehouse': edit.head.warehouse,
                                'before': edit.head.current_value, 'after': edit.new_value,
                                'category': edit.category, 'tax': edit.tax, 'delivery': edit.delivery,
                                'provider_id': edit.provider_id, 'service_code': edit.service_code,
                                'manual': edit.manual, 'rule_row': edit.chosen.row if edit.chosen and not edit.manual else None})
            else:
                dest.write_bytes(raw)
                if digest(dest) != expected_hash:
                    raise ValueError('未修改文件复制校验失败')
            output_hashes[relative] = digest(dest)
        verify_snapshot(scan, catalog_path)
        record = {'created_at': datetime.now().astimezone().isoformat(), 'source': str(scan.root),
                  'rules': str(scan.rules.path), 'rules_sha256': scan.rules.sha256,
                  'catalog_version': scan.catalog.version, 'address_sha256': scan.address_sha256,
                  'source_sha256': dict(scan.hashes), 'output_sha256': output_hashes, 'changes': changes,
                  'note': '仅修改服务格；税号、交税方式等其他表格字段未自动改动，请核对适用条件。'}
        (reports / '渠道修改记录.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        verify_snapshot(scan, catalog_path)
        stage.rename(final)
        return final
    except Exception:
        try:
            (stage / '未完成说明.txt').write_text('此目录未发布，不能上传。原始发票未被本功能修改。', encoding='utf-8')
        except OSError:
            pass
        raise
