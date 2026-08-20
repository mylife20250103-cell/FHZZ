from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from app.app_logging import log_event
from app.invoice_config import LOCAL_TEMP_ROOT
from app.json_io import read_json
from app.services.batch_service import (
    STATUS_CONTENT_MERGED,
    BatchRecord,
    save_status,
)
from app.services.invoice_adapters import get_adapter
from app.services.invoice_scan_service import read_system_meta


class ContentMergeError(Exception):
    pass


@dataclass
class ContentMergeResult:
    passed: bool
    batch_id: str
    output_files: list[str]
    errors: list[str]


def _cleanup(path: Path) -> None:

    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def run_content_merge(batch: BatchRecord) -> ContentMergeResult:

    plan_path = batch.directory / "merge_plan.json"

    if not plan_path.exists():
        return ContentMergeResult(
            passed=False,
            batch_id=batch.batch_id,
            output_files=[],
            errors=["缺少 merge_plan.json"],
        )

    plan = read_json(plan_path)
    groups = plan.get("Groups", [])
    merge_plan_hash = plan.get("MergePlanHash", "")

    if not groups:
        return ContentMergeResult(
            passed=False,
            batch_id=batch.batch_id,
            output_files=[],
            errors=["MergePlan 没有分组"],
        )

    work_root = LOCAL_TEMP_ROOT / batch.batch_id / "content_merge"
    _cleanup(work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    outputs: list[str] = []
    errors: list[str] = []

    try:

        for group in groups:

            adapter = get_adapter(
                group["carrier_code"],
                group["template_version"],
            )

            group_work = work_root / group["group_id"]
            group_work.mkdir(parents=True, exist_ok=True)

            local_inputs = []
            group_errors = []

            for source in group["input_files"]:
                source_path = Path(source)
                local_path = group_work / source_path.name

                if not source_path.exists():
                    group_errors.append(
                        f"缺少输入文件：{source_path}"
                    )
                    continue

                try:
                    shutil.copy2(source_path, local_path)
                except OSError as exc:
                    group_errors.append(
                        f"无法复制输入文件：{source_path.name}：{exc}"
                    )
                    continue

                local_inputs.append(local_path)

                meta, meta_error = read_system_meta(local_path)
                if meta_error:
                    group_errors.append(meta_error)
                    continue

                group_errors.extend(
                    adapter.validate_source(local_path, meta)
                )

            errors.extend(group_errors)

            if group_errors:
                continue

            enriched = dict(group)
            enriched["input_files"] = [str(path) for path in local_inputs]
            enriched["date_id"] = batch.date_id
            enriched["merge_plan_hash"] = merge_plan_hash

            ext = adapter.output_extension()
            temp_output = group_work / f"merged_tmp{ext}"

            try:
                adapter.merge_group(enriched, temp_output)
            except Exception as exc:
                errors.append(
                    f"{group['group_id']} 合并失败：{exc}"
                )
                continue

            output_errors = adapter.validate_output(temp_output, enriched)
            if output_errors:
                errors.extend(output_errors)
                continue

            official = Path(group["planned_output_path"]).with_suffix(ext)
            official.parent.mkdir(parents=True, exist_ok=True)

            temp_official = official.with_name(
                ".__" + official.name
            )

            if temp_official.exists():
                temp_official.unlink()

            shutil.copy2(temp_output, temp_official)

            if official.exists():
                official.unlink()

            temp_official.replace(official)
            outputs.append(str(official))

        if errors:
            for path in outputs:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass

            return ContentMergeResult(
                passed=False,
                batch_id=batch.batch_id,
                output_files=[],
                errors=errors,
            )

        save_status(batch, STATUS_CONTENT_MERGED)

        log_event(
            "invoice_content_merge",
            f"内容合并成功：{len(outputs)} 个文件",
            batch_id=batch.batch_id,
            stage="5",
        )

        return ContentMergeResult(
            passed=True,
            batch_id=batch.batch_id,
            output_files=outputs,
            errors=[],
        )

    finally:
        _cleanup(work_root)
