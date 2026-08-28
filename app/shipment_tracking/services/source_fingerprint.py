from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.shipment_tracking.domain.commands import ShipmentCreateCommand


def build_source_fingerprint(command: ShipmentCreateCommand) -> str:

    payload = json.dumps(
        {
            "carton_numbers": sorted(
                carton.carton_number.strip() for carton in command.cartons
            ),
            "fba_shipment_id": command.fba_shipment_id.strip(),
            "ship_date": command.ship_date.isoformat(),
            "source_file": _normalize_source_file(command.source_file),
            "store_code": command.store_code.strip(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_source_file(source_file: str) -> str:

    unified = source_file.replace("\\", "/").strip()
    return Path(unified).name.casefold()
