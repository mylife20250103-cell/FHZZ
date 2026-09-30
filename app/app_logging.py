from __future__ import annotations

import logging
from pathlib import Path

from app.invoice_config import LOG_ROOT, appdata_root


LOGGER_NAME = "invoice_merge"


def _attach_file_handler(logger: logging.Logger, directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(
            directory / "app.log",
            encoding="utf-8",
        )
    except OSError:
        return False
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s"
        )
    )
    logger.addHandler(handler)
    return True


def setup_logging() -> logging.Logger:

    logger = logging.getLogger(LOGGER_NAME)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    for directory in (LOG_ROOT, appdata_root() / "logs"):
        if _attach_file_handler(logger, directory):
            return logger

    logger.addHandler(logging.NullHandler())
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
