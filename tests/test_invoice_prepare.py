from __future__ import annotations

from app.services.batch_service import (
    STATUS_MERGE_PLAN_READY,
    STATUS_QUICK_MERGED,
    STATUS_SECOND_SCAN_PASSED,
    ensure_batch_after_first_scan,
)
from app.services.invoice_fast_merge_service import QuickMergeResult
from app.services.invoice_prepare_service import run_prepare_merge
from app.services.invoice_second_scan_service import SecondScanResult
from app.services.merge_plan_service import MergePlanResult
from tests.test_batch_service import make_record, make_result


def _batch(tmp_path, monkeypatch):

    monkeypatch.setattr(
        "app.services.batch_service.BATCH_ROOT",
        tmp_path / "batches",
    )

    batch, _ = ensure_batch_after_first_scan(
        "20260819",
        make_result([make_record()]),
    )
    return batch


def test_prepare_merge_runs_three_steps(tmp_path, monkeypatch):

    batch = _batch(tmp_path, monkeypatch)
    calls = []

    def fake_quick(record):
        calls.append("quick")
        record.status = STATUS_QUICK_MERGED
        return QuickMergeResult(
            passed=True,
            batch_id=record.batch_id,
            root="r",
            items=[object(), object()],
            errors=[],
        )

    def fake_second(record):
        calls.append("second")
        record.status = STATUS_SECOND_SCAN_PASSED
        return SecondScanResult(
            passed=True,
            batch_id=record.batch_id,
            file_count=2,
            errors=[],
        )

    def fake_plan(record):
        calls.append("plan")
        record.status = STATUS_MERGE_PLAN_READY
        return MergePlanResult(
            passed=True,
            batch_id=record.batch_id,
            group_count=5,
            plan={},
            errors=[],
        )

    monkeypatch.setattr(
        "app.services.invoice_prepare_service.run_quick_merge",
        fake_quick,
    )
    monkeypatch.setattr(
        "app.services.invoice_prepare_service.run_second_scan",
        fake_second,
    )
    monkeypatch.setattr(
        "app.services.invoice_prepare_service.build_merge_plan",
        fake_plan,
    )
    monkeypatch.setattr(
        "app.services.invoice_prepare_service.load_batch",
        lambda directory: batch,
    )

    result = run_prepare_merge(batch)

    assert result.passed
    assert result.group_count == 5
    assert calls == ["quick", "second", "plan"]


def test_prepare_merge_stops_on_quick_merge_fail(tmp_path, monkeypatch):

    batch = _batch(tmp_path, monkeypatch)

    monkeypatch.setattr(
        "app.services.invoice_prepare_service.run_quick_merge",
        lambda record: QuickMergeResult(
            passed=False,
            batch_id=record.batch_id,
            root="",
            items=[],
            errors=["复制失败"],
        ),
    )
    monkeypatch.setattr(
        "app.services.invoice_prepare_service.load_batch",
        lambda directory: batch,
    )

    result = run_prepare_merge(batch)

    assert result.passed is False
    assert result.stopped_at == "quick_merge"
    assert "复制失败" in result.errors


def test_prepare_merge_resumes_from_second_scan(tmp_path, monkeypatch):

    batch = _batch(tmp_path, monkeypatch)
    batch.status = STATUS_QUICK_MERGED
    calls = []

    def fake_second(record):
        calls.append("second")
        record.status = STATUS_SECOND_SCAN_PASSED
        return SecondScanResult(
            passed=True,
            batch_id=record.batch_id,
            file_count=7,
            errors=[],
        )

    def fake_plan(record):
        calls.append("plan")
        record.status = STATUS_MERGE_PLAN_READY
        return MergePlanResult(
            passed=True,
            batch_id=record.batch_id,
            group_count=5,
            plan={},
            errors=[],
        )

    monkeypatch.setattr(
        "app.services.invoice_prepare_service.run_quick_merge",
        lambda record: (_ for _ in ()).throw(
            AssertionError("should skip quick merge")
        ),
    )
    monkeypatch.setattr(
        "app.services.invoice_prepare_service.run_second_scan",
        fake_second,
    )
    monkeypatch.setattr(
        "app.services.invoice_prepare_service.build_merge_plan",
        fake_plan,
    )
    monkeypatch.setattr(
        "app.services.invoice_prepare_service.load_batch",
        lambda directory: batch,
    )

    result = run_prepare_merge(batch)

    assert result.passed
    assert calls == ["second", "plan"]
