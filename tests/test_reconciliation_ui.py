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


def test_partial_association_displays_omitted_fbas_and_filters_whole_ticket(panel,tmp_path):
    from app.reconciliation.export import HEADERS
    write_mc(tmp_path/'MC_GYR3_3箱.xlsx')
    scan=scan_directory(tmp_path)
    panel.accept_scan(scan)
    text='MC1(FBA1) 美速达快提卡派 42kg'
    parsed=parse_reports(text)
    panel.accept_comparison((reconcile(scan,parsed),parsed,text))
    assert panel.table.rowCount()==1
    assert panel.table.item(0,HEADERS.index('关联方式')).text()=='部分FBA辅助关联'
    assert panel.table.item(0,HEADERS.index('报数未列FBA')).text()=='FBA2\nFBA3'
    assert panel.table.item(0,HEADERS.index('箱数')).text()=='3'
    panel.only_remeasure.setChecked(True)
    assert panel.table.rowCount()==1
    assert panel.table.item(0,HEADERS.index('核准上限(kg)')).text()=='41.000'
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


@pytest.fixture
def main_window(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QApplication,QWidget
    import app.main_window as ui
    import app.pages.invoice_page as invoice_ui
    app=QApplication.instance() or QApplication([])
    class UnrelatedPage(QWidget):
        navigate_requested=Signal(str)
        def receive_merge(self,context):pass
        def can_close(self):return True
    for name in ('HomePage','InquiryPage','CustomsPage','TrackingPage','WatchlistPage',
                 'BatchEditPage','SensitivePage','MaintainPage'):
        monkeypatch.setattr(ui,name,UnrelatedPage)
    monkeypatch.setattr(invoice_ui.InvoicePage,'restore_active_batch',lambda self:None)
    monkeypatch.setattr(invoice_ui,'load_source_entries',lambda:[])
    monkeypatch.setattr(invoice_ui,'portals_grouped_by_carrier',lambda:{})
    if hasattr(ui,'ReconciliationPage'):
        original=ui.ReconciliationPage
        monkeypatch.setattr(ui,'ReconciliationPage',lambda:original(directory=tmp_path))
    window=ui.MainWindow()
    yield window
    from app.pages.reconciliation_panel import ReconciliationPanel
    for widget in window.findChildren(ReconciliationPanel):
        if widget.worker is not None:
            widget.worker.wait(5000);app.processEvents()
        widget.set_busy(False)
    window.close();window.deleteLater();app.processEvents()


def test_own_page_receives_merge_and_preserves_state_across_navigation(main_window,tmp_path):
    from PySide6.QtCore import QElapsedTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from app.pages.reconciliation_panel import ReconciliationPanel
    window=main_window
    keys=list(window.nav_buttons)
    assert keys[keys.index('invoice')+1:keys.index('invoice')+3]==['reconciliation','customs']
    page=window.pages['reconciliation'];panel=page.panel
    assert not window.pages['invoice'].findChildren(ReconciliationPanel)
    folder=tmp_path/'merged';folder.mkdir()
    write_mc(folder/'MC_GYR3_3箱.xlsx')
    window.pages['invoice'].content_merge_succeeded.emit({'directory':str(folder),'carrier':'MC'})
    timer=QElapsedTimer();timer.start()
    while panel.worker is not None and timer.elapsed()<5000:
        QApplication.processEvents();QTest.qWait(10)
    assert panel.worker is None and panel.scan.directory==folder.resolve()
    assert len(panel.scan.invoices)==1
    text='MC1(FBA1) 美速达快提卡派 42kg'
    panel.report_edit.setPlainText(text)
    parsed=parse_reports(text)
    panel.accept_comparison((reconcile(panel.scan,parsed),parsed,text))
    window.nav_buttons['reconciliation'].click()
    assert window.stack.currentWidget() is page
    window.go_to('invoice');window.go_to('reconciliation')
    assert window.stack.currentWidget() is page and panel.report_edit.toPlainText()==text
    assert panel.table.rowCount()==1 and panel.visible_rows()[0].needs_remeasure


def test_busy_reconciliation_page_blocks_window_close_even_when_hidden(main_window):
    from PySide6.QtGui import QCloseEvent
    page=main_window.pages['reconciliation']
    main_window.go_to('invoice');page.panel.set_busy(True)
    event=QCloseEvent();main_window.closeEvent(event)
    assert not event.isAccepted()
    page.panel.set_busy(False)
    event=QCloseEvent();main_window.closeEvent(event)
    assert event.isAccepted()


def test_remeasure_marker_survives_selection_and_clears_for_allowed_result(panel,tmp_path):
    from PySide6.QtWidgets import QApplication,QLabel
    from app.reconciliation.export import HEADERS
    panel.resize(1400,900);panel.show()
    scan=preview(panel,tmp_path);col=HEADERS.index('核对结果')
    panel.table.selectRow(0);QApplication.processEvents()
    badge=panel.table.cellWidget(0,col)
    assert badge is not None
    assert badge.findChild(QLabel,'RemeasureBadge').isVisible()
    assert panel.table.item(0,col).text()=='需申请重测'
    text='MC1(FBA1,FBA2,FBA3) 美速达快提卡派 41kg'
    parsed=parse_reports(text)
    panel.accept_comparison((reconcile(scan,parsed),parsed,text))
    assert panel.table.cellWidget(0,col) is None
    assert panel.table.item(0,col).text()=='重量在允许范围'
    panel.only_remeasure.setChecked(True)
    assert panel.table.rowCount()==0


def test_double_click_on_remeasure_marker_still_opens_all_box_details(panel,tmp_path,monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QTableWidget
    from app.reconciliation.export import HEADERS
    import app.pages.reconciliation_panel as ui
    panel.resize(1400,900);panel.show();preview(panel,tmp_path)
    QApplication.processEvents()
    observed=[]
    def inspect(dialog):
        table=dialog.findChild(QTableWidget)
        observed.append([table.item(r,1).text() for r in range(table.rowCount())])
        return 0
    monkeypatch.setattr(ui.QDialog,'exec',inspect)
    item=panel.table.item(0,HEADERS.index('核对结果'))
    viewport=panel.table.viewport()
    position=panel.table.visualItemRect(item).center()
    # 离屏平台不提供全屏widgetAt，按真实子控件命中测试选择接收者。
    target=viewport.childAt(position) or viewport
    QTest.mouseClick(target,Qt.LeftButton,Qt.NoModifier,target.mapFrom(viewport,position))
    QTest.mouseDClick(target,Qt.LeftButton,Qt.NoModifier,target.mapFrom(viewport,position))
    assert observed==[['FBA1','FBA2','FBA3']]
