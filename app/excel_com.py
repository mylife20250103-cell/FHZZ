from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from app.app_logging import log_event


XL_SHEET_VERY_HIDDEN = 2
MSO_PICTURE = 13


@contextmanager
def excel_application() -> Iterator[object]:

    import win32com.client as win32

    excel = win32.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.AskToUpdateLinks = False
    excel.AlertBeforeOverwriting = False
    excel.ScreenUpdating = False
    excel.EnableEvents = False

    try:
        yield excel
    finally:
        try:
            excel.DisplayAlerts = False
            excel.Quit()
        except Exception as exc:
            log_event(
                "excel_com",
                f"Excel.Quit 失败：{exc}",
                level="ERROR",
                error_type=type(exc).__name__,
            )


def open_workbook(excel, path, *, read_only: bool = False):

    return excel.Workbooks.Open(
        str(path),
        UpdateLinks=0,
        ReadOnly=read_only,
        IgnoreReadOnlyRecommended=True,
    )


def close_workbook(workbook, save: bool = False) -> None:

    if workbook is None:
        return

    try:
        workbook.Close(SaveChanges=save)
    except Exception:
        try:
            workbook.Close(SaveChanges=False)
        except Exception:
            pass
