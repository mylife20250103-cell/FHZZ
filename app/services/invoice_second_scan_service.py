from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.app_logging import log_event
from app.json_io import read_json, write_json
from app.services.batch_service import (
    STATUS_SECOND_SCAN_PASSED,
    BatchRecord,
    save_status,
)
from app.services.invoice_fast_merge_service import quick_merge_root
from app.services.invoice_scan_service import (
    collect_invoice_files,
    read_system_meta,
    sha256_file,
    validate_carton_number,
    validate_source_id,
)


class SecondScanError(Exception):
    pass


@dataclass
class IdentityItem:
    source_id: str
    carton_number: str
    sha256: str
    carrier_code: str
    warehouse_code: str
    fba_batch: str
    date_id: str
    template_version: str
    path: str


@dataclass
class SecondScanResult:
    passed: bool
    batch_id: str
    file_count: int
    errors: list[str]


def _key(item: IdentityItem) -> tuple[str, str]:

    return (item.source_id, item.carton_number)


def snapshot_identity_items(snapshot: dict) -> list[IdentityItem]:

    items = []

    for record in snapshot.get("Files", []):

        items.append(
            IdentityItem(
                source_id=record["source_id"],
                carton_number=record["carton_number"],
                sha256=record["sha256"],
                carrier_code=record["carrier_code"],
                warehouse_code=record["warehouse_code"],
                fba_batch=record["fba_batch"],
                date_id=record["date_id"],
                template_version=record["template_version"],
                path=record["path"],
            )
        )

    return items


def manifest_identity_items(manifest: dict) -> list[IdentityItem]:

    snapshot_by_key = {}

    items = []

    for record in manifest.get("Files", []):

        items.append(
            IdentityItem(
                source_id=record["SourceID"],
                carton_number=record["CartonNumber"],
                sha256=record["sha256"],
                carrier_code=record["CarrierCode"],
                warehouse_code=record["WarehouseCode"],
                fba_batch=record["FBABatch"],
                date_id=manifest.get("DateID", ""),
                template_version="",
                path=record["copied_path"],
            )
        )

        snapshot_by_key[(record["SourceID"], record["CartonNumber"])] = record

    return items


def compare_identity_sets(
    snapshot_items: list[IdentityItem],
    manifest_items: list[IdentityItem],
    scan_items: list[IdentityItem],
) -> list[str]:

    errors = []

    snap_map = {_key(item): item for item in snapshot_items}
    man_map = {_key(item): item for item in manifest_items}
    scan_map = {_key(item): item for item in scan_items}

    snap_keys = set(snap_map)
    man_keys = set(man_map)
    scan_keys = set(scan_map)

    if len(snapshot_items) != len(manifest_items) or len(snapshot_items) != len(scan_items):
        errors.append(
            "文件总数不一致："
            f"Stage1={len(snapshot_items)} "
            f"Stage2={len(manifest_items)} "
            f"Stage3={len(scan_items)}"
        )

    for label, left, right in (
        ("Stage1 vs Stage2", snap_keys, man_keys),
        ("Stage1 vs Stage3", snap_keys, scan_keys),
        ("Stage2 vs Stage3", man_keys, scan_keys),
    ):
        missing = sorted(left - right)
        extra = sorted(right - left)

        if missing:
            errors.append(f"{label} 缺少 Key：{missing}")

        if extra:
            errors.append(f"{label} 多余 Key：{extra}")

    for key in sorted(snap_keys & man_keys & scan_keys):

        snap = snap_map[key]
        man = man_map[key]
        scan = scan_map[key]

        if not (snap.sha256 == man.sha256 == scan.sha256):
            errors.append(
                f"{key[0]} + {key[1]}：SHA256 不一致"
            )

        for field in (
            "carrier_code",
            "warehouse_code",
            "fba_batch",
            "carton_number",
            "source_id",
        ):
            values = {
                getattr(snap, field),
                getattr(man, field),
                getattr(scan, field),
            }

            if len(values) != 1:
                errors.append(
                    f"{key[0]} + {key[1]}：{field} 不一致"
                )

        if snap.date_id and scan.date_id and snap.date_id != scan.date_id:
            errors.append(
                f"{key[0]} + {key[1]}：DateID 不一致"
            )

        if (
            snap.template_version
            and scan.template_version
            and snap.template_version != scan.template_version
        ):
            errors.append(
                f"{key[0]} + {key[1]}：TemplateVersion 不一致"
            )

    return errors


def run_second_scan(batch: BatchRecord) -> SecondScanResult:

    manifest_path = batch.directory / "quick_merge_manifest.json"

    if not manifest_path.exists():
        return SecondScanResult(
            passed=False,
            batch_id=batch.batch_id,
            file_count=0,
            errors=["缺少 quick_merge_manifest.json，请先完成快速合并"],
        )

    manifest = read_json(manifest_path)
    root = Path(manifest.get("Root") or quick_merge_root(batch.batch_id))

    if not root.exists():
        return SecondScanResult(
            passed=False,
            batch_id=batch.batch_id,
            file_count=0,
            errors=[f"快速合并目录不存在：{root}"],
        )

    errors: list[str] = []

    files = collect_invoice_files([root])

    scan_items: list[IdentityItem] = []

    for path in files:

        meta, meta_error = read_system_meta(path)

        if meta_error:
            errors.append(meta_error)
            continue

        if not meta.get("DateID"):
            errors.append(
                f"{path.name}：DateID 为空"
            )
            continue

        source_error = validate_source_id(meta["SourceID"])
        if source_error:
            errors.append(f"{path.name}：{source_error}")

        carton_error = validate_carton_number(
            meta["FBABatch"],
            meta["CartonNumber"],
        )
        if carton_error:
            errors.append(f"{path.name}：{carton_error}")

        try:
            file_hash = sha256_file(path)
        except Exception as exc:
            errors.append(f"{path.name}：SHA256 失败：{exc}")
            continue

        scan_items.append(
            IdentityItem(
                source_id=meta["SourceID"],
                carton_number=meta["CartonNumber"],
                sha256=file_hash,
                carrier_code=meta["CarrierCode"].strip().upper(),
                warehouse_code=meta["WarehouseCode"],
                fba_batch=meta["FBABatch"],
                date_id=meta["DateID"],
                template_version=meta["TemplateVersion"],
                path=str(path),
            )
        )

    snapshot_items = snapshot_identity_items(batch.snapshot)

    # Manifest DateID already set; fill template_version from snapshot.
    manifest_items = manifest_identity_items(manifest)
    snap_by_key = {_key(item): item for item in snapshot_items}

    for item in manifest_items:
        snap = snap_by_key.get(_key(item))
        if snap is not None:
            item.template_version = snap.template_version
            item.date_id = snap.date_id

    errors.extend(
        compare_identity_sets(
            snapshot_items,
            manifest_items,
            scan_items,
        )
    )

    if errors:
        log_event(
            "invoice_second_scan",
            "二次扫描失败",
            level="ERROR",
            batch_id=batch.batch_id,
            stage="3",
            detail="\n".join(errors),
        )

        return SecondScanResult(
            passed=False,
            batch_id=batch.batch_id,
            file_count=len(scan_items),
            errors=errors,
        )

    payload = {
        "ScanVersion": "1.0",
        "BatchID": batch.batch_id,
        "DateID": batch.date_id,
        "ScannedAt": datetime.now().isoformat(timespec="seconds"),
        "FileCount": len(scan_items),
        "Root": str(root),
        "Status": STATUS_SECOND_SCAN_PASSED,
    }

    write_json(batch.directory / "second_scan.json", payload)
    save_status(batch, STATUS_SECOND_SCAN_PASSED)

    log_event(
        "invoice_second_scan",
        f"二次扫描通过：{len(scan_items)} 个文件",
        batch_id=batch.batch_id,
        stage="3",
    )

    return SecondScanResult(
        passed=True,
        batch_id=batch.batch_id,
        file_count=len(scan_items),
        errors=[],
    )
