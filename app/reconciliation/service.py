from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from .models import ParseResult, ReconciliationRow, ScanResult


def _channel(value: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value)).casefold()


def reconcile(scan: ScanResult, parsed: ParseResult) -> list[ReconciliationRow]:
    """完整集合优先；迈创/皓鹏可按全部已列FBA唯一指向的发票辅助关联，按整票核算。"""
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
        if not candidates and report.carrier in {'MC', 'HP'} and report.fba_ids:
            # 所有已列FBA必须属于同一文件；任意相交、重量或消息顺序均不能作为关联依据。
            owners = [fba_owners.get((report.carrier, fba), set()) for fba in report.fba_ids]
            candidates = sorted(set.intersection(*owners))
        if len(candidates) > 1:
            ambiguous.update(candidates)
            extra.append(ReconciliationRow(None, report, '匹配冲突', '报数FBA同时指向多份文件，请缩小目录或确认重复文件'))
        elif len(candidates) == 1:
            matched[candidates[0]].append(report)
        else:
            status = '报数异常' if report.issues else '未匹配'
            message = '；'.join(report.issues) if report.issues else '报数中列出的FBA未能全部对应同一份同货代发票，请核对号码和目录'
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
            unlisted = tuple(fba for fba in invoice.fba_ids if fba not in report.fba_ids)
            match_method = '部分FBA辅助关联' if unlisted else '完整FBA匹配'
            messages = []
            if unlisted:
                messages.append(f'部分FBA辅助关联：报数{len(report.fba_ids)}个FBA，'
                    f'按发票全部{len(invoice.cartons)}箱核算；报数未列FBA：'+ '，'.join(unlisted))
            if channel_differs:
                messages.append('渠道与发票不一致，请核实下单服务')
            exceeds = report.billed_weight > invoice.approved_weight
            status = '需申请重测' if exceeds else ('渠道待核对' if channel_differs else '重量在允许范围')
            rows.append(ReconciliationRow(invoice, report, status, '；'.join(messages), exceeds,
                                          match_method, unlisted))
    return rows + extra
