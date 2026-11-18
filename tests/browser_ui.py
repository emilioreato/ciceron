import hashlib,os,sys,tempfile
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
tmp=tempfile.TemporaryDirectory(); os.environ['APPDATA']=tmp.name; os.environ['CICERON_HOME']=str(Path(tmp.name)/'Aplicacion')
sys.path.insert(0,str(Path('src').resolve()))
from PySide6.QtWidgets import QApplication,QMessageBox,QInputDialog
import browser_bridge as bridge
import browser_ui
from browser_ui import BrowserDialog,X_SIDEBAR
app=QApplication([])
QMessageBox.information=lambda *a,**k: QMessageBox.StandardButton.Ok
QMessageBox.warning=lambda *a,**k: QMessageBox.StandardButton.Ok
d=BrowserDialog();d.change_enabled(True);assert bridge.load_policy()['enabled'] is True
d.sidebar.setChecked(True);d.save_selectors();assert bridge.load_policy()['x_selectors']==[X_SIDEBAR]
d.selectors.setPlainText('invalid; color:red'); d.save_selectors(); assert bridge.load_policy()['x_selectors']==[X_SIDEBAR]
phrase='Frase de prueba'
browser_ui.PASSPHRASE_HASH=hashlib.sha256(phrase.encode()).hexdigest()
QInputDialog.getText=lambda *a,**k: (phrase,True)
d.change_enabled(False);assert bridge.load_policy()['enabled'] is False
d.show();app.processEvents();assert d.size().width()>=540; d.close()
panel=BrowserDialog(attached=True); panel.show(); app.processEvents()
assert panel.width()<450 and panel.advanced.isHidden()
assert panel.toggle.accessibleName()=='Activar Pausa Feed'
assert not panel.status.text() and panel.status.toolTip()=='Desactivado · Sin conexión'
panel.show_options(True); app.processEvents(); assert panel.advanced.isVisible()
panel.selectors.setPlainText('.sin-guardar')
panel.sidebar.click()
assert bridge.load_policy()['x_selectors']==[]
assert panel.selectors.toPlainText()=='.sin-guardar'
panel.close()
print('Panel: activar, pausar, guardar y rechazar selectores inválidos: correcto')
