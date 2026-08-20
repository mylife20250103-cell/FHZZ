from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from app.app_logging import log_event
from app.json_io import read_json, write_json
from app.services.batch_service import (
    STATUS_CHECK_PASSED,
    BatchRecord,
    save_status,
)
from app.services.invoice_adapters import get_adapter


@dataclass
class ResultCheckOutcome:
    passed: bool
    batch_id: str
    output_count: int
    warning_count: int
    errors: list[str]
    warnings: list[str]


def _sensitive_warning_count(files: list[Path]) -> tuple[int, list[str]]:

    try:
        from app.services.sensitive_word_service import scan_output_files
    except ImportError:
        return 0, []

    result = scan_output_files(files)
    return result.hit_count, result.warning_messages


def run_result_check(batch: BatchRecord) -> ResultCheckOutcome:

    plan_path = batch.directory / "merge_plan.json"

    if not plan_path.exists():
        return ResultCheckOutcome(
            passed=False,
            batch_id=batch.batch_id,
            output_count=0,
            warning_count=0,
            errors=["缺少 merge_plan.json"],
            warnings=[],
        )

    plan = read_json(plan_path)
    groups = plan.get("Groups", [])
    merge_plan_hash = plan.get("MergePlanHash", "")

    errors: list[str] = []
    warnings: list[str] = []
    actual_files: list[Path] = []

    for group in groups:

        adapter = get_adapter(
            group["carrier_code"],
            group["template_version"],
        )
        output = Path(group["planned_output_path"]).with_suffix(
            adapter.output_extension()
        )

        if not output.exists():
            errors.append(f"缺少输出文件：{output}")
            continue

        if output.name.startswith("~$"):
            errors.append(f"输出是临时锁文件：{output.name}")
            continue

        actual_files.append(output)

        try:
            if output.suffix.lower() != ".xls":
                workbook = load_workbook(output, data_only=False)
                workbook.close()
        except Exception as exc:
            errors.append(f"{output.name}：无法打开：{exc}")
            continue

        enriched = dict(group)
        enriched["date_id"] = batch.date_id
        enriched["merge_plan_hash"] = merge_plan_hash

        errors.extend(
            adapter.validate_output(output, enriched)
        )

    if len(actual_files) != len(groups) and not any(
        "缺少输出文件" in item for item in errors
    ):
        errors.append(
            f"计划输出 {len(groups)} 个，实际 {len(actual_files)} 个"
        )

    warning_count = 0
    sensitive_messages: list[str] = []

    if not errors:
        warning_count, sensitive_messages = _sensitive_warning_count(
            actual_files
        )
        warnings.extend(sensitive_messages)

    payload = {
        "CheckVersion": "1.0",
        "BatchID": batch.batch_id,
        "DateID": batch.date_id,
        "CheckedAt": datetime.now().isoformat(timespec="seconds"),
        "PlannedOutputCount": len(groups),
        "ActualOutputCount": len(actual_files),
        "Passed": not errors,
        "Errors": errors,
        "Warnings": warnings,
        "sensitive_word_warning_count": warning_count,
    }

    write_json(batch.directory / "result_check.json", payload)

    if errors:
        log_event(
            "invoice_result_check",
            "结果检查失败",
            level="ERROR",
            batch_id=batch.batch_id,
            stage="6",
            detail="\n".join(errors),
        )

        return ResultCheckOutcome(
            passed=False,
            batch_id=batch.batch_id,
            output_count=len(actual_files),
            warning_count=warning_count,
            errors=errors,
            warnings=warnings,
        )

    save_status(batch, STATUS_CHECK_PASSED)

    log_event(
        "invoice_result_check",
        f"结果检查通过，敏感词警告 {warning_count}",
        batch_id=batch.batch_id,
        stage="6",
    )

    return ResultCheckOutcome(
        passed=True,
        batch_id=batch.batch_id,
        output_count=len(actual_files),
        warning_count=warning_count,
        errors=[],
        warnings=warnings,
    )
