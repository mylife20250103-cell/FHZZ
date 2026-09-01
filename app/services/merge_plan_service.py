from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.app_logging import log_event
from app.invoice_config import MERGE_RESULT_ROOT
from app.json_io import read_json, write_json
from app.services.batch_service import (
    STATUS_MERGE_PLAN_READY,
    BatchRecord,
    save_status,
)
from app.services.invoice_adapters import adapter_id, get_adapter


class MergePlanError(Exception):
    pass


@dataclass
class MergePlanResult:
    passed: bool
    batch_id: str
    group_count: int
    plan: dict | None
    errors: list[str]


def output_file_name(
    carrier_code: str,
    warehouse_code: str,
    carton_count: int,
    extension: str = ".xlsx",
) -> str:

    suffix = extension if extension.startswith(".") else f".{extension}"
    return f"{carrier_code}_{warehouse_code}_{carton_count}箱{suffix}"


def planned_output_path(
    date_id: str,
    batch_id: str,
    carrier_code: str,
    warehouse_code: str,
    carton_count: int,
    extension: str = ".xlsx",
) -> Path:

    return (
        MERGE_RESULT_ROOT
        / date_id
        / batch_id
        / output_file_name(
            carrier_code,
            warehouse_code,
            carton_count,
            extension=extension,
        )
    )


def compute_plan_hash(plan: dict) -> str:

    text = json.dumps(
        plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_merge_plan(batch: BatchRecord) -> MergePlanResult:

    manifest_path = batch.directory / "quick_merge_manifest.json"

    if not manifest_path.exists():
        return MergePlanResult(
            passed=False,
            batch_id=batch.batch_id,
            group_count=0,
            plan=None,
            errors=["缺少 quick_merge_manifest.json"],
        )

    manifest = read_json(manifest_path)
    snapshot_files = {
        (item["source_id"], item["carton_number"]): item
        for item in batch.snapshot.get("Files", [])
    }

    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    errors: list[str] = []

    for item in manifest.get("Files", []):

        key = (item["SourceID"], item["CartonNumber"])
        snap = snapshot_files.get(key)

        if snap is None:
            errors.append(
                "Manifest 中的箱子不在 snapshot 中："
                f"{key[0]} + {key[1]}"
            )
            continue

        template_version = snap["template_version"]
        carrier_code = item["CarrierCode"]
        warehouse_code = item["WarehouseCode"]

        try:
            adapter = get_adapter(carrier_code, template_version)
        except Exception as exc:
            errors.append(str(exc))
            continue

        grouped[
            (carrier_code, template_version, warehouse_code)
        ].append(
            {
                "manifest": item,
                "snapshot": snap,
                "adapter_id": adapter.adapter_id(),
            }
        )

    if errors:
        return MergePlanResult(
            passed=False,
            batch_id=batch.batch_id,
            group_count=0,
            plan=None,
            errors=errors,
        )

    groups = []

    for (
        carrier_code,
        template_version,
        warehouse_code,
    ) in sorted(grouped):

        members = grouped[
            (carrier_code, template_version, warehouse_code)
        ]

        members.sort(
            key=lambda item: (
                item["manifest"]["SourceID"],
                item["manifest"]["CartonNumber"],
            )
        )

        adapter_name = members[0]["adapter_id"]
        carton_numbers = [
            item["manifest"]["CartonNumber"] for item in members
        ]
        source_ids = sorted(
            {item["manifest"]["SourceID"] for item in members}
        )
        machine_keys = [
            [
                item["manifest"]["SourceID"],
                item["manifest"]["CartonNumber"],
            ]
            for item in members
        ]
        input_files = [
            item["manifest"]["copied_path"] for item in members
        ]
        carton_count = len(carton_numbers)
        group_adapter = get_adapter(carrier_code, template_version)
        output_path = planned_output_path(
            batch.date_id,
            batch.batch_id,
            carrier_code,
            warehouse_code,
            carton_count,
            extension=group_adapter.output_extension(),
        )
        group_id = (
            f"{batch.batch_id}_"
            f"{carrier_code}_"
            f"{template_version}_"
            f"{warehouse_code}"
        )

        groups.append(
            {
                "group_id": group_id,
                "batch_id": batch.batch_id,
                "carrier_code": carrier_code,
                "template_version": template_version,
                "warehouse_code": warehouse_code,
                "input_count": len(members),
                "input_files": input_files,
                "machine_keys": machine_keys,
                "carton_numbers": carton_numbers,
                "source_ids": source_ids,
                "adapter": adapter_name,
                "planned_output_path": str(output_path),
            }
        )

    plan = {
        "PlanVersion": "1.0",
        "BatchID": batch.batch_id,
        "DateID": batch.date_id,
        "CreatedAt": datetime.now().isoformat(timespec="seconds"),
        "GroupCount": len(groups),
        "Groups": groups,
    }

    plan["MergePlanHash"] = compute_plan_hash(
        {key: value for key, value in plan.items() if key != "MergePlanHash"}
    )

    write_json(batch.directory / "merge_plan.json", plan)
    save_status(batch, STATUS_MERGE_PLAN_READY)

    log_event(
        "merge_plan",
        f"MergePlan 已生成：{len(groups)} 个分组",
        batch_id=batch.batch_id,
        stage="4",
    )

    return MergePlanResult(
        passed=True,
        batch_id=batch.batch_id,
        group_count=len(groups),
        plan=plan,
        errors=[],
    )
