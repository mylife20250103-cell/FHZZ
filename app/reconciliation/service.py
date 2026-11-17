from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from .models import ParseResult, ReconciliationRow, ScanResult


def _channel(value: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value)).casefold()


def reconcile(scan: ScanResult, parsed: ParseResult) -> list[ReconciliationRow]:
    """每份源文件一行；无法唯一关联的报数另外保留，绝不部分匹配。"""
    index = defaultdict(list)
    fba_owners = defaultdict(set)
    for i, invoice in enumerate(scan.invoices):
        if invoice.fba_ids:
            index[invoice.carrier, invoice.fba_ids].append(i)
            for fba in invoice.fba_ids:
                fba_owners[invoice.carrier, fba].add(i)
    # 扫描历史父目录时，旧/新文件集合即使不完全相同，也不能重复占有同一FBA。
    ambiguous = set().union(*(owners for owners in fba_owners.values() if len(owners)>1))
    matched, extra = defaultdict(list), []
    for report in parsed.reports:
        candidates = index.get((report.carrier, report.fba_ids), [])
        if len(candidates) > 1:
            ambiguous.update(candidates)
            extra.append(ReconciliationRow(None, report, '匹配冲突', '多份文件具有同一完整FBA集合，请缩小目录或确认重复文件'))
        elif len(candidates) == 1:
            matched[candidates[0]].append(report)
        else:
            status = '报数异常' if report.issues else '未匹配'
            message = '；'.join(report.issues) if report.issues else '完整FBA集合未匹配；不会按单个FBA或消息顺序关联'
            extra.append(ReconciliationRow(None, report, status, message))
    rows = []
    for i, invoice in enumerate(scan.invoices):
        reports = matched[i]
        if i in ambiguous:
            rows.append(ReconciliationRow(invoice, reports[0] if len(reports)==1 else None,
                '匹配冲突', '多份源文件包含相同FBA/货箱，请选择单个有效批次目录'))
            if len(reports)>1:
                extra.extend(ReconciliationRow(None,r,'报数异常','重复源身份对应多条报数') for r in reports)
        elif len(reports) > 1:
            rows.append(ReconciliationRow(invoice, None, '匹配冲突', '同一文件对应多条报数，请删除重复/冲突报数后重新核对'))
            extra.extend(ReconciliationRow(None, r, '报数异常', '；'.join(r.issues) or '同一文件重复报数') for r in reports)
        elif invoice.issues:
            rows.append(ReconciliationRow(invoice, reports[0] if reports else None,
                                          '源数据异常', '；'.join(invoice.issues)))
        elif not reports:
            rows.append(ReconciliationRow(invoice, None, '待货代报数'))
        else:
            report = reports[0]
            if report.issues:
                rows.append(ReconciliationRow(invoice, report, '报数异常', '；'.join(report.issues)))
                continue
            channel_differs = _channel(invoice.channel) != _channel(report.channel)
            message = '渠道与发票不一致，请核实下单服务' if channel_differs else ''
            exceeds = report.billed_weight > invoice.approved_weight
            status = '需申请重测' if exceeds else ('渠道待核对' if channel_differs else '重量在允许范围')
            rows.append(ReconciliationRow(invoice, report, status, message, exceeds))
    return rows + extra
