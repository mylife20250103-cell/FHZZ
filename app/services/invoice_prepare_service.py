from __future__ import annotations

from dataclasses import dataclass

from app.app_logging import log_event
from app.services.batch_service import (
    STATUS_FIRST_SCAN_PASSED,
    STATUS_MERGE_PLAN_READY,
    STATUS_QUICK_MERGED,
    STATUS_SECOND_SCAN_PASSED,
    BatchRecord,
    load_batch,
)
from app.services.invoice_fast_merge_service import run_quick_merge
from app.services.invoice_second_scan_service import run_second_scan
from app.services.merge_plan_service import build_merge_plan


@dataclass
class PrepareMergeResult:
    passed: bool
    batch_id: str
    group_count: int
    file_count: int
    errors: list[str]
    stopped_at: str


def _reload(batch: BatchRecord) -> BatchRecord:

    record = load_batch(batch.directory)
    return record if record is not None else batch


def run_prepare_merge(batch: BatchRecord) -> PrepareMergeResult:
    """
    原始扫描通过后，连续完成：
    快速合并 → 二次扫描 → MergePlan。
    已完成的步骤会跳过，从当前 Batch 状态接着做。
    """

    record = _reload(batch)
    file_count = 0
    group_count = 0

    if record.status == STATUS_FIRST_SCAN_PASSED:

        log_event(
            "invoice",
            "准备合并：开始快速合并",
            batch_id=record.batch_id,
            stage="2",
        )

        quick = run_quick_merge(record)

        if not quick.passed:
            return PrepareMergeResult(
                passed=False,
                batch_id=record.batch_id,
                group_count=0,
                file_count=0,
                errors=quick.errors,
                stopped_at="quick_merge",
            )

        file_count = len(quick.items)
        record = _reload(record)

    if record.status == STATUS_QUICK_MERGED:

        log_event(
            "invoice",
            "准备合并：开始二次扫描",
            batch_id=record.batch_id,
            stage="3",
        )

        second = run_second_scan(record)

        if not second.passed:
            return PrepareMergeResult(
                passed=False,
                batch_id=record.batch_id,
                group_count=0,
                file_count=second.file_count,
                errors=second.errors,
                stopped_at="second_scan",
            )

        file_count = second.file_count
        record = _reload(record)

    if record.status == STATUS_SECOND_SCAN_PASSED:

        log_event(
            "invoice",
            "准备合并：生成 MergePlan",
            batch_id=record.batch_id,
            stage="4",
        )

        plan = build_merge_plan(record)

        if not plan.passed:
            return PrepareMergeResult(
                passed=False,
                batch_id=record.batch_id,
                group_count=plan.group_count,
                file_count=file_count,
                errors=plan.errors,
                stopped_at="merge_plan",
            )

        group_count = plan.group_count
        record = _reload(record)

    if record.status != STATUS_MERGE_PLAN_READY:

        return PrepareMergeResult(
            passed=False,
            batch_id=record.batch_id,
            group_count=group_count,
            file_count=file_count,
            errors=[
                "准备合并未能到达 MergePlan："
                f"当前状态 {record.status}"
            ],
            stopped_at="prepare",
        )

    return PrepareMergeResult(
        passed=True,
        batch_id=record.batch_id,
        group_count=group_count,
        file_count=file_count,
        errors=[],
        stopped_at="",
    )
