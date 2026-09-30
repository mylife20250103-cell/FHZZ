from __future__ import annotations

import logging
from pathlib import Path

from app.app_logging import LOGGER_NAME, setup_logging
from app.invoice_config import choose_writable_root, dir_writable


def test_dir_writable_true(tmp_path):
    assert dir_writable(tmp_path / "logs") is True
    assert not (tmp_path / "logs" / ".ims_write_test").exists()


def test_choose_writable_root_skips_unwritable(tmp_path, monkeypatch):
    bad = tmp_path / "onedrive-exe"
    good = tmp_path / "appdata"

    def fake_writable(path: Path) -> bool:
        return good in path.parents or path == good or path.parent == good

    monkeypatch.setattr("app.invoice_config.dir_writable", fake_writable)
    assert choose_writable_root(bad, good) == good


def test_setup_logging_falls_back_when_onedrive_log_fails(tmp_path, monkeypatch):
    import app.app_logging as app_logging

    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    bad = tmp_path / "onedrive-logs"
    good = tmp_path / "appdata"
    monkeypatch.setattr(app_logging, "LOG_ROOT", bad)
    monkeypatch.setattr(app_logging, "appdata_root", lambda: good)

    real_handler = logging.FileHandler

    def fake_handler(filename, encoding="utf-8"):
        path = Path(filename)
        if path.parent == bad:
            raise OSError(22, "Invalid argument", str(path))
        return real_handler(filename, encoding=encoding)

    monkeypatch.setattr(app_logging.logging, "FileHandler", fake_handler)
    result = setup_logging()
    try:
        assert any(isinstance(item, real_handler) for item in result.handlers)
        assert (good / "logs" / "app.log").exists()
    finally:
        for handler in list(result.handlers):
            handler.close()
            result.removeHandler(handler)


def test_setup_logging_never_raises_if_all_paths_fail(monkeypatch):
    import app.app_logging as app_logging

    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    monkeypatch.setattr(app_logging, "_attach_file_handler", lambda *_args, **_kwargs: False)
    result = setup_logging()
    try:
        assert any(isinstance(item, logging.NullHandler) for item in result.handlers)
    finally:
        logger.handlers.clear()
