from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


FIELDS = ("产品中文品名", "产品英文品名", "产品材质", "产品海关编码")
REGIONS = {"US": "美国", "EU": "欧洲", "GB": "英国", "CA": "加拿大"}
CARRIERS = {"MC": "迈创", "KYD": "快越达", "HP": "皓鹏"}
Product = tuple[str, str, str, str]


@dataclass(frozen=True)
class Rule:
    row: int
    region: str
    before: Product
    after: Product


@dataclass(frozen=True)
class RuleSet:
    path: Path
    sha256: str
    sheet: str
    rules: tuple[Rule, ...]
    skipped_empty_rows: int = 0


@dataclass(frozen=True)
class Candidate:
    rule: Rule
    score: float


@dataclass(frozen=True)
class InvoiceLine:
    row: int  # Excel 1-based
    values: Product


@dataclass(frozen=True)
class Invoice:
    path: Path
    carrier: str
    sheet: str
    columns: tuple[int, int, int, int]  # 1-based, FIELDS order
    lines: tuple[InvoiceLine, ...]


@dataclass(frozen=True)
class PreviewLine:
    key: str
    relative: str
    sheet: str
    line: InvoiceLine
    candidates: tuple[Candidate, ...]


@dataclass(frozen=True)
class ScanResult:
    root: Path
    rules: RuleSet
    carrier: str
    region: str
    threshold: float
    hashes: tuple[tuple[str, str], ...]
    invoices: tuple[Invoice, ...]
    rows: tuple[PreviewLine, ...]
