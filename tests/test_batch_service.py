from __future__ import annotations

from pathlib import Path

from app.services.batch_service import (
    STATUS_COMPLETED,
    STATUS_FIRST_SCAN_PASSED,
    STATUS_INVALIDATED,
    BatchError,
    allocate_batch_id,
    compute_content_hash,
    enforce_single_active,
    ensure_batch_after_first_scan,
    find_active_batches,
    invalidate_batch,
    load_batch,
    save_status,
)
from app.services.invoice_scan_service import (
    InvoiceRecord,
    ScanResult,
    is_enabled_flag,
    machine_key,
    validate_carton_number,
    validate_source_id,
)


def make_record(**overrides) -> InvoiceRecord:

    data = {
        "path": r"I:\demo\BJC1.xlsx",
        "sha256": "abc123",
        "carrier_code": "KYD",
        "carrier_name": "快越达",
        "template_version": "1.0",
        "date_id": "20260819",
        "generated_at": "2026-08-19 09:13:31",
        "store_code": "美10",
        "plan_id": "CD",
        "source_id": "85731029",
        "warehouse_code": "BJC1",
        "fba_batch": "FBA19L0YW7PM",
        "carton_number": "FBA19L0YW7PMU000001",
    }

    data.update(overrides)

    return InvoiceRecord(**data)


def make_result(records: list[InvoiceRecord]) -> ScanResult:

    return ScanResult(
        passed=True,
        invoice_count=len(records),
        carton_count=len({item.carton_number for item in records}),
        source_count=len({item.source_id for item in records}),
        warehouse_count=len({item.warehouse_code for item in records}),
        carrier_count=len({item.carrier_code for item in records}),
        records=records,
        errors=[],
        warnings=[],
    )


def test_source_id_rules():

    assert validate_source_id("85731029") is None
    assert validate_source_id("abcdef12") is not None
    assert validate_source_id("ABCDEF1") is not None
    assert validate_source_id("ABCDEF123") is not None
    assert validate_source_id("GHIJKLMN") is not None


def test_carton_number_rules():

    fba = "FBA19L11LFRW"

    assert validate_carton_number(
        fba,
        "FBA19L11LFRWU000001",
    ) is None

    assert validate_carton_number(
        fba,
        "FBA19L11LFRWU000000",
    ) is not None

    assert validate_carton_number(
        fba,
        "FBA19L11LFRWU00001",
    ) is not None

    assert validate_carton_number(
        fba,
        "OTHERU000001",
    ) is not None


def test_machine_key_dedup():

    first = machine_key("85731029", "FBA19L11LFRWU000001")
    second = machine_key("85731029", "FBA19L11LFRWU000001")
    third = machine_key("85731029", "FBA19L11LFRWU000002")

    keys = {first, second, third}

    assert first == second
    assert len(keys) == 2


def test_enabled_flag_accepts_true():

    assert is_enabled_flag("TRUE")
    assert is_enabled_flag("true")
    assert is_enabled_flag("1")
    assert is_enabled_flag("YES")
    assert not is_enabled_flag("FALSE")
    assert not is_enabled_flag("0")


def test_content_hash_stable_regardless_of_order():

    first = make_record(
        carton_number="FBA19L0YW7PMU000001",
        warehouse_code="BJC1",
    )

    second = make_record(
        path=r"I:\demo\PSP3.xlsx",
        sha256="def456",
        warehouse_code="PSP3",
        fba_batch="FBA19L11LFRW",
        carton_number="FBA19L11LFRWU000001",
    )

    hash_a = compute_content_hash(
        "20260819",
        [first, second],
    )

    hash_b = compute_content_hash(
        "20260819",
        [second, first],
    )

    assert hash_a == hash_b

    changed = compute_content_hash(
        "20260819",
        [
            first,
            make_record(
                path=r"I:\demo\PSP3.xlsx",
                sha256="changed",
                warehouse_code="PSP3",
                fba_batch="FBA19L11LFRW",
                carton_number="FBA19L11LFRWU000001",
            ),
        ],
    )

    assert changed != hash_a


def test_batch_allocate_and_reuse(tmp_path, monkeypatch):

    monkeypatch.setattr(
        "app.services.batch_service.BATCH_ROOT",
        tmp_path,
    )

    records = [make_record()]
    result = make_result(records)

    first, action = ensure_batch_after_first_scan(
        "20260819",
        result,
    )

    assert action == "created"
    assert first.batch_id == "20260819-B0001"
    assert first.status == STATUS_FIRST_SCAN_PASSED
    assert (first.directory / "status.json").exists()
    assert (first.directory / "snapshot.json").exists()

    second, action = ensure_batch_after_first_scan(
        "20260819",
        result,
    )

    assert action == "reused"
    assert second.batch_id == "20260819-B0001"

    actives = find_active_batches("20260819")

    assert len(actives) == 1


def test_changed_snapshot_invalidates_and_creates_new(tmp_path, monkeypatch):

    monkeypatch.setattr(
        "app.services.batch_service.BATCH_ROOT",
        tmp_path,
    )

    first_result = make_result([make_record()])

    first, _ = ensure_batch_after_first_scan(
        "20260819",
        first_result,
    )

    changed_result = make_result(
        [
            make_record(
                sha256="new-hash",
            )
        ]
    )

    second, action = ensure_batch_after_first_scan(
        "20260819",
        changed_result,
    )

    assert action == "created"
    assert second.batch_id == "20260819-B0002"

    old = load_batch(first.directory)

    assert old is not None
    assert old.status == STATUS_INVALIDATED
    assert old.status_payload["Reason"] == "原始扫描快照已变化"
    assert old.status_payload["OldSnapshotHash"] == first.content_hash
    assert old.status_payload["NewSnapshotHash"] == second.content_hash

    actives = find_active_batches("20260819")

    assert [item.batch_id for item in actives] == ["20260819-B0002"]


def test_completed_batch_cannot_be_modified(tmp_path, monkeypatch):

    monkeypatch.setattr(
        "app.services.batch_service.BATCH_ROOT",
        tmp_path,
    )

    record, _ = ensure_batch_after_first_scan(
        "20260819",
        make_result([make_record()]),
    )

    completed = save_status(record, STATUS_COMPLETED)

    try:
        save_status(completed, STATUS_FIRST_SCAN_PASSED)
        assert False, "should not allow modifying COMPLETED"
    except BatchError:
        pass

    try:
        invalidate_batch(
            completed,
            "should fail",
            completed.content_hash,
            "xxx",
        )
        assert False, "should not allow invalidating COMPLETED"
    except BatchError:
        pass

    actives = find_active_batches("20260819")

    assert actives == []


def test_legacy_duplicate_batches_keep_latest(tmp_path, monkeypatch):

    monkeypatch.setattr(
        "app.services.batch_service.BATCH_ROOT",
        tmp_path,
    )

    result = make_result([make_record()])

    first, _ = ensure_batch_after_first_scan(
        "20260819",
        result,
    )

    # Simulate the old bug: a second unfinished batch already exists.
    batch_id, batch_dir = allocate_batch_id("20260819")

    from app.json_io import write_json

    snapshot = dict(first.snapshot)
    snapshot["BatchID"] = batch_id

    write_json(batch_dir / "snapshot.json", snapshot)
    write_json(
        batch_dir / "status.json",
        {
            "StatusVersion": "1.0",
            "BatchID": batch_id,
            "DateID": "20260819",
            "Status": STATUS_FIRST_SCAN_PASSED,
            "ContentHash": first.content_hash,
            "CurrentStage": 1,
            "CreatedAt": snapshot["CreatedAt"],
            "UpdatedAt": snapshot["CreatedAt"],
            "InvalidatedAt": "",
            "Reason": "",
            "OldSnapshotHash": "",
            "NewSnapshotHash": "",
        },
    )

    keeper = enforce_single_active("20260819")

    assert keeper is not None
    assert keeper.batch_id == batch_id

    old = load_batch(first.directory)

    assert old is not None
    assert old.status == STATUS_INVALIDATED
