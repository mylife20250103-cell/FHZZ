from __future__ import annotations

from app.services.batch_service import (
    STATUS_CHECK_PASSED,
    STATUS_COMPLETED,
    complete_batch,
    ensure_batch_after_first_scan,
    save_status,
)
from tests.test_batch_service import make_record, make_result


def test_complete_requires_check_passed_and_cleans_quick_merge(tmp_path, monkeypatch):

    monkeypatch.setattr(
        "app.services.batch_service.BATCH_ROOT",
        tmp_path / "batches",
    )
    monkeypatch.setattr(
        "app.invoice_config.MERGE_RESULT_ROOT",
        tmp_path / "out",
    )
    monkeypatch.setattr(
        "app.services.invoice_fast_merge_service.QUICK_MERGE_ROOT",
        tmp_path / "quick",
    )

    record, _ = ensure_batch_after_first_scan(
        "20260819",
        make_result([make_record()]),
    )

    try:
        complete_batch(record)
        assert False, "should require CHECK_PASSED"
    except Exception:
        pass

    save_status(record, STATUS_CHECK_PASSED)

    try:
        complete_batch(record)
        assert False, "should require output files"
    except Exception as exc:
        assert "重新执行内容合并" in str(exc)

    output_dir = tmp_path / "out" / "20260819" / record.batch_id
    output_dir.mkdir(parents=True)
    (output_dir / "KYD_BJC1_1箱.xlsx").write_bytes(b"ok")

    quick_dir = tmp_path / "quick" / record.batch_id
    quick_dir.mkdir(parents=True)
    (quick_dir / "dummy.xlsx").write_bytes(b"tmp")

    completed = complete_batch(record)

    assert completed.status == STATUS_COMPLETED
    assert not quick_dir.exists()
    assert (output_dir / "KYD_BJC1_1箱.xlsx").exists()


def test_complete_when_quick_merge_locked(tmp_path, monkeypatch):

    monkeypatch.setattr(
        "app.services.batch_service.BATCH_ROOT",
        tmp_path / "batches",
    )
    monkeypatch.setattr(
        "app.invoice_config.MERGE_RESULT_ROOT",
        tmp_path / "out",
    )
    monkeypatch.setattr(
        "app.services.invoice_fast_merge_service.QUICK_MERGE_ROOT",
        tmp_path / "quick",
    )
    monkeypatch.setattr(
        "app.services.batch_service.time.sleep",
        lambda *_: None,
    )

    record, _ = ensure_batch_after_first_scan(
        "20260819",
        make_result([make_record()]),
    )
    save_status(record, STATUS_CHECK_PASSED)

    output_dir = tmp_path / "out" / "20260819" / record.batch_id
    output_dir.mkdir(parents=True)
    (output_dir / "KYD_BJC1_1箱.xlsx").write_bytes(b"ok")

    quick_dir = tmp_path / "quick" / record.batch_id
    quick_dir.mkdir(parents=True)
    (quick_dir / "dummy.xlsx").write_bytes(b"tmp")

    def boom(path, *args, **kwargs):
        raise PermissionError(5, "拒绝访问", str(path))

    monkeypatch.setattr(
        "app.services.batch_service.shutil.rmtree",
        boom,
    )

    completed = complete_batch(record)

    assert completed.status == STATUS_COMPLETED
    assert (output_dir / "KYD_BJC1_1箱.xlsx").exists()
