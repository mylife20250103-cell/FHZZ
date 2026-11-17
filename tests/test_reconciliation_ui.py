from pathlib import Path

import pytest

from app.reconciliation.invoices import scan_directory
from app.reconciliation.parser import parse_reports
from app.reconciliation.service import reconcile
from tests.test_reconciliation_inputs import write_mc


@pytest.fixture
def panel(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from app.pages.reconciliation_panel import ReconciliationPanel
    app=QApplication.instance() or QApplication([])
    widget=ReconciliationPanel(directory=tmp_path)
    yield widget
    if widget.worker is not None:
        widget.worker.wait(5000)
        app.processEvents()
    widget.close();widget.deleteLater();app.processEvents()


def preview(panel,tmp_path):
    write_mc(tmp_path/'MC_GYR3_3箱.xlsx')
    scan=scan_directory(tmp_path)
    panel.accept_scan(scan)
    text='MC1(FBA1,FBA2,FBA3) 美速达快提卡派 42kg'
    panel.report_edit.setPlainText(text)
    parsed=parse_reports(text)
    panel.accept_comparison((reconcile(scan,parsed),parsed,text))
    return scan


def test_text_and_directory_changes_invalidate_results(panel,tmp_path):
    preview(panel,tmp_path)
    assert len(panel.visible_rows())==1 and panel.export_button.isEnabled()
    panel.report_edit.setPlainText('MC1(FBA1) 渠道 1kg')
    assert panel.rows==[] and not panel.export_button.isEnabled()
    assert panel.scan is not None
    panel.source_edit.setText(str(tmp_path/'other'))
    assert panel.scan is None and not panel.compare_button.isEnabled()


def test_remeasure_filter_and_box_preview(panel,tmp_path):
    preview(panel,tmp_path)
    assert panel.table.rowCount()==1 and panel.visible_rows()[0].needs_remeasure
    panel.only_remeasure.setChecked(True)
    assert panel.table.rowCount()==1
    panel.report_edit.setPlainText('MC1(FBA1,FBA2,FBA3) 美速达快提卡派 41kg')
    parsed=parse_reports(panel.report_edit.toPlainText())
    panel.accept_comparison((reconcile(panel.scan,parsed),parsed,panel.report_edit.toPlainText()))
    assert panel.table.rowCount()==0 and not panel.export_button.isEnabled()
    panel.only_remeasure.setChecked(False)
    assert panel.table.rowCount()==1


def test_new_success_directory_clears_old_text_and_queues_while_busy(panel,tmp_path,monkeypatch):
    preview(panel,tmp_path)
    folder=tmp_path/'new_batch';folder.mkdir()
    calls=[];monkeypatch.setattr(panel,'start_scan',lambda:calls.append(True))
    panel.set_busy(True)
    assert not panel.can_close() and not panel.source_edit.isEnabled()
    panel.receive_merge({'directory':str(folder),'carrier':'MC'})
    assert panel.source_edit.text()==str(tmp_path)
    panel.set_busy(False)
    assert panel.source_edit.text()==str(folder)
    assert not panel.report_edit.toPlainText() and panel.rows==[] and calls


def test_new_batch_during_worker_discards_old_scan_preview(panel,tmp_path):
    from PySide6.QtCore import QElapsedTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    scan=preview(panel,tmp_path)
    folder=tmp_path/'next';folder.mkdir()
    panel.run_job(lambda:scan,panel.accept_scan,'reading')
    panel.receive_merge({'directory':str(folder)})
    clock=QElapsedTimer();clock.start()
    while panel.worker is not None and clock.elapsed()<5000:
        QApplication.processEvents();QTest.qWait(10)
    assert panel.worker is None and not panel.busy
    assert panel.source_edit.text()==str(folder)
    assert panel.scan is not None and panel.scan.directory==folder.resolve()
    assert panel.rows==[] and not panel.export_button.isEnabled()


def test_export_uses_current_filter_and_captures_raw_snapshot(panel,tmp_path,monkeypatch):
    import app.pages.reconciliation_panel as ui
    preview(panel,tmp_path)
    panel.only_remeasure.setChecked(True)
    target=tmp_path/'output.xlsx'
    monkeypatch.setattr(ui.QFileDialog,'getSaveFileName',lambda *a,**k:(str(target),'xlsx'))
    captured=[]
    monkeypatch.setattr(panel,'run_job',lambda job,done,message:captured.append(job()))
    panel.export_current()
    assert captured==[target.resolve()] and target.exists()


def test_export_dialog_new_batch_cannot_change_the_export_snapshot(panel,tmp_path,monkeypatch):
    from PySide6.QtCore import QElapsedTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from openpyxl import load_workbook
    import app.pages.reconciliation_panel as ui
    preview(panel,tmp_path)
    new=tmp_path/'new';new.mkdir()
    write_mc(new/'MC_GYR3_1箱.xlsx',[('FBA9U000001',8,40,30,30)])
    target=tmp_path/'export.xlsx'
    def choose(*args,**kwargs):
        panel.receive_merge({'directory':str(new)})
        clock=QElapsedTimer();clock.start()
        while panel.worker is not None and clock.elapsed()<3000:
            QApplication.processEvents();QTest.qWait(10)
        return str(target),'xlsx'
    monkeypatch.setattr(ui.QFileDialog,'getSaveFileName',choose)
    panel.export_current()
    clock=QElapsedTimer();clock.start()
    while panel.worker is not None and clock.elapsed()<5000:
        QApplication.processEvents();QTest.qWait(10)
    assert target.exists()
    w=load_workbook(target,data_only=True)
    assert w['货件核对']['A7'].value=='MC1'
    assert w['货代原文']['B2'].value.startswith('MC1(FBA1,FBA2,FBA3)')
    w.close()


def test_invoice_page_has_fifth_card_and_merge_signal_connection(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication,QLabel
    import app.pages.invoice_page as ui
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui.InvoicePage,'restore_active_batch',lambda self:None)
    monkeypatch.setattr(ui,'load_source_entries',lambda:[])
    monkeypatch.setattr(ui,'portals_grouped_by_carrier',lambda:{})
    page=ui.InvoicePage()
    labels=[l for l in page.findChildren(QLabel) if l.text()=='5  货件数据核对']
    assert len(labels)==1
    calls=[];monkeypatch.setattr(page.reconciliation_panel,'start_scan',lambda:calls.append(True))
    page.content_merge_succeeded.emit({'directory':str(tmp_path)})
    assert page.reconciliation_panel.source_edit.text()==str(tmp_path) and calls
    page.reconciliation_panel.set_busy(True)
    assert not page.can_close()
    page.reconciliation_panel.set_busy(False)
    page.close();page.deleteLater();app.processEvents()
