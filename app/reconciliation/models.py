from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

DIVISOR = Decimal(6000)
DIMENSION_TOLERANCE = Decimal(2)


@dataclass(frozen=True)
class Carton:
    number: str
    fba_id: str
    weight: Decimal
    length: Decimal
    width: Decimal
    height: Decimal
    source_row: int

    @property
    def volume(self) -> Decimal:
        return self.length * self.width * self.height / DIVISOR

    @property
    def tolerance_volume(self) -> Decimal:
        t = DIMENSION_TOLERANCE
        return (self.length+t) * (self.width+t) * (self.height+t) / DIVISOR


@dataclass(frozen=True)
class InvoiceEstimate:
    path: Path
    carrier: str
    warehouse: str = ''
    channel: str = ''
    cartons: tuple[Carton, ...] = ()
    issues: tuple[str, ...] = ()
    sha256: str = ''

    @property
    def fba_ids(self) -> tuple[str, ...]:
        return tuple(sorted({c.fba_id for c in self.cartons}))

    @property
    def total_real(self) -> Decimal:
        return sum((c.weight for c in self.cartons), Decimal(0))

    @property
    def original_volume(self) -> Decimal:
        return sum((c.length*c.width*c.height for c in self.cartons), Decimal(0)) / DIVISOR

    @property
    def tolerance_volume(self) -> Decimal:
        # 先累加体积乘积再除一次，避免循环小数求和在整数边界多进位1kg。
        t = DIMENSION_TOLERANCE
        return sum(((c.length+t)*(c.width+t)*(c.height+t) for c in self.cartons), Decimal(0)) / DIVISOR

    @property
    def estimated_weight(self) -> Decimal | None:
        return None if self.issues or not self.cartons else max(self.total_real, self.original_volume)

    @property
    def approved_weight(self) -> Decimal | None:
        if self.issues or not self.cartons:
            return None
        return max(self.total_real, self.tolerance_volume).to_integral_value(rounding=ROUND_CEILING)


@dataclass(frozen=True)
class ScanResult:
    directory: Path
    invoices: tuple[InvoiceEstimate, ...]
    scanned_at: str


@dataclass
class ForwarderReport:
    line_number: int
    raw_text: str
    order_number: str = ''
    carrier: str = 'MC'
    fba_ids: tuple[str, ...] = ()
    channel: str = ''
    billed_weight: Decimal | None = None
    issues: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParseResult:
    reports: tuple[ForwarderReport, ...]
    ignored_lines: tuple[str, ...]


@dataclass(frozen=True)
class ReconciliationRow:
    invoice: InvoiceEstimate | None
    report: ForwarderReport | None
    status: str
    message: str = ''
    needs_remeasure: bool = False

    @property
    def difference(self) -> Decimal | None:
        if (self.status in {'匹配冲突','源数据异常','报数异常','未匹配','待货代报数'}
                or self.invoice is None or self.report is None or self.report.issues
                or self.invoice.approved_weight is None or self.report.billed_weight is None):
            return None
        return self.report.billed_weight - self.invoice.approved_weight
