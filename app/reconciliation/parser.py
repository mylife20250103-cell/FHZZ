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


HP_HEADER = re.compile(r'^HPT\d+(?:\s*/\s*FBA[A-Z0-9-]+)+\s*$', re.IGNORECASE)
HP_WEIGHT = re.compile(r'收费重\s*([-+]?\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)[.,。]*$', re.IGNORECASE)
HP_NOTICE = re.compile(r'^(?:麻烦请确认|您好|你好|温馨提示|请知悉)')


def _normalize(raw: str) -> str:
    return unicodedata.normalize('NFKC', raw).strip().rstrip('\\').strip()


def _parse_hp(number: int, raw: str) -> ForwarderReport:
    line = ' '.join(_normalize(part) for part in raw.splitlines())
    report = ForwarderReport(number, raw, carrier='HP')
    order = re.match(r'^HPT\d+', line, re.IGNORECASE)
    if order:
        report.order_number = order.group().upper()
    # 先验证完整身份行；一行粘贴时以客户前缀/皓鹏正文开始处为界。
    identity = re.split(r'\s+(?=\S*皓鹏)', _normalize(raw.splitlines()[0]), maxsplit=1)[0]
    tokens = tuple(re.findall(r'(?<![A-Z0-9-])FBA[A-Z0-9-]+', identity.upper()))
    # 坏格式也保留可读身份，防止绕过跨票重复检查；票内重复属于皓鹏正常格式。
    report.fba_ids = tuple(sorted(set(tokens)))
    if not HP_HEADER.fullmatch(identity):
        report.issues.append('皓鹏报数需要 HPT单号/FBA列表')
    if any(re.search(r'U\d{6}$', t) for t in tokens):
        report.issues.append('FBA列表无效，请填写FBA号而非完整箱号')
    body = line
    channel = re.search(r'皓鹏\s*(.*?)\s*报关方式\s*(.*?)\s*收费重', body)
    if (channel and channel.group(1).strip() and channel.group(2).strip()
            and body.count('报关方式') == 1):
        report.channel = channel.group(1).strip()
    else:
        report.issues.append('皓鹏渠道或报关方式缺失/重复')
    weight = HP_WEIGHT.search(body)
    if weight and body.count('收费重') == 1:
        report.billed_weight = Decimal(weight.group(1))
        if report.billed_weight <= 0:
            report.issues.append('计费重量必须为大于0的有效数字')
    else:
        report.issues.append('皓鹏收费重缺失、重复或无效')
    return report


def _parse_mc_lines(lines) -> list[ForwarderReport]:
    reports = []
    for number, raw in lines:
        line = _normalize(raw)
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
    return reports


def parse_reports(text: str) -> ParseResult:
    reports, ignored, pending = [], [], []
    start = 0

    def flush_hp():
        if pending:
            reports.append(_parse_hp(start, '\n'.join(pending)))
            pending.clear()

    for number, raw in enumerate(text.splitlines(), 1):
        line = _normalize(raw)
        if not line:
            if pending:
                pending.append(raw)
            continue
        if re.match(r'^HPT\d', line, re.IGNORECASE):
            flush_hp()
            start = number
            pending.append(raw)
        elif re.match(r'^MC\d+\s*\(', line, re.IGNORECASE):
            flush_hp()
            reports.extend(_parse_mc_lines([(number, raw)]))
        elif pending and not HP_NOTICE.match(line):
            last = next((_normalize(part) for part in reversed(pending) if _normalize(part)), '')
            if (HP_WEIGHT.search(last)
                    and not re.search(r'收费重|报关方式|皓鹏|FBA', line, re.IGNORECASE)):
                flush_hp()
                ignored.append(raw)
            else:
                pending.append(raw)
        else:
            flush_hp()
            if re.search(r'\bMC\d', line, re.IGNORECASE):
                reports.extend(_parse_mc_lines([(number,raw)]))
            elif re.search(r'\bHPT\d', line, re.IGNORECASE):
                reports.append(_parse_hp(number,raw))
            else:
                ignored.append(raw)
    flush_hp()
    orders, fbas = defaultdict(list), defaultdict(list)
    for i, report in enumerate(reports):
        if report.order_number:
            orders[report.carrier, report.order_number].append(i)
        for fba in report.fba_ids:
            fbas[report.carrier, fba].append(i)
    for lookup, label in ((orders, '单号重复'), (fbas, 'FBA跨报数重复')):
        for key, indexes in lookup.items():
            if len(indexes) > 1:
                for index in indexes:
                    reports[index].issues.append(f'{label}：{key[1]}')
    return ParseResult(tuple(reports), tuple(ignored))
