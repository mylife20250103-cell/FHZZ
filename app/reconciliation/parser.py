from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from decimal import Decimal

from .models import ForwarderReport, ParseResult

FBA = re.compile(r'^FBA[A-Z0-9-]+$')
MC_START = re.compile(r'^MC\d+(?=\s*\(|[ \t]+FBA)', re.IGNORECASE)
MC_PARENS = re.compile(r'\s*\(([^()]*)\)')
MC_COLUMNS = re.compile(r'[ \t]+([^\s,、;/()]+(?: *[,、;/]+ *[^\s,、;/()]+)*(?: *[,、;/]+)?)')
MC_EXTRA_FBA = re.compile(r'(?:[ \t,、;/]+FBA[A-Z0-9-]+(?=[\s,、;/]|$))+', re.IGNORECASE)
MC_WEIGHT = re.compile(r'(.*?)\s*([-+]?\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)[.,。]*$', re.IGNORECASE)

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


def _parse_mc(number: int, raw: str, line: str) -> ForwarderReport:
    report = ForwarderReport(number, raw)
    order = re.match(r'^MC\d+', line, re.IGNORECASE)
    if order:
        report.order_number = order.group().upper()
    details = line[order.end():] if order else ''
    parentheses = MC_PARENS.match(details)
    identity = parentheses or MC_COLUMNS.match(details)
    if not identity:
        report.issues.append('迈创报数需要单号、FBA、渠道和计费重，支持括号或四列格式')
        return report

    fbas = identity.group(1).strip().upper()
    body = details[identity.end():]
    if parentheses:
        tokens = [token for token in re.split(r'[,、;\s]+', fbas) if token]
    else:
        tokens = [token.strip() for token in re.split(r'[,、;/]', fbas)]
        extra = MC_EXTRA_FBA.match(body)
        if '/' in fbas or extra or (body and not body[0].isspace()):
            report.issues.append('迈创四列格式的多个FBA应放在同一列，用逗号分隔')
        if extra:
            tokens.extend(re.findall(r'FBA[A-Z0-9-]+', extra.group().upper()))
            body = body[extra.end():]

    # 坏格式也保留可读FBA，避免重复报数绕过冲突检查。
    report.fba_ids = tuple(sorted({token for token in tokens if FBA.fullmatch(token)}))
    if not tokens or any(not FBA.fullmatch(token) or re.search(r'U\d{6}$', token) for token in tokens):
        report.issues.append('FBA列表无效，请填写FBA号而非带U箱序号的完整箱号')
    if len(tokens) != len(set(tokens)):
        report.issues.append('同一行FBA重复')

    weight = MC_WEIGHT.fullmatch(body.strip())
    if weight:
        report.channel = weight.group(1).strip()
        report.billed_weight = Decimal(weight.group(2))
        if not report.channel:
            report.issues.append('渠道为空')
        elif not parentheses and '\t' in report.channel:
            report.issues.append('迈创四列格式含多余列，请核对渠道和计费重')
        if report.billed_weight <= 0:
            report.issues.append('计费重量必须为大于0的有效数字')
    else:
        report.issues.append('计费重量缺失或无效，请填写正数及kg单位')
    return report


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
        elif MC_START.match(line):
            flush_hp()
            reports.append(_parse_mc(number, raw, line))
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
                reports.append(_parse_mc(number, raw, line))
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
