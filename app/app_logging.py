from __future__ import annotations

import logging
from pathlib import Path

from app.invoice_config import LOG_ROOT


LOGGER_NAME = "invoice_merge"


def setup_logging() -> logging.Logger:

    logger = logging.getLogger(LOGGER_NAME)

    if logger.handlers:
        return logger

    LOG_ROOT.mkdir(parents=True, exist_ok=True)

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    handler = logging.FileHandler(
        LOG_ROOT / "app.log",
        encoding="utf-8",
    )

    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s"
        )
    )

    logger.addHandler(handler)

    return logger


def log_event(
    module: str,
    message: str,
    *,
    level: str = "INFO",
    batch_id: str = "",
    stage: str = "",
    file: str = "",
    error_type: str = "",
    detail: str = "",
) -> None:

    logger = setup_logging()

    parts = [
        f"module={module}",
        f"batch={batch_id or '-'}",
        f"stage={stage or '-'}",
        f"file={file or '-'}",
        f"error_type={error_type or '-'}",
        message,
    ]

    if detail:
        parts.append(detail)

    text = " | ".join(parts)

    log_fn = getattr(
        logger,
        level.lower(),
        logger.info,
    )

    log_fn(text)
