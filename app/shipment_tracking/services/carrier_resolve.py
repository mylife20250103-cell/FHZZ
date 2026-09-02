from __future__ import annotations

from configparser import ConfigParser

from app.invoice_config import CURRENT_CONFIG_INI

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
    path = CURRENT_CONFIG_INI
    if not path.exists():
        return []
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    text = None
    for encoding in ("utf-8-sig", "gbk", "utf-8"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return []
    parser = ConfigParser()
    parser.read_string(text)
    found: list[tuple[str, str]] = []
    for section in parser.sections():
        if not section.upper().startswith("CARRIER."):
            continue
        code = section.split(".", 1)[-1].strip().upper()
        name = parser.get(section, "CarrierName", fallback="").strip()
        if code and name:
            found.append((name, code))
    return found
