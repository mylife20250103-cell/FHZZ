from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:

    return json.loads(
        path.read_text(encoding="utf-8")
    )


def write_json(path: Path, data: Any) -> None:

    path.parent.mkdir(parents=True, exist_ok=True)

    text = json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
    )

    tmp_path = path.with_name(
        path.name + ".tmp"
    )

    tmp_path.write_text(
        text,
        encoding="utf-8",
    )

    tmp_path.replace(path)
