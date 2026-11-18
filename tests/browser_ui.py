import hashlib,os,sys,tempfile
from pathlib import Path
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
tmp=tempfile.TemporaryDirectory(); os.environ['APPDATA']=tmp.name; os.environ['CICERON_HOME']=str(Path(tmp.name)/'Aplicacion')
sys.path.insert(0,str(Path('src').resolve()))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QMessageBox,QInputDialog,QLabel,QPushButton
import browser_bridge as bridge
import browser_ui
from browser_ui import BrowserDialog,SelectorDialog,X_SIDEBAR
app=QApplication([])
QMessageBox.information=lambda *a,**k: QMessageBox.StandardButton.Ok
QMessageBox.warning=lambda *a,**k: QMessageBox.StandardButton.Ok
d=BrowserDialog();d.change_enabled(True);assert bridge.load_policy()['enabled'] is True
def indicator_color(dialog):
    frame = dialog.status_indicator.grab().toImage()
    return frame.pixelColor(frame.rect().center()).name()

assert indicator_color(d) == '#e5656c'
with patch.object(bridge, 'sessions', return_value=[{'browser': 'Edge', 'enabled': True}]):
    d.refresh()
    assert indicator_color(d) == '#2db47b'
    assert d.status.text() == 'Activado · Edge'
with patch.object(bridge, 'sessions', return_value=[{'browser': 'Edge', 'enabled': False}]):
    d.refresh()
    assert indicator_color(d) == '#e5656c'
d.sidebar.setChecked(True);d.save_selectors();assert bridge.load_policy()['x_selectors']==[X_SIDEBAR]
assert not d.save_selectors(['invalid; color:red'])
assert bridge.load_policy()['x_selectors']==[X_SIDEBAR]
phrase='Frase de prueba'
browser_ui.PASSPHRASE_HASH=hashlib.sha256(phrase.encode()).hexdigest()
QInputDialog.getText=lambda *a,**k: (phrase,True)
d.change_enabled(False);assert bridge.load_policy()['enabled'] is False
d.show();app.processEvents();assert d.width()>=430; d.close()
panel=BrowserDialog(attached=True); panel.show(); app.processEvents()
assert panel.width()<450
assert panel.toggle.accessibleName()=='Activar Pausa Feed'
assert panel.status.text()=='Desactivado · Sin navegador conectado'
indicator = panel.status_indicator.geometry()
title = panel.findChild(QLabel, 'title').geometry()
assert panel.width() - indicator.right() - 1 == 14
assert indicator.left() - title.right() - 1 == 14
assert abs(indicator.center().y() - title.center().y()) <= 1
assert panel.toggle.geometry().right()==panel.edit_rules.geometry().right()
original_size=panel.size()

def edit_rules(commit):
    editor=app.activeModalWidget()
    try:
        assert isinstance(editor,SelectorDialog)
        assert panel.size()==original_size and editor.rules.count()==0
        editor.entry.setText('.sin-guardar')
        editor.add_pending()
        assert editor.rules.item(0).text()=='.sin-guardar'
        if commit:
            editor.rules.item(0).setText('.guardada')
            editor.entry.setText('.temporal')
            editor.add_pending()
            next(button for button in editor.findChildren(QPushButton) if button.text()=='Quitar').click()
            editor.entry.setText('.nueva')
            next(button for button in editor.findChildren(QPushButton) if button.text()=='Guardar').click()
        else:
            editor.reject()
    except Exception as error:
        errors.append(error)
        if editor is not None:
            editor.reject()

errors=[]
QTimer.singleShot(0,lambda:edit_rules(False)); panel.edit_rules.click()
assert not errors,errors
assert bridge.load_policy()['x_selectors']==[X_SIDEBAR]
QTimer.singleShot(0,lambda:edit_rules(True)); panel.edit_rules.click()
assert not errors,errors
assert bridge.load_policy()['x_selectors']==[X_SIDEBAR,'.guardada','.nueva']
panel.sidebar.click()
assert bridge.load_policy()['x_selectors']==['.guardada','.nueva']
assert panel.rules_count.text()=='2 reglas'
panel.close()
print('Panel: estado visible, acciones alineadas, activar, pausar y editar reglas: correcto')
