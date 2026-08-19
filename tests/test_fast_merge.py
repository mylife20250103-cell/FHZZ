from __future__ import annotations

from pathlib import Path

from app.services.batch_service import (
    STATUS_FIRST_SCAN_PASSED,
    STATUS_QUICK_MERGED,
    ensure_batch_after_first_scan,
    load_batch,
)
from app.services.invoice_fast_merge_service import run_quick_merge
from app.services.invoice_scan_service import sha256_file
from tests.test_batch_service import make_record, make_result


def _write_file(path: Path, content: bytes) -> str:

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return sha256_file(path)


def test_quick_merge_copy_and_sha(tmp_path, monkeypatch):

    batch_root = tmp_path / "batches"
    merge_root = tmp_path / "quick"

    monkeypatch.setattr(
        "app.services.batch_service.BATCH_ROOT",
        batch_root,
    )
    monkeypatch.setattr(
        "app.services.invoice_fast_merge_service.QUICK_MERGE_ROOT",
        merge_root,
    )

    src_dir = tmp_path / "src"
    file_a = src_dir / "BJC1_box1.xlsx"
    file_b = src_dir / "PSP3_box1.xlsx"

    hash_a = _write_file(file_a, b"invoice-a")
    hash_b = _write_file(file_b, b"invoice-b")

    records = [
        make_record(
            path=str(file_a),
            sha256=hash_a,
            warehouse_code="BJC1",
            carton_number="FBA19L0YW7PMU000001",
        ),
        make_record(
            path=str(file_b),
            sha256=hash_b,
            warehouse_code="PSP3",
            fba_batch="FBA19L11LFRW",
            carton_number="FBA19L11LFRWU000001",
        ),
    ]

    batch, _ = ensure_batch_after_first_scan(
        "20260819",
        make_result(records),
    )

    result = run_quick_merge(batch)

    assert result.passed
    assert len(result.items) == 2

    refreshed = load_batch(batch.directory)

    assert refreshed is not None
    assert refreshed.status == STATUS_QUICK_MERGED
    assert (batch.directory / "quick_merge_manifest.json").exists()

    for item in result.items:
        copied = Path(item.copied_path)
        assert copied.exists()
        assert sha256_file(copied) == item.sha256
        assert item.source_id in str(copied)
        assert item.warehouse_code in str(copied)
        assert item.carrier_code in str(copied)


def test_quick_merge_detects_missing_source(tmp_path, monkeypatch):

    batch_root = tmp_path / "batches"
    merge_root = tmp_path / "quick"

    monkeypatch.setattr(
        "app.services.batch_service.BATCH_ROOT",
        batch_root,
    )
    monkeypatch.setattr(
        "app.services.invoice_fast_merge_service.QUICK_MERGE_ROOT",
        merge_root,
    )

    missing = tmp_path / "src" / "gone.xlsx"

    records = [
        make_record(
            path=str(missing),
            sha256="deadbeef",
        )
    ]

    batch, _ = ensure_batch_after_first_scan(
        "20260819",
        make_result(records),
    )

    result = run_quick_merge(batch)

    assert not result.passed
    assert any("不存在" in item for item in result.errors)
    assert not (merge_root / batch.batch_id).exists()
    assert list(merge_root.glob(".__*_tmp")) == []

    refreshed = load_batch(batch.directory)

    assert refreshed is not None
    assert refreshed.status == STATUS_FIRST_SCAN_PASSED


def test_quick_merge_detects_sha_mismatch(tmp_path, monkeypatch):

    batch_root = tmp_path / "batches"
    merge_root = tmp_path / "quick"

    monkeypatch.setattr(
        "app.services.batch_service.BATCH_ROOT",
        batch_root,
    )
    monkeypatch.setattr(
        "app.services.invoice_fast_merge_service.QUICK_MERGE_ROOT",
        merge_root,
    )

    src = tmp_path / "src" / "BJC1.xlsx"
    real_hash = _write_file(src, b"current-bytes")

    records = [
        make_record(
            path=str(src),
            sha256="0" * 64,
        )
    ]

    batch, _ = ensure_batch_after_first_scan(
        "20260819",
        make_result(records),
    )

    result = run_quick_merge(batch)

    assert real_hash != "0" * 64
    assert not result.passed
    assert any("SHA256" in item for item in result.errors)
    assert not (merge_root / batch.batch_id).exists()
