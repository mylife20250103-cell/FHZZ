from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal

from app.app_logging import log_event


class TaskWorker(QThread):
    """
    统一后台任务线程。

    UI 更新只能通过 Signal 回到主线程。
    Excel COM 任务必须设置 use_com=True。
    """

    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(
        self,
        func: Callable[[], Any],
        *,
        use_com: bool = False,
        module: str = "",
        batch_id: str = "",
        stage: str = "",
        parent=None,
    ):

        super().__init__(parent)

        self._func = func
        self._use_com = use_com
        self._module = module
        self._batch_id = batch_id
        self._stage = stage

    def run(self):

        initialized = False

        try:

            if self._use_com:
                import pythoncom

                pythoncom.CoInitialize()
                initialized = True

            result = self._func()
            self.succeeded.emit(result)

        except Exception as exc:

            tb = traceback.format_exc()

            log_event(
                self._module or "worker",
                str(exc),
                level="ERROR",
                batch_id=self._batch_id,
                stage=self._stage,
                error_type=type(exc).__name__,
                detail=tb,
            )

            self.failed.emit(str(exc), tb)

        finally:

            if initialized:
                import pythoncom

                pythoncom.CoUninitialize()
