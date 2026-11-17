from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

CARRIERS = {'MC': '迈创', 'KYD': '快越达', 'HP': '皓鹏'}
TAXES = ('包税', '递延')
DELIVERIES = ('卡派', '快递派')


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


@dataclass(frozen=True)
class Service:
    provider_id: str
    carrier_code: str
    code: str
    name: str
    type: str = ''


@dataclass(frozen=True)
class AccountCatalog:
    provider_id: str
    carrier_code: str
    label: str
    services: tuple[Service, ...]
    updated_at: str = ''
    error: str = ''


@dataclass(frozen=True)
class Catalog:
    accounts: tuple[AccountCatalog, ...] = ()

    @property
    def version(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    @property
    def services(self) -> tuple[Service, ...]:
        return tuple(service for account in self.accounts for service in account.services)

    def find(self, provider_id: str, code: str) -> Service | None:
        return next((s for s in self.services if s.provider_id == provider_id and s.code == code), None)


@dataclass(frozen=True)
class ChannelRule:
    row: int
    carrier: str
    country: str
    warehouse: str
    category: str
    tax: str
    delivery: str
    provider_id: str
    service_code: str
    invoice_value: str


@dataclass(frozen=True)
class RuleSet:
    path: Path
    sha256: str
    rules: tuple[ChannelRule, ...]


@dataclass(frozen=True)
class InvoiceHead:
    path: Path
    relative: str
    carrier: str
    country: str
    warehouse: str
    sheet: str
    cell: str
    current_value: str
    has_products: bool


@dataclass(frozen=True)
class ChannelScan:
    root: Path
    rules: RuleSet
    catalog: Catalog
    heads: tuple[InvoiceHead, ...]
    hashes: tuple[tuple[str, str], ...]
    address_path: Path
    address_sha256: str


@dataclass
class ChannelEdit:
    head: InvoiceHead
    category: str
    tax: str
    delivery: str
    candidates: tuple[ChannelRule, ...] = ()
    chosen: ChannelRule | None = None
    provider_id: str = ''
    service_code: str = ''
    new_value: str = ''
    status: str = ''
    manual: bool = False
    selected: bool = False
