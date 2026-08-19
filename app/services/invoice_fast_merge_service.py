from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.app_logging import log_event
from app.invoice_config import QUICK_MERGE_ROOT
from app.json_io import write_json
from app.services.batch_service import (
    STATUS_QUICK_MERGED,
    BatchError,
    BatchRecord,
    save_status,
)
from app.services.invoice_scan_service import sha256_file


class QuickMergeError(Exception):
    pass


@dataclass
class QuickMergeItem:
    source_id: str
    carton_number: str
    carrier_code: str
    warehouse_code: str
    fba_batch: str
    original_path: str
    copied_path: str
    sha256: str


@dataclass
class QuickMergeResult:
    passed: bool
    batch_id: str
    root: str
    items: list[QuickMergeItem]
    errors: list[str]


def quick_merge_root(batch_id: str) -> Path:

    return QUICK_MERGE_ROOT / batch_id


def _now_iso() -> str:

    return datetime.now().isoformat(timespec="seconds")


def _relative_dest(record: dict) -> Path:

    return Path(
        record["carrier_code"]
    ) / record["warehouse_code"] / record["source_id"] / Path(
        record["path"]
    ).name


def _collect_copied_xlsx(root: Path) -> list[Path]:

    files = []

    for path in root.rglob("*"):

        if not path.is_file():
            continue

        if path.name.startswith("~$"):
            continue

        if path.suffix.lower() != ".xlsx":
            continue

        files.append(path)

    return sorted(files)


def _cleanup(path: Path) -> None:

    if path.exists():
        shutil.rmtree(path)


def run_quick_merge(batch: BatchRecord) -> QuickMergeResult:

    if not batch.snapshot.get("Files"):
        raise QuickMergeError("Batch snapshot 没有发票文件")

    snapshot_files = list(batch.snapshot["Files"])

    final_root = quick_merge_root(batch.batch_id)
    temp_root = QUICK_MERGE_ROOT / f".__{batch.batch_id}_tmp"

    errors: list[str] = []

    _cleanup(temp_root)
    QUICK_MERGE_ROOT.mkdir(parents=True, exist_ok=True)

    planned: list[tuple[dict, Path, Path]] = []

    try:

        seen_dest = set()

        for record in snapshot_files:

            original = Path(record["path"])
            relative = _relative_dest(record)
            temp_dest = temp_root / relative

            if relative in seen_dest:
                errors.append(
                    "快速合并目标文件名冲突："
                    f"{relative}"
                )
                continue

            seen_dest.add(relative)

            if not original.exists():
                errors.append(
                    "原始发票不存在："
                    f"{original}"
                )
                continue

            planned.append((record, original, temp_dest))

        if errors:
            raise QuickMergeError("；".join(errors))

        for record, original, temp_dest in planned:

            temp_dest.parent.mkdir(parents=True, exist_ok=True)

            shutil.copy2(original, temp_dest)

            copied_hash = sha256_file(temp_dest)

            if copied_hash != record["sha256"]:
                errors.append(
                    "复制后 SHA256 不一致："
                    f"{original.name}"
                )

        copied_files = _collect_copied_xlsx(temp_root)

        expected_keys = {
            (item["source_id"], item["carton_number"])
            for item in snapshot_files
        }

        if len(copied_files) < len(snapshot_files):
            errors.append(
                f"漏复制：期望 {len(snapshot_files)} 个，"
                f"实际 {len(copied_files)} 个"
            )

        if len(copied_files) > len(snapshot_files):
            errors.append(
                f"多复制：期望 {len(snapshot_files)} 个，"
                f"实际 {len(copied_files)} 个"
            )

        if errors:
            raise QuickMergeError("；".join(errors))

        items = []

        for record, original, temp_dest in planned:

            relative = temp_dest.relative_to(temp_root)
            final_dest = final_root / relative

            items.append(
                QuickMergeItem(
                    source_id=record["source_id"],
                    carton_number=record["carton_number"],
                    carrier_code=record["carrier_code"],
                    warehouse_code=record["warehouse_code"],
                    fba_batch=record["fba_batch"],
                    original_path=str(original),
                    copied_path=str(final_dest),
                    sha256=record["sha256"],
                )
            )

        copied_keys = {
            (item.source_id, item.carton_number)
            for item in items
        }

        if copied_keys != expected_keys:
            missing = expected_keys - copied_keys
            extra = copied_keys - expected_keys
            raise QuickMergeError(
                "机器 Key 不一致："
                f"缺少 {sorted(missing)} "
                f"多余 {sorted(extra)}"
            )

        if final_root.exists():
            _cleanup(final_root)

        temp_root.replace(final_root)

        manifest = {
            "ManifestVersion": "1.0",
            "BatchID": batch.batch_id,
            "DateID": batch.date_id,
            "CreatedAt": _now_iso(),
            "Root": str(final_root),
            "FileCount": len(items),
            "Files": [
                {
                    "SourceID": item.source_id,
                    "CartonNumber": item.carton_number,
                    "CarrierCode": item.carrier_code,
                    "WarehouseCode": item.warehouse_code,
                    "FBABatch": item.fba_batch,
                    "original_path": item.original_path,
                    "copied_path": item.copied_path,
                    "sha256": item.sha256,
                }
                for item in items
            ],
        }

        write_json(
            batch.directory / "quick_merge_manifest.json",
            manifest,
        )

        save_status(batch, STATUS_QUICK_MERGED)

        log_event(
            "invoice_fast_merge",
            f"快速合并成功：{len(items)} 个文件",
            batch_id=batch.batch_id,
            stage="2",
        )

        return QuickMergeResult(
            passed=True,
            batch_id=batch.batch_id,
            root=str(final_root),
            items=items,
            errors=[],
        )

    except Exception as exc:

        _cleanup(temp_root)

        log_event(
            "invoice_fast_merge",
            str(exc),
            level="ERROR",
            batch_id=batch.batch_id,
            stage="2",
            error_type=type(exc).__name__,
        )

        if isinstance(exc, (QuickMergeError, BatchError)):
            return QuickMergeResult(
                passed=False,
                batch_id=batch.batch_id,
                root=str(final_root),
                items=[],
                errors=[str(exc)],
            )

        return QuickMergeResult(
            passed=False,
            batch_id=batch.batch_id,
            root=str(final_root),
            items=[],
            errors=[f"快速合并失败：{exc}"],
        )
