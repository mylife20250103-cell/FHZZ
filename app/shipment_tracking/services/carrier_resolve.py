from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

from app.invoice_config import CURRENT_CONFIG_INI, FORWARDER_API_INI

_FALLBACK_NAMES = (
    ("快越达", "KYD"),
    ("迈创", "MC"),
    ("皓鹏", "HP"),
    ("利合", "LH"),
)


def resolve_carrier(confirmed: str, candidate: str = "") -> str:
    """
    拉取/详情用的货代代码。
    有发票确认货代时用确认值；没有时用文件名候选（如 迈创合德 → MC）。
    """

    code = (confirmed or "").strip().upper()
    if code.startswith("冲突"):
        return ""
    if code:
        return code
    return carrier_code_from_name(candidate)


def carrier_code_from_name(name: str) -> str:
    text = (name or "").strip()
    if not text:
        return ""
    upper = text.upper()
    if upper in {"KYD", "MC", "HP", "LH"}:
        return upper
    hints = list(_FALLBACK_NAMES)
    hints.extend(_config_name_hints())
    hints.sort(key=lambda item: len(item[0]), reverse=True)
    folded = text.casefold()
    for hint, code in hints:
        if hint.casefold() in folded or hint.upper() == upper:
            return code
    return ""


def _config_name_hints() -> list[tuple[str, str]]:
    """
    发票白名单只读 current_config.ini（KYD/MC）。
    追踪货代只读 forwarder_api.ini，不要写回发票配置表。
    """

    found: list[tuple[str, str]] = []
    found.extend(
        _carrier_section_hints(CURRENT_CONFIG_INI, prefix="CARRIER.")
    )
    found.extend(_nextsls_name_hints(FORWARDER_API_INI))
    return found


def _carrier_section_hints(
    path: Path,
    *,
    prefix: str,
) -> list[tuple[str, str]]:
    parser = _read_ini(path)
    if parser is None:
        return []
    found: list[tuple[str, str]] = []
    wanted = prefix.upper()
    for section in parser.sections():
        if not section.upper().startswith(wanted):
            continue
        code = section.split(".", 1)[-1].strip().upper()
        name = parser.get(section, "CarrierName", fallback="").strip()
        if code and name:
            found.append((name, code))
    return found


def _nextsls_name_hints(path: Path) -> list[tuple[str, str]]:
    parser = _read_ini(path)
    if parser is None:
        return []
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for section in parser.sections():
        if not section.upper().startswith("NEXTSLS."):
            continue
        code = parser.get(section, "CarrierCode", fallback="").strip().upper()
        name = parser.get(section, "Name", fallback="").strip()
        if not code:
            continue
        labels = [name]
        if "-" in name:
            labels.append(name.split("-", 1)[0].strip())
        for label in labels:
            item = (label, code)
            if not label or item in seen:
                continue
            seen.add(item)
            found.append(item)
    return found


def _read_ini(path) -> ConfigParser | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    try:
        raw = file_path.read_bytes()
    except OSError:
        return None
    text = None
    for encoding in ("utf-8-sig", "gbk", "utf-8"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return None
    parser = ConfigParser()
    parser.read_string(text)
    return parser
