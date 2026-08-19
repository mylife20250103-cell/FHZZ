from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

from app.invoice_config import SYSTEM_ROOT
from app.json_io import read_json, write_json
from app.services.invoice_adapters import get_adapter
from app.services.invoice_scan_service import collect_invoice_files


SENSITIVE_WORDS_PATH = (
    SYSTEM_ROOT / "公共配置" / "sensitive_words.json"
)

FIELD_ALIASES = {
    "ProductEN": ["产品英文品名", "产品英文品名*"],
    "ProductCN": ["产品中文品名", "产品中文品名*"],
    "MaterialEN": ["英文产品材质", "产品材质", "产品材质*"],
    "MaterialCN": ["中文产品材质", "产品材质", "产品材质*"],
}

FIELD_NAMES = {
    "ProductEN": "产品英文品名",
    "ProductCN": "产品中文品名",
    "MaterialEN": "英文产品材质",
    "MaterialCN": "中文产品材质",
}

WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class KeywordRule:
    keyword: str
    category: str
    enabled: bool
    fields: list[str]
    whitelist_phrases: list[str]
    remark: str = ""


@dataclass
class SensitiveHit:
    file_path: str
    sheet_name: str
    cell_address: str
    field_code: str
    field_name: str
    keyword: str
    category: str
    original_text: str
    normalized_text: str


@dataclass
class SensitiveScanResult:
    file_count: int
    field_count: int
    hit_count: int
    hit_file_count: int
    hits: list[SensitiveHit] = field(default_factory=list)
    aggregates: list[dict] = field(default_factory=list)
    warning_messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def normalize_text(value) -> str:

    if value is None:
        return ""

    text = str(value).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text


def apply_whitelist(text: str, phrases: list[str], ignore_case: bool) -> str:

    result = text

    for phrase in phrases:
        if not phrase:
            continue
        if ignore_case:
            result = re.sub(
                re.escape(phrase),
                "",
                result,
                flags=re.IGNORECASE,
            )
        else:
            result = result.replace(phrase, "")

    return normalize_text(result) if phrases else result


def keyword_hits_in_text(
    text: str,
    keyword: str,
    whitelist_phrases: list[str],
) -> bool:

    if not text or not keyword:
        return False

    has_latin = bool(re.search(r"[A-Za-z]", keyword))
    prepared = apply_whitelist(text, whitelist_phrases, ignore_case=has_latin)

    if has_latin:
        return keyword.lower() in prepared.lower()

    return keyword in prepared


def default_config() -> dict:

    return {
        "version": "1.0",
        "keywords": [],
    }


def load_keyword_rules(path: Path | None = None) -> list[KeywordRule]:

    config_path = path or SENSITIVE_WORDS_PATH

    if not config_path.exists():
        write_json(config_path, default_config())
        return []

    data = read_json(config_path)
    rules = []

    for item in data.get("keywords", []):
        rules.append(
            KeywordRule(
                keyword=str(item.get("keyword", "")).strip(),
                category=str(item.get("category", "")).strip(),
                enabled=bool(item.get("enabled", True)),
                fields=list(item.get("fields") or list(FIELD_NAMES)),
                whitelist_phrases=[
                    str(phrase)
                    for phrase in item.get("whitelist_phrases", [])
                    if str(phrase).strip()
                ],
                remark=str(item.get("remark", "")),
            )
        )

    return [rule for rule in rules if rule.enabled and rule.keyword]


def _header_map(headers: list[str]) -> dict[str, int]:

    mapping = {}

    for field_code, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in headers:
                mapping[field_code] = headers.index(alias)
                break

    return mapping


def _meta_from_sheet(workbook, sheet_name: str) -> dict:

    if sheet_name not in workbook.sheetnames:
        return {}

    values = {}
    ws = workbook[sheet_name]

    for row in ws.iter_rows(min_col=1, max_col=2, values_only=True):
        if row[0] is None:
            continue
        key = str(row[0]).strip()
        values[key] = "" if row[1] is None else str(row[1]).strip()

    return values


def _cells_from_adapter(path: Path, workbook) -> list[tuple[str, str, str, str, str]]:

    meta = _meta_from_sheet(workbook, "_SystemMeta")
    if not meta:
        meta = _meta_from_sheet(workbook, "_MergeMeta")

    carrier = meta.get("CarrierCode", "")
    version = meta.get("TemplateVersion") or "1.0"
    if version == "1":
        version = "1.0"

    if not carrier:
        return []

    try:
        adapter = get_adapter(carrier, version)
    except Exception:
        return []

    cfg = adapter.template_config()
    if cfg.header_row < 1 or cfg.data_start_row < 1:
        return []

    if cfg.sheet_name not in workbook.sheetnames:
        return []

    ws = workbook[cfg.sheet_name]
    results = []

    for spec in adapter.product_field_specs():
        if spec.column < 1:
            continue

        for row in range(cfg.data_start_row, ws.max_row + 1):
            carton = ws.cell(row, 1).value
            product = ws.cell(row, 3).value if ws.max_column >= 3 else None
            if carton in (None, "") and product in (None, ""):
                continue

            cell = ws.cell(row, spec.column)
            results.append(
                (
                    cfg.sheet_name,
                    cell.coordinate,
                    spec.field_code,
                    spec.field_name,
                    cell.value,
                )
            )

    return results


def _cells_from_headers(workbook) -> list[tuple[str, str, str, str, str]]:

    results = []

    for sheet_name in workbook.sheetnames:
        if sheet_name in {"_SystemMeta", "_MergeMeta"}:
            continue

        ws = workbook[sheet_name]
        first = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if not first:
            continue

        headers = [
            str(value).strip() if value is not None else ""
            for value in first
        ]
        mapping = _header_map(headers)
        if not mapping:
            continue

        for row_number, values in enumerate(
            ws.iter_rows(min_row=2, values_only=True),
            start=2,
        ):
            if not any(value not in (None, "") for value in values):
                continue

            for field_code, index in mapping.items():
                raw = values[index] if index < len(values) else None
                from openpyxl.utils import get_column_letter

                address = f"{get_column_letter(index + 1)}{row_number}"
                results.append(
                    (
                        sheet_name,
                        address,
                        field_code,
                        FIELD_NAMES[field_code],
                        raw,
                    )
                )

    return results


def scan_workbook(path: Path, rules: list[KeywordRule]) -> list[SensitiveHit]:

    workbook = load_workbook(path, data_only=True, read_only=False)
    hits: list[SensitiveHit] = []

    try:
        cells = _cells_from_adapter(path, workbook)
        if not cells:
            cells = _cells_from_headers(workbook)

        for sheet_name, address, field_code, field_name, raw in cells:
            original = "" if raw is None else str(raw)
            normalized = normalize_text(raw)

            for rule in rules:
                if field_code not in rule.fields:
                    continue

                if keyword_hits_in_text(
                    normalized,
                    rule.keyword,
                    rule.whitelist_phrases,
                ):
                    hits.append(
                        SensitiveHit(
                            file_path=str(path),
                            sheet_name=sheet_name,
                            cell_address=address,
                            field_code=field_code,
                            field_name=field_name,
                            keyword=rule.keyword,
                            category=rule.category,
                            original_text=original,
                            normalized_text=normalized,
                        )
                    )
    finally:
        workbook.close()

    return hits


def aggregate_hits(hits: list[SensitiveHit]) -> list[dict]:

    grouped: dict[tuple[str, str], dict] = {}

    for hit in hits:
        key = (hit.file_path, hit.keyword)
        item = grouped.get(key)
        if item is None:
            item = {
                "file_path": hit.file_path,
                "file_name": Path(hit.file_path).name,
                "keyword": hit.keyword,
                "category": hit.category,
                "count": 0,
                "details": [],
            }
            grouped[key] = item

        item["count"] += 1
        item["details"].append(hit)

    return list(grouped.values())


def scan_paths(
    paths: list[Path],
    *,
    recursive: bool = True,
    config_path: Path | None = None,
) -> SensitiveScanResult:

    rules = load_keyword_rules(config_path)
    files: list[Path] = []

    for path in paths:
        if path.is_file() and path.suffix.lower() == ".xlsx" and not path.name.startswith("~$"):
            files.append(path)
        elif path.is_dir():
            if recursive:
                files.extend(collect_invoice_files([path]))
            else:
                files.extend(
                    sorted(
                        item
                        for item in path.glob("*.xlsx")
                        if not item.name.startswith("~$")
                    )
                )

    unique = []
    seen = set()
    for file in files:
        resolved = file.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(file)

    hits: list[SensitiveHit] = []
    errors: list[str] = []
    field_count = 0

    for file in unique:
        try:
            file_hits = scan_workbook(file, rules)
            hits.extend(file_hits)
            field_count += 4
        except Exception as exc:
            errors.append(f"{file.name}：{exc}")

    aggregates = aggregate_hits(hits)
    hit_files = {hit.file_path for hit in hits}

    warnings = [
        f"{Path(item['file_path']).name} / {item['keyword']} x{item['count']}"
        for item in aggregates
    ]

    return SensitiveScanResult(
        file_count=len(unique),
        field_count=field_count,
        hit_count=len(hits),
        hit_file_count=len(hit_files),
        hits=hits,
        aggregates=aggregates,
        warning_messages=warnings,
        errors=errors,
    )


def scan_output_files(files: list[Path]) -> SensitiveScanResult:

    return scan_paths(files, recursive=False)


def export_results(result: SensitiveScanResult, output_path: Path) -> Path:

    from openpyxl import Workbook

    workbook = Workbook()
    summary = workbook.active
    summary.title = "汇总"
    summary.append(["文件", "敏感词", "分类", "命中次数"])

    for item in result.aggregates:
        summary.append(
            [
                item["file_path"],
                item["keyword"],
                item["category"],
                item["count"],
            ]
        )

    detail = workbook.create_sheet("明细")
    detail.append(
        [
            "文件",
            "工作表",
            "单元格",
            "字段代码",
            "字段名",
            "敏感词",
            "分类",
            "原始文本",
            "规范化文本",
        ]
    )

    for hit in result.hits:
        detail.append(
            [
                hit.file_path,
                hit.sheet_name,
                hit.cell_address,
                hit.field_code,
                hit.field_name,
                hit.keyword,
                hit.category,
                hit.original_text,
                hit.normalized_text,
            ]
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    workbook.close()
    return output_path
