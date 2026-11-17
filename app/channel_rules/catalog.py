"""只调用已核实的服务目录查询接口；缓存不包含请求、原始响应或密钥。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from app.channel_rules.models import AccountCatalog, Catalog, Service


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 身份头只允许发给配置中的目录地址，禁止自动转发到重定向目标。
        return None


def parse_services(config, body: dict) -> tuple[Service, ...]:
    if not isinstance(body, dict) or str(body.get('status')) != '1':
        raise ValueError('服务目录请求未成功，请核对账号权限')
    data = body.get('data')
    rows = data.get('services') if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError('服务目录响应缺少 services 数组，未覆盖旧目录')
    found = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('code'), str) or not isinstance(row.get('name'), str):
            raise ValueError('服务目录项目缺少文本代码或名称')
        code, name = row['code'].strip(), row['name'].strip()
        if not code or not name:
            raise ValueError('服务目录存在空代码或名称')
        item = Service(config.provider_id, config.carrier_code, code, name, str(row.get('type') or ''))
        if code in found and found[code] != item:
            raise ValueError('同一账号的服务代码重复且内容冲突')
        found[code] = item
    return tuple(found.values())


def fetch_services(config) -> tuple[Service, ...]:
    base = urlsplit(config.gateway)
    if base.scheme not in ('http', 'https') or not base.netloc or base.username or base.password or base.query or base.fragment:
        raise ValueError('服务目录网关配置无效')
    request = urllib.request.Request(
        config.gateway.rstrip('/') + '/api/v5/shipment/get_services',
        data=json.dumps({'services': {'type': 'all'}}).encode(), method='POST',
        headers={'Authorization': f'Bearer {config.token}', 'Content-Type': 'application/json',
                 'Accept': 'application/json', 'Accept-Language': 'zh-CN'},
    )
    try:
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(request, timeout=20) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('目录响应过大')
        body = json.loads(raw.decode('utf-8-sig'))
    except urllib.error.HTTPError as exc:
        raise ValueError(f'目录查询 HTTP {exc.code}，请核对权限') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError('目录接口连接失败，请稍后重试') from None
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError('目录接口返回格式无法解析') from None
    return parse_services(config, body)


def refresh_catalog(configs, previous: Catalog, *, fetcher=None) -> Catalog:
    fetcher = fetcher or fetch_services
    old = {a.provider_id: a for a in previous.accounts}
    result = []
    for config in configs:
        try:
            services = fetcher(config)
            result.append(AccountCatalog(config.provider_id, config.carrier_code, config.name, tuple(services),
                                         datetime.now().isoformat(timespec='seconds')))
        except Exception:
            # 不传播服务商错误正文或底层请求信息，避免把密钥带进界面、日志、缓存。
            last = old.get(config.provider_id)
            if last is not None and last.carrier_code != config.carrier_code:
                last = None
            result.append(AccountCatalog(config.provider_id, config.carrier_code, config.name,
                                         last.services if last else (), last.updated_at if last else '',
                                         '本次同步失败；有历史目录时继续保留，请核对网络和账号权限'))
    return Catalog(tuple(result))


def save_catalog(path: Path, catalog: Catalog) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps({'schema': 1, **asdict(catalog)}, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def load_catalog(path: Path) -> Catalog:
    if not Path(path).exists():
        return Catalog()
    try:
        body = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(body, dict) or body.get('schema') != 1 or not isinstance(body.get('accounts'), list):
            raise ValueError()
        accounts = []
        seen = set()
        for row in body['accounts']:
            provider, carrier = row['provider_id'], row['carrier_code']
            if not all(isinstance(v, str) and v for v in (provider, carrier)) or provider in seen:
                raise ValueError()
            seen.add(provider)
            config = type('Account', (), {'provider_id': provider, 'carrier_code': carrier})
            services = parse_services(config, {'status': 1, 'data': {'services': row['services']}})
            label, updated, error = row.get('label', ''), row.get('updated_at', ''), row.get('error', '')
            if not all(isinstance(v, str) for v in (label, updated, error)):
                raise ValueError()
            accounts.append(AccountCatalog(provider, carrier, label, services, updated, error))
        return Catalog(tuple(accounts))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('本机服务目录缓存损坏，请重新同步；原文件未改动') from None
