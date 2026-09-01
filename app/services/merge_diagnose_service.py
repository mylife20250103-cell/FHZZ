from __future__ import annotations

from pathlib import Path

from app.services.address_library import lookup_kyd_address
from app.services.invoice_adapters.base import AdapterError, InvoiceMergeAdapter


def diagnose_merge_group(
    adapter: InvoiceMergeAdapter,
    group: dict,
    input_files: list[Path] | None = None,
) -> list[str]:
    """合并失败后按分组逐张检查源发票。"""

    warehouse = str(group.get("warehouse_code") or "").strip()
    count = group.get("input_count") or len(group.get("input_files") or [])
    lines = [
        f"【自检】{adapter.carrier_code} {warehouse or '未知仓库'}"
        f"（{count} 箱）"
    ]
    found = False

    if adapter.carrier_code.upper() == "KYD":
        try:
            lookup_kyd_address(warehouse)
        except AdapterError as exc:
            lines.append(f"- 分组：{exc}")
            found = True

    paths = input_files
    if not paths:
        paths = [Path(item) for item in group.get("input_files") or []]

    for path in paths:
        if not path.exists():
            lines.append(f"- {path.name}：文件不存在")
            found = True
            continue
        issues = adapter.diagnose_source(path)
        for issue in issues:
            lines.append(f"- {issue}")
            found = True

    if not found:
        lines.append("- 源发票逐张检查未发现问题，请看上面的合并错误原文")

    return lines
