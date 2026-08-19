from __future__ import annotations

import os
import shutil
import stat
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from app.app_logging import log_event
from app.invoice_config import BATCH_ROOT
from app.json_io import read_json, write_json
from app.services.invoice_scan_service import InvoiceRecord, ScanResult


STATUS_FIRST_SCAN_PASSED = "FIRST_SCAN_PASSED"
STATUS_QUICK_MERGED = "QUICK_MERGED"
STATUS_SECOND_SCAN_PASSED = "SECOND_SCAN_PASSED"
STATUS_MERGE_PLAN_READY = "MERGE_PLAN_READY"
STATUS_CONTENT_MERGED = "CONTENT_MERGED"
STATUS_CHECK_PASSED = "CHECK_PASSED"
STATUS_COMPLETED = "COMPLETED"
STATUS_INVALIDATED = "INVALIDATED"

LEGACY_STATUS_MAP = {
    "FIRST_STAGE_PASSED": STATUS_FIRST_SCAN_PASSED,
}

ACTIVE_STATUSES = {
    STATUS_FIRST_SCAN_PASSED,
    STATUS_QUICK_MERGED,
    STATUS_SECOND_SCAN_PASSED,
    STATUS_MERGE_PLAN_READY,
    STATUS_CONTENT_MERGED,
    STATUS_CHECK_PASSED,
}

STATUS_TO_STAGE = {
    STATUS_FIRST_SCAN_PASSED: 1,
    STATUS_QUICK_MERGED: 2,
    STATUS_SECOND_SCAN_PASSED: 3,
    STATUS_MERGE_PLAN_READY: 4,
    STATUS_CONTENT_MERGED: 5,
    STATUS_CHECK_PASSED: 6,
    STATUS_COMPLETED: 7,
    STATUS_INVALIDATED: 0,
}

STAGE_LABELS = {
    1: "① 原始扫描",
    2: "② 快速合并",
    3: "③ 二次扫描",
    4: "④ MergePlan",
    5: "⑤ 内容合并",
    6: "⑥ 结果检查",
    7: "⑦ 完成",
}


class BatchError(Exception):
    pass


@dataclass
class BatchRecord:
    batch_id: str
    date_id: str
    directory: Path
    status: str
    content_hash: str
    snapshot: dict
    status_payload: dict

    @property
    def stage(self) -> int:

        return STATUS_TO_STAGE.get(
            self.status,
            0,
        )


def now_iso() -> str:

    return datetime.now().isoformat(
        timespec="seconds"
    )


def _file_identity(item: InvoiceRecord | dict) -> dict:

    if not isinstance(item, dict):
        item = asdict(item)

    return {
        "carton_number": item["carton_number"],
        "carrier_code": item["carrier_code"],
        "fba_batch": item["fba_batch"],
        "path": item["path"],
        "plan_id": item["plan_id"],
        "sha256": item["sha256"],
        "source_id": item["source_id"],
        "store_code": item["store_code"],
        "template_version": item["template_version"],
        "warehouse_code": item["warehouse_code"],
    }


def compute_content_hash(
    date_id: str,
    records: list[InvoiceRecord] | list[dict],
) -> str:

    import hashlib
    import json

    files = [
        _file_identity(item)
        for item in records
    ]

    files.sort(
        key=lambda item: (
            item["source_id"],
            item["carton_number"],
            item["path"],
        )
    )

    payload = {
        "DateID": date_id,
        "Files": files,
    }

    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def date_batch_root(date_id: str) -> Path:

    return BATCH_ROOT / date_id


def batch_directory(date_id: str, batch_id: str) -> Path:

    return date_batch_root(date_id) / batch_id


def allocate_batch_id(date_id: str) -> tuple[str, Path]:

    date_root = date_batch_root(date_id)

    date_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    for number in range(1, 10000):

        batch_id = f"{date_id}-B{number:04d}"
        batch_dir = date_root / batch_id

        try:
            batch_dir.mkdir()
            return batch_id, batch_dir

        except FileExistsError:
            continue

    raise BatchError("无法分配新的 BatchID")


def _normalize_status(raw: str) -> str:

    return LEGACY_STATUS_MAP.get(raw, raw)


def _synthesize_status(snapshot: dict) -> dict:

    date_id = snapshot["DateID"]
    files = snapshot.get("Files", [])

    status = _normalize_status(
        snapshot.get(
            "Status",
            STATUS_FIRST_SCAN_PASSED,
        )
    )

    content_hash = snapshot.get("ContentHash")

    if not content_hash:
        content_hash = compute_content_hash(
            date_id,
            files,
        )

    created_at = snapshot.get(
        "CreatedAt",
        now_iso(),
    )

    return {
        "StatusVersion": "1.0",
        "BatchID": snapshot["BatchID"],
        "DateID": date_id,
        "Status": status,
        "ContentHash": content_hash,
        "CurrentStage": STATUS_TO_STAGE.get(status, 1),
        "CreatedAt": created_at,
        "UpdatedAt": created_at,
        "InvalidatedAt": "",
        "Reason": "",
        "OldSnapshotHash": "",
        "NewSnapshotHash": "",
    }


def load_batch(directory: Path) -> BatchRecord | None:

    snapshot_path = directory / "snapshot.json"

    if not snapshot_path.exists():
        return None

    snapshot = read_json(snapshot_path)

    status_path = directory / "status.json"

    if status_path.exists():
        status_payload = read_json(status_path)
        status_payload["Status"] = _normalize_status(
            status_payload.get("Status", "")
        )
    else:
        status_payload = _synthesize_status(snapshot)
        write_json(status_path, status_payload)

    content_hash = status_payload.get("ContentHash", "")

    if not content_hash:
        content_hash = compute_content_hash(
            snapshot["DateID"],
            snapshot.get("Files", []),
        )
        status_payload["ContentHash"] = content_hash
        write_json(status_path, status_payload)

    hash_path = directory / "snapshot.sha256"

    if not hash_path.exists():
        hash_path.write_text(
            content_hash,
            encoding="ascii",
        )

    return BatchRecord(
        batch_id=status_payload["BatchID"],
        date_id=status_payload["DateID"],
        directory=directory,
        status=status_payload["Status"],
        content_hash=content_hash,
        snapshot=snapshot,
        status_payload=status_payload,
    )


def list_batches(date_id: str) -> list[BatchRecord]:

    date_root = date_batch_root(date_id)

    if not date_root.exists():
        return []

    records = []

    for path in sorted(date_root.iterdir()):

        if not path.is_dir():
            continue

        record = load_batch(path)

        if record is not None:
            records.append(record)

    return records


def find_active_batches(date_id: str) -> list[BatchRecord]:

    return [
        record
        for record in list_batches(date_id)
        if record.status in ACTIVE_STATUSES
    ]


def save_status(
    record: BatchRecord,
    status: str,
    extra: dict | None = None,
) -> BatchRecord:

    if record.status == STATUS_COMPLETED:
        raise BatchError(
            f"COMPLETED Batch 不可修改：{record.batch_id}"
        )

    if (
        record.status == STATUS_INVALIDATED
        and status != STATUS_INVALIDATED
    ):
        raise BatchError(
            f"INVALIDATED Batch 不可修改：{record.batch_id}"
        )

    payload = dict(record.status_payload)
    payload["Status"] = status
    payload["CurrentStage"] = STATUS_TO_STAGE.get(status, 0)
    payload["UpdatedAt"] = now_iso()

    if extra:
        payload.update(extra)

    write_json(
        record.directory / "status.json",
        payload,
    )

    record.status = status
    record.status_payload = payload

    return record


def invalidate_batch(
    record: BatchRecord,
    reason: str,
    old_snapshot_hash: str,
    new_snapshot_hash: str,
) -> BatchRecord:

    if record.status == STATUS_COMPLETED:
        raise BatchError(
            f"COMPLETED Batch 不可作废：{record.batch_id}"
        )

    return save_status(
        record,
        STATUS_INVALIDATED,
        extra={
            "Reason": reason,
            "InvalidatedAt": now_iso(),
            "OldSnapshotHash": old_snapshot_hash,
            "NewSnapshotHash": new_snapshot_hash,
        },
    )


def enforce_single_active(date_id: str) -> BatchRecord | None:
    """
    同一 DateID 只保留一个未完成 Batch。
    若存在多个，保留编号最大的，其余标记 INVALIDATED。
    """

    actives = find_active_batches(date_id)

    if not actives:
        return None

    actives.sort(key=lambda item: item.batch_id)

    keeper = actives[-1]

    for other in actives[:-1]:

        invalidate_batch(
            other,
            "同一 DateID 只允许一个未完成 Batch",
            other.content_hash,
            keeper.content_hash,
        )

    return load_batch(keeper.directory)


def scan_result_from_snapshot(snapshot: dict) -> ScanResult:

    records = [
        InvoiceRecord(**item)
        for item in snapshot.get("Files", [])
    ]

    return ScanResult(
        passed=True,
        invoice_count=int(
            snapshot.get("InvoiceCount", len(records))
        ),
        carton_count=int(
            snapshot.get("CartonCount", len(records))
        ),
        source_count=int(
            snapshot.get("SourceCount", 0)
        ),
        warehouse_count=int(
            snapshot.get("WarehouseCount", 0)
        ),
        carrier_count=int(
            snapshot.get("CarrierCount", 0)
        ),
        records=records,
        errors=[],
        warnings=[],
        batch_id=snapshot.get("BatchID"),
        snapshot_path=None,
    )


def _write_snapshot(
    batch_dir: Path,
    batch_id: str,
    date_id: str,
    result: ScanResult,
    content_hash: str,
) -> dict:

    snapshot = {
        "SnapshotVersion": "1.0",
        "BatchID": batch_id,
        "DateID": date_id,
        "CreatedAt": now_iso(),
        "Status": STATUS_FIRST_SCAN_PASSED,
        "ContentHash": content_hash,
        "InvoiceCount": result.invoice_count,
        "CartonCount": result.carton_count,
        "SourceCount": result.source_count,
        "WarehouseCount": result.warehouse_count,
        "CarrierCount": result.carrier_count,
        "Files": [
            asdict(record)
            for record in result.records
        ],
    }

    write_json(batch_dir / "snapshot.json", snapshot)

    (batch_dir / "snapshot.sha256").write_text(
        content_hash,
        encoding="ascii",
    )

    return snapshot


def ensure_batch_after_first_scan(
    date_id: str,
    result: ScanResult,
) -> tuple[BatchRecord, str]:
    """
    Stage1 PASS 后创建或复用 Batch。

    返回 (record, action)，action 为 reused 或 created。
    """

    if not result.passed:
        raise BatchError("扫描未通过，禁止创建 Batch")

    content_hash = compute_content_hash(
        date_id,
        result.records,
    )

    active = enforce_single_active(date_id)

    if active is not None:

        if active.content_hash == content_hash:
            return active, "reused"

        invalidate_batch(
            active,
            "原始扫描快照已变化",
            active.content_hash,
            content_hash,
        )

    batch_id, batch_dir = allocate_batch_id(date_id)

    snapshot = _write_snapshot(
        batch_dir,
        batch_id,
        date_id,
        result,
        content_hash,
    )

    created_at = snapshot["CreatedAt"]

    status_payload = {
        "StatusVersion": "1.0",
        "BatchID": batch_id,
        "DateID": date_id,
        "Status": STATUS_FIRST_SCAN_PASSED,
        "ContentHash": content_hash,
        "CurrentStage": 1,
        "CreatedAt": created_at,
        "UpdatedAt": created_at,
        "InvalidatedAt": "",
        "Reason": "",
        "OldSnapshotHash": "",
        "NewSnapshotHash": "",
    }

    write_json(
        batch_dir / "status.json",
        status_payload,
    )

    record = BatchRecord(
        batch_id=batch_id,
        date_id=date_id,
        directory=batch_dir,
        status=STATUS_FIRST_SCAN_PASSED,
        content_hash=content_hash,
        snapshot=snapshot,
        status_payload=status_payload,
    )

    return record, "created"


def official_output_dir(record: BatchRecord) -> Path:

    from app.invoice_config import MERGE_RESULT_ROOT

    return (
        MERGE_RESULT_ROOT
        / record.date_id
        / record.batch_id
    )


def list_official_xlsx(record: BatchRecord) -> list[Path]:

    directory = official_output_dir(record)

    if not directory.exists():
        return []

    return [
        path
        for path in sorted(directory.glob("*.xlsx"))
        if not path.name.startswith("~$")
        and not path.name.startswith(".__")
    ]


def missing_official_outputs(record: BatchRecord) -> list[Path]:

    plan_path = record.directory / "merge_plan.json"

    if not plan_path.exists():
        if list_official_xlsx(record):
            return []
        return [official_output_dir(record)]

    plan = read_json(plan_path)
    missing = []

    for group in plan.get("Groups", []):
        path = Path(group.get("planned_output_path", ""))
        if not path.exists():
            missing.append(path)

    return missing


def _make_writable(path: str) -> None:

    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        return


def _rmtree_onerror(func, path, _exc_info) -> None:

    _make_writable(path)
    func(path)


def remove_tree_best_effort(
    path: Path,
    retries: int = 5,
) -> str:
    """
    尽量删除目录。OneDrive / Excel 锁文件时允许留下残留，
    返回警告文本；删除成功则返回空字符串。
    """

    if not path.exists():
        return ""

    last_error = None

    for attempt in range(retries):
        try:
            shutil.rmtree(path, onerror=_rmtree_onerror)
            if not path.exists():
                return ""
        except OSError as exc:
            last_error = exc

        time.sleep(0.35 * (attempt + 1))

    leftover = []

    if path.exists():
        for child in sorted(path.rglob("*"), reverse=True):
            try:
                _make_writable(str(child))
                if child.is_dir():
                    child.rmdir()
                else:
                    child.unlink()
            except OSError:
                leftover.append(child.name)

        try:
            path.rmdir()
        except OSError as exc:
            last_error = exc

    if not path.exists():
        return ""

    detail = str(last_error) if last_error else "未知原因"
    names = "、".join(leftover[:8])
    extra = f"｜残留 {names}" if names else ""
    return f"{path}：{detail}{extra}"


def complete_batch(record: BatchRecord) -> BatchRecord:

    if record.status != STATUS_CHECK_PASSED:
        raise BatchError(
            "只有 CHECK_PASSED 的 Batch 才能完成："
            f"{record.batch_id} 当前是 {record.status}"
        )

    from app.services.invoice_fast_merge_service import quick_merge_root

    missing = missing_official_outputs(record)
    existing = list_official_xlsx(record)

    if missing or not existing:
        directory = official_output_dir(record)
        names = "\n".join(
            path.name if path.name else str(path)
            for path in (missing or [directory])[:12]
        )
        raise BatchError(
            "合并结果目录里没有完整的最终发票，"
            "禁止完成 Batch。\n\n"
            f"目录：{directory}\n"
            f"缺少：\n{names}\n\n"
            "请重新执行内容合并后再完成。"
        )

    for other in list_batches(record.date_id):

        if other.batch_id == record.batch_id:
            continue

        if other.status != STATUS_COMPLETED:
            continue

        old_dir = official_output_dir(other)

        if not old_dir.exists():
            continue

        for xlsx in old_dir.glob("*.xlsx"):
            if xlsx.name.startswith("~$"):
                continue
            try:
                xlsx.unlink()
            except OSError as exc:
                log_event(
                    "batch",
                    f"未能删除旧结果 {xlsx.name}：{exc}",
                    level="WARNING",
                    batch_id=record.batch_id,
                    stage="7",
                )

    quick_root = quick_merge_root(record.batch_id)
    cleanup_warning = ""

    if quick_root.exists():
        cleanup_warning = remove_tree_best_effort(quick_root)

        if cleanup_warning:
            log_event(
                "batch",
                "快速合并临时目录未能完全删除，Batch 仍标记为完成",
                level="WARNING",
                batch_id=record.batch_id,
                stage="7",
                detail=cleanup_warning,
            )

    extra = {}
    if cleanup_warning:
        extra["CleanupWarning"] = cleanup_warning

    return save_status(
        record,
        STATUS_COMPLETED,
        extra=extra or None,
    )
