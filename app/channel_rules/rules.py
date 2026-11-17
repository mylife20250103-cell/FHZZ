"""人工关系与官方目录分别维护；六项条件精确匹配，不推断仓库覆盖。"""
from __future__ import annotations

from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from app.channel_rules.models import CARRIERS, DELIVERIES, TAXES, Catalog, ChannelRule, RuleSet, digest
from app.services.address_library import normalize_country_code

HEADERS = ('启用', '物流商', '国家', '仓库代码', '内部渠道', '税费方式', '派送方式', '账号标识', '服务代码', '发票填写值')


def text(value) -> str:
    return '' if value is None else str(value).strip()


def carrier_code(value) -> str:
    raw = text(value)
    return next((code for code, name in CARRIERS.items() if raw == name), raw.upper())


def country_code(value) -> str:
    raw = normalize_country_code(text(value))
    return {'美国': 'US', 'USA': 'US', 'UNITED STATES': 'US', '加拿大': 'CA', 'CAN': 'CA',
            '英国': 'GB', 'UK': 'GB', '德国': 'DE', '法国': 'FR', '意大利': 'IT', '西班牙': 'ES',
            '波兰': 'PL', '捷克': 'CZ', '日本': 'JP', '澳大利亚': 'AU', '墨西哥': 'MX'}.get(raw, raw)


def tax_code(value) -> str:
    raw = text(value)
    return '递延' if raw in ('递延', '不包税', '递延（不包税）', '递延(不包税)') else raw


def read_rules(path: Path) -> RuleSet:
    path = Path(path)
    if path.suffix.lower() != '.xlsx':
        raise ValueError('渠道规则必须是.xlsx 文件')
    before = digest(path)
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        if '渠道规则' not in book.sheetnames:
            raise ValueError('规则文件缺少“渠道规则”工作表，请使用创建的规则表')
        rows = book['渠道规则'].iter_rows()
        header = [text(c.value) for c in next(rows, ())]
        if any(header.count(name) != 1 for name in HEADERS):
            raise ValueError('渠道规则首行必须包含完整且不重复的十个列名')
        indices = [header.index(name) for name in HEADERS]
        rules = []
        for number, cells in enumerate(rows, 2):
            values = [cells[i].value if i < len(cells) else None for i in indices]
            if not any(text(v) for v in values):
                continue
            enabled = text(values[0]).lower()
            if enabled in ('false', '0', '否', '停用', '禁用'):
                continue
            if enabled not in ('', 'true', '1', '是', '启用'):
                raise ValueError(f'规则第{number}行：启用值无效')
            if any(i < len(cells) and cells[i].data_type in ('f', 'e') for i in indices):
                raise ValueError(f'规则第{number}行含公式或错误值，请填写明确文本')
            fields = [text(v) for v in values[1:]]
            if not all(fields) or '*' in fields or '?' in fields:
                raise ValueError(f'规则第{number}行缺项或含通配符；必须明确指定完整组合')
            carrier, country, warehouse, category, tax, delivery, provider, code, value = fields
            carrier, country, tax = carrier_code(carrier), country_code(country), tax_code(tax)
            if carrier not in CARRIERS or len(country) != 2 or not country.isascii() or not country.isalpha() or country == 'EU':
                raise ValueError(f'规则第{number}行：物流商或实际目的国无效')
            if tax not in TAXES or delivery not in DELIVERIES:
                raise ValueError(f'规则第{number}行：税费方式或派送方式无效')
            rules.append(ChannelRule(number, carrier, country, warehouse.upper(), category, tax, delivery, provider, code, value))
    finally:
        book.close()
    if digest(path) != before:
        raise ValueError('规则读取期间发生变化，请重试')
    return RuleSet(path.resolve(), before, tuple(rules))


def match_rules(rules, carrier, country, warehouse, category, tax, delivery) -> tuple[ChannelRule, ...]:
    key = (carrier_code(carrier), country_code(country), text(warehouse).upper(), text(category), tax_code(tax), text(delivery))
    found = {}
    for rule in rules:
        if (rule.carrier, rule.country, rule.warehouse, rule.category, rule.tax, rule.delivery) == key:
            found.setdefault((rule.provider_id, rule.service_code, rule.invoice_value), rule)
    return tuple(found.values())


def _save_new(book, path: Path):
    path = Path(path)
    if path.exists():
        raise ValueError('文件已存在，请另选名称，避免覆盖已有规则')
    for sheet in book:
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='245B90')
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 23
    try:
        book.save(path)
    finally:
        book.close()


def export_rule_template(path: Path):
    book = Workbook()
    sheet = book.active
    sheet.title = '渠道规则'
    sheet.append(HEADERS)
    for column, options in [('A', '是,否'), ('B', 'MC,KYD,HP'), ('F', '包税,递延'), ('G', '卡派,快递派')]:
        validation = DataValidation(type='list', formula1='"' + options + '"')
        validation.errorTitle, validation.error = '请使用列表选项', '不支持其他值'
        validation.showErrorMessage = True
        sheet.add_data_validation(validation)
        validation.add(f'{column}2:{column}10000')
    guide = book.create_sheet('填写说明')
    guide.append(['项目', '说明'])
    for row in [
        ('每行规则', '一个物流商、国家、仓库、内部渠道、税费、派送组合对应一个账号和服务。'),
        ('国家', '填写US、CA、GB、DE等实际国家；欧洲不是国家代码。'),
        ('账号与服务', '从导出的官方服务目录复制账号标识和服务代码；填写值用货代确认的完整服务名称。'),
        ('内部渠道', '由你们自行补充，例如美国合德；程序不从名称猜测归属或仓库覆盖。'),
        ('税费方式', '包税或递延；不包税按你们的内部口径归入递延，官方服务名称不改写。'),
        ('禁用规则', '启用填否可暂不补齐；启用规则不允许缺项或使用*通配。'),
        ('人工核实', '目录不证明服务适用于某个仓库；需核实税费、派送及账号要求。仅修改服务格，不修改税号等字段。'),
    ]:
        guide.append(row)
    _save_new(book, path)


def export_catalog(path: Path, catalog: Catalog):
    book = Workbook()
    sheet = book.active
    sheet.title = '官方服务目录'
    sheet.append(['物流商', '账号标识', '账号名称', '服务代码', '官方服务名称', '服务类型', '上次成功同步', '本次同步状态'])
    for account in catalog.accounts:
        for service in account.services:
            # 目录只输出官方已知字段；没有国家/仓库覆盖时不补造笛卡尔积。
            values = [account.carrier_code, account.provider_id, account.label, service.code, service.name,
                      service.type, account.updated_at, account.error or '成功']
            sheet.append([("'" + v) if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v for v in values])
    _save_new(book, path)
