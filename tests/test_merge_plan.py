from __future__ import annotations

from app.services.invoice_adapters import get_adapter, list_adapter_ids
from app.services.invoice_second_scan_service import (
    IdentityItem,
    compare_identity_sets,
)
from app.services.merge_plan_service import (
    build_merge_plan,
    output_file_name,
)
from tests.test_batch_service import make_record, make_result
from app.services.batch_service import (
    STATUS_MERGE_PLAN_READY,
    STATUS_QUICK_MERGED,
    ensure_batch_after_first_scan,
    save_status,
)
from app.json_io import write_json


def _item(**overrides) -> IdentityItem:

    data = dict(
        source_id="85731029",
        carton_number="FBA19L0YW7PMU000001",
        sha256="aaa",
        carrier_code="KYD",
        warehouse_code="BJC1",
        fba_batch="FBA19L0YW7PM",
        date_id="20260819",
        template_version="1.0",
        path=r"D:\a.xlsx",
    )
    data.update(overrides)
    return IdentityItem(**data)


def test_second_scan_sets_must_be_equal():

    base = _item()
    snap = [base]
    man = [_item(path=r"D:\copied\a.xlsx")]
    scan = [_item(path=r"D:\copied\a.xlsx")]

    assert compare_identity_sets(snap, man, scan) == []


def test_second_scan_detects_missing_and_sha():

    snap = [
        _item(),
        _item(
            carton_number="FBA19L11LFRWU000001",
            fba_batch="FBA19L11LFRW",
            warehouse_code="PSP3",
            sha256="bbb",
        ),
    ]

    man = [_item(path=r"D:\copied\a.xlsx")]
    scan = [_item(sha256="changed")]

    errors = compare_identity_sets(snap, man, scan)

    assert any("缺少" in item for item in errors)
    assert any("SHA256" in item for item in errors)


def test_adapter_selection():

    kyd = get_adapter("KYD", "1.0")
    mc = get_adapter("mc", "1.0")

    assert kyd.adapter_id() == "KYD:1.0"
    assert mc.adapter_id() == "MC:1.0"
    assert "KYD:1.0" in list_adapter_ids()

    try:
        get_adapter("KYD", "9.9")
        assert False, "unknown adapter should fail"
    except Exception as exc:
        assert "没有匹配" in str(exc)


def test_merge_plan_groups_by_warehouse(tmp_path, monkeypatch):

    monkeypatch.setattr(
        "app.services.batch_service.BATCH_ROOT",
        tmp_path / "batches",
    )
    monkeypatch.setattr(
        "app.services.merge_plan_service.MERGE_RESULT_ROOT",
        tmp_path / "out",
    )

    records = [
        make_record(warehouse_code="BJC1"),
        make_record(
            path=r"I:\demo\IND9.xlsx",
            sha256="h2",
            warehouse_code="IND9",
            fba_batch="FBA19L107VS5",
            carton_number="FBA19L107VS5U000001",
        ),
        make_record(
            path=r"I:\demo\PSP3-1.xlsx",
            sha256="h3",
            warehouse_code="PSP3",
            fba_batch="FBA19L11LFRW",
            carton_number="FBA19L11LFRWU000001",
        ),
        make_record(
            path=r"I:\demo\PSP3-2.xlsx",
            sha256="h4",
            warehouse_code="PSP3",
            fba_batch="FBA19L11LFRW",
            carton_number="FBA19L11LFRWU000002",
        ),
        make_record(
            path=r"I:\demo\PSP3-3.xlsx",
            sha256="h5",
            warehouse_code="PSP3",
            fba_batch="FBA19L11LFRW",
            carton_number="FBA19L11LFRWU000003",
        ),
        make_record(
            path=r"I:\demo\SCK4.xlsx",
            sha256="h6",
            warehouse_code="SCK4",
            fba_batch="FBA19L1301QV",
            carton_number="FBA19L1301QVU000001",
        ),
        make_record(
            path=r"I:\demo\TEB9.xlsx",
            sha256="h7",
            warehouse_code="TEB9",
            fba_batch="FBA19L12X5FG",
            carton_number="FBA19L12X5FGU000001",
        ),
    ]

    batch, _ = ensure_batch_after_first_scan(
        "20260819",
        make_result(records),
    )

    save_status(batch, STATUS_QUICK_MERGED)

    write_json(
        batch.directory / "quick_merge_manifest.json",
        {
            "ManifestVersion": "1.0",
            "BatchID": batch.batch_id,
            "DateID": "20260819",
            "Files": [
                {
                    "SourceID": item.source_id,
                    "CartonNumber": item.carton_number,
                    "CarrierCode": item.carrier_code,
                    "WarehouseCode": item.warehouse_code,
                    "FBABatch": item.fba_batch,
                    "original_path": item.path,
                    "copied_path": str(
                        tmp_path / "copied" / PathLikeName(item)
                    ),
                    "sha256": item.sha256,
                }
                for item in records
            ],
        },
    )

    result = build_merge_plan(batch)

    assert result.passed
    assert result.group_count == 5

    names = [
        output_file_name(
            group["carrier_code"],
            group["warehouse_code"],
            group["input_count"],
            extension=".xls",
        )
        for group in result.plan["Groups"]
    ]

    assert "KYD_BJC1_1箱.xls" in names
    assert "KYD_PSP3_3箱.xls" in names
    assert "KYD_IND9_1箱.xls" in names
    assert "KYD_SCK4_1箱.xls" in names
    assert "KYD_TEB9_1箱.xls" in names

    psp3 = next(
        group
        for group in result.plan["Groups"]
        if group["warehouse_code"] == "PSP3"
    )

    assert psp3["adapter"] == "KYD:1.0"
    assert psp3["input_count"] == 3
    assert len(psp3["machine_keys"]) == 3

    refreshed = __import__(
        "app.services.batch_service",
        fromlist=["load_batch"],
    ).load_batch(batch.directory)

    assert refreshed.status == STATUS_MERGE_PLAN_READY


def PathLikeName(item) -> str:

    return f"{item.warehouse_code}_{item.carton_number}.xlsx"
