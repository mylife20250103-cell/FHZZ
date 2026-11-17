from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from decimal import Decimal

from .models import ForwarderReport, ParseResult

REPORT = re.compile(
    r'^(MC\d+)\s*\(([^()]*)\)\s*(.*?)\s*([-+]?\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)[.,。]*$',
    re.IGNORECASE,
)
FBA = re.compile(r'^FBA[A-Z0-9-]+$')


def parse_reports(text: str) -> ParseResult:
    reports, ignored = [], []
    for number, raw in enumerate(text.splitlines(), 1):
        line = unicodedata.normalize('NFKC', raw).strip().rstrip('\\').strip()
        if not line:
            continue
        if not re.search(r'\bMC\d', line, re.IGNORECASE):
            ignored.append(raw)
            continue
        report = ForwarderReport(number, raw)
        # 格式错误也保留可识别身份，不能让坏重量绕过重复单号/FBA检查。
        order_match = re.match(r'^(MC\d+)', line, re.IGNORECASE)
        identity = re.match(r'^MC\d+\s*\(([^()]*)\)', line, re.IGNORECASE)
        if order_match:
            report.order_number = order_match.group(1).upper()
        if identity:
            report.fba_ids = tuple(sorted(set(t.upper() for t in
                re.split(r'[,、;\s]+', identity.group(1).strip()) if t)))
        match = REPORT.fullmatch(line)
        if not match:
            report.issues.append('报数格式或重量无效，需要 MC单号(FBA列表) 渠道 正数kg')
        else:
            order, fbas, channel, weight = match.groups()
            report.order_number = order.upper()
            tokens = tuple(t.upper() for t in re.split(r'[,、;\s]+', fbas.strip()) if t)
            report.fba_ids = tuple(sorted(set(tokens)))
            report.channel = channel.strip()
            report.billed_weight = Decimal(weight)
            if not tokens or any(not FBA.fullmatch(t) or re.search(r'U\d{6}$', t) for t in tokens):
                report.issues.append('FBA列表无效，请填写FBA号而非带U箱序号的完整箱号')
            if len(tokens) != len(set(tokens)):
                report.issues.append('同一行FBA重复')
            if not report.channel:
                report.issues.append('渠道为空')
            if not report.billed_weight.is_finite() or report.billed_weight <= 0:
                report.issues.append('计费重量必须为大于0的有效数字')
        reports.append(report)
    orders, fbas = defaultdict(list), defaultdict(list)
    for i, report in enumerate(reports):
        if report.order_number:
            orders[report.order_number].append(i)
        for fba in report.fba_ids:
            fbas[fba].append(i)
    for lookup, label in ((orders, '单号重复'), (fbas, 'FBA跨报数重复')):
        for key, indexes in lookup.items():
            if len(indexes) > 1:
                for index in indexes:
                    reports[index].issues.append(f'{label}：{key}')
    return ParseResult(tuple(reports), tuple(ignored))
