import json

import pytest
from openpyxl import Workbook


HEADERS = ('启用', '物流商', '国家', '仓库代码', '内部渠道', '税费方式', '派送方式', '账号标识', '服务代码', '发票填写值')


def rule_file(path, rows=None):
    book = Workbook()
    sheet = book.active
    sheet.title = '渠道规则'
    sheet.append(HEADERS)
    for row in rows or [(True, '迈创', '美国', 'SCK4', '美国合德', '包税', '卡派', 'MC.A', 'FAST', '美速达快提卡派')]:
        sheet.append(row)
    book.save(path)
    book.close()
    return path


def catalog():
    from app.channel_rules.models import AccountCatalog, Catalog, Service
    return Catalog((AccountCatalog('MC.A', 'MC', '迈创A', (
        Service('MC.A', 'MC', 'FAST', '美速达快提卡派', 'b2b'),
        Service('MC.A', 'MC', 'UNTAX', '美速达快提卡派-不包税', 'b2b'),
        Service('MC.A', 'MC', 'EXP', '美速达快提快递派', 'b2b'),
    ), '2026-10-23T10:00:00'),))


def test_rules_match_all_conditions_and_preserve_invoice_text(tmp_path):
    from app.channel_rules.rules import read_rules, match_rules
    path = rule_file(tmp_path / 'rules.xlsx', [
        (True, 'MC', 'US', 'SCK4', '美国合德', '包税', '卡派', 'MC.A', 'FAST', '美速达快提卡派'),
        (True, 'MC', 'US', 'SCK4', '美国合德', '不包税', '卡派', 'MC.A', 'UNTAX', '美速达快提卡派-不包税'),
        (True, 'MC', 'US', 'SCK4', '美国合德', '包税', '快递派', 'MC.A', 'EXP', '美速达快提快递派'),
    ])
    rules = read_rules(path)
    matches = match_rules(rules.rules, 'MC', 'US', 'sck4', '美国合德', '递延（不包税）', '卡派')
    assert [(m.service_code, m.invoice_value) for m in matches] == [('UNTAX', '美速达快提卡派-不包税')]
    assert match_rules(rules.rules, 'MC', 'CA', 'SCK4', '美国合德', '包税', '卡派') == ()
    assert match_rules(rules.rules, 'MC', 'US', 'SCK4', '美国合', '包税', '卡派') == ()


def test_conflicting_rules_remain_candidates_and_duplicates_coalesce(tmp_path):
    from app.channel_rules.rules import read_rules, match_rules
    row = (True, 'MC', 'US', 'SCK4', '美国合德', '包税', '卡派', 'MC.A', 'FAST', '服务甲')
    other = row[:-2] + ('OTHER', '服务乙')
    rules = read_rules(rule_file(tmp_path / 'r.xlsx', [row, row, other]))
    matches = match_rules(rules.rules, 'MC', 'US', 'SCK4', '美国合德', '包税', '卡派')
    assert [r.invoice_value for r in matches] == ['服务甲', '服务乙']


@pytest.mark.parametrize('index,value', [(3, ''), (3, '*'), (5, '任意'), (6, ''), (7, ''), (8, '=A1')])
def test_enabled_rule_rejects_missing_unrestricted_or_formula_fields(tmp_path, index, value):
    from app.channel_rules.rules import read_rules
    row = [True, 'MC', 'US', 'SCK4', '美国合德', '包税', '卡派', 'MC.A', 'FAST', '服务']
    row[index] = value
    with pytest.raises(ValueError):
        read_rules(rule_file(tmp_path / 'r.xlsx', [row]))


def test_disabled_rule_does_not_require_completion(tmp_path):
    from app.channel_rules.rules import read_rules
    assert read_rules(rule_file(tmp_path / 'r.xlsx', [(False, 'MC')])).rules == ()


def test_catalog_parser_validates_response_and_does_not_guess_country_or_coverage():
    from app.channel_rules.catalog import parse_services
    from app.shipment_tracking.providers.nextsls import NextslsConfig
    config = NextslsConfig('MC.A', '迈创A', 'https://example.test', 'SECRET', 'MC')
    data = {'status': 1, 'data': {'services': [{'code': '001', 'name': '服务', 'type': 'b2b', 'token': 'SECRET'}]}}
    services = parse_services(config, data)
    assert [(s.provider_id, s.code, s.name) for s in services] == [('MC.A', '001', '服务')]
    assert 'SECRET' not in repr(services)
    assert parse_services(config, {'status': 1, 'data': {'services': []}}) == ()
    for bad in ({'status': 0, 'info': 'SECRET'}, {'status': 1, 'data': {}}, {'status': 1, 'data': {'services': [None]}}):
        with pytest.raises(ValueError) as exc:
            parse_services(config, bad)
        assert 'SECRET' not in str(exc.value)


def test_failed_account_retains_previous_catalog_successful_empty_clears(tmp_path):
    from app.channel_rules.catalog import refresh_catalog, save_catalog, load_catalog
    from app.shipment_tracking.providers.nextsls import NextslsConfig
    config = NextslsConfig('MC.A', '迈创A', 'https://example.test', 'SECRET', 'MC')
    def fail(_):
        raise OSError('SECRET must never leak')
    failed = refresh_catalog((config,), catalog(), fetcher=fail)
    assert len(failed.accounts[0].services) == 3
    assert failed.accounts[0].error
    assert failed.accounts[0].updated_at == '2026-10-23T10:00:00'
    empty = refresh_catalog((config,), failed, fetcher=lambda _: ())
    assert empty.accounts[0].services == () and not empty.accounts[0].error
    path = tmp_path / 'catalog.json'
    save_catalog(path, failed)
    assert 'SECRET' not in path.read_text(encoding='utf-8')
    assert load_catalog(path) == failed
    assert load_catalog(path).version != empty.version


def test_fetch_uses_only_documented_read_service_endpoint(monkeypatch):
    from app.channel_rules.catalog import fetch_services
    from app.shipment_tracking.providers.nextsls import NextslsConfig
    config = NextslsConfig('MC.A', '迈创A', 'https://example.test', 'SECRET', 'MC')
    seen = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, _size=-1): return b'{"status":1,"data":{"services":[]}}'
    def transport(request, **kwargs):
        seen.append((request.full_url, json.loads(request.data), request.get_header('Authorization')))
        return Response()
    class Opener:
        open=staticmethod(transport)
    monkeypatch.setattr('app.channel_rules.catalog.urllib.request.build_opener', lambda *_: Opener())
    assert fetch_services(config) == ()
    assert seen == [('https://example.test/api/v5/shipment/get_services', {'services': {'type': 'all'}}, 'Bearer SECRET')]


def test_catalog_request_must_not_forward_credentials_through_redirects():
    from urllib.request import Request
    from app.channel_rules.catalog import NoRedirect
    handler=NoRedirect()
    request=Request('https://example.test/api/v5/shipment/get_services',data=b'{}',headers={'Authorization':'Bearer SECRET'})
    assert handler.redirect_request(request,None,307,'redirect',{},'https://other.test/collect') is None


def test_exports_have_no_enabled_fabricated_rules_or_credentials(tmp_path):
    from openpyxl import load_workbook
    from app.channel_rules.rules import export_rule_template, export_catalog, read_rules
    template = tmp_path / 'rules.xlsx'
    export_rule_template(template)
    assert read_rules(template).rules == ()
    dest = tmp_path / 'services.xlsx'
    export_catalog(dest, catalog())
    book = load_workbook(dest, read_only=True)
    rows = list(book['官方服务目录'].values)
    assert rows[0][:4] == ('物流商', '账号标识', '账号名称', '服务代码')
    assert rows[1][:6] == ('MC', 'MC.A', '迈创A', 'FAST', '美速达快提卡派', 'b2b')
    book.close()
