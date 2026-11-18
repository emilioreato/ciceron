import os, tempfile, importlib.machinery, importlib.util
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PySide6.QtCore import QDate, QTime, Qt
from PySide6.QtTest import QTest
with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
 os.environ['APPDATA']=tmp
 os.environ['CICERON_HOME']=str(Path(tmp)/'Aplicacion')
 path=Path(__file__).resolve().parents[1] / 'src' / 'ciceron.pyw'; l=importlib.machinery.SourceFileLoader('ci',str(path)); s=importlib.util.spec_from_loader(l.name,l); m=importlib.util.module_from_spec(s); l.exec_module(m)
 m.write(m.CONFIG,dict(m.DEFAULT,show_timer=False,guardian=False,interval='inválido',theme='dark'))
 a=m.QApplication([]); a.setQuitOnLastWindowClosed(False); c=m.App(); notices=[]
 assert c.cfg['interval']==m.DEFAULT['interval']
 aware=m.dt.datetime.fromisoformat('2027-11-12T12:15+00:00')
 assert m.target({'target':aware.isoformat()})==aware.astimezone().replace(tzinfo=None)
 m.QMessageBox.information=lambda *args:notices.append(args[-1])
 def dialog(action):
  errors=[]
  def use():
   try:
    d=a.activeModalWidget(); assert d is not None
    action(d)
   except Exception as e:
    errors.append(repr(e)); d.reject()
  m.QTimer.singleShot(50,use); c.goal_dialog().exec(); assert not errors,errors
 def start(d, date, hour=None):
  d.findChild(m.QDateEdit).setDate(QDate(*date)); chk=next(x for x in d.findChildren(m.QCheckBox) if x.text()=='Elegir una hora')
  chk.setChecked(hour is not None)
  if hour: d.findChild(m.QTimeEdit).setTime(QTime(*hour))
  next(x for x in d.findChildren(m.QPushButton) if x.text()=='Guardar y empezar').click()
 def first(d):
  stop=next(x for x in d.findChildren(m.QPushButton) if x.text()=='Detener')
  assert not stop.isEnabled() and stop.objectName()=='destructive'
  assert not d.findChild(m.QTimeEdit).isEnabled()
  chk=next(x for x in d.findChildren(m.QCheckBox) if x.text()=='Elegir una hora')
  chk.setFocus(); a.processEvents(); QTest.keyClick(chk,Qt.Key.Key_Space); assert chk.isChecked()
  QTest.keyClick(chk,Qt.Key.Key_Space); assert not chk.isChecked()
  button=next(x for x in d.findChildren(m.QPushButton) if x.text()=='Calendario')
  assert button.parentWidget() is d.findChild(m.QDateEdit).parentWidget()
  button_frame=button.grab().toImage()
  assert button_frame.pixelColor(8,button_frame.height()//2).lightness()<110
  button.click()
  picker=a.activePopupWidget(); assert picker is not None and picker.isVisible()
  assert '#171e30' in picker.styleSheet()
  next(x for x in picker.findChildren(m.QPushButton) if x.text()=='Cerrar').click()
  assert not picker.isVisible() and d.isVisible()
  button.click()
  assert a.activePopupWidget() is picker
  picker.findChild(m.QCalendarWidget).clicked.emit(QDate(2027,11,12))
  assert d.findChild(m.QDateEdit).date()==QDate(2027,11,12)
  start(d,(2027,11,12))
 dialog(first)
 assert c.cfg['target']=='2027-11-12T00:00' and c.cfg['show_timer'] is True
 if c._count_fits: assert c.count.isVisible()
 else: assert notices
 dialog(lambda d:next(x for x in d.findChildren(m.QPushButton) if x.text()=='Detener').click())
 assert c.cfg['show_timer'] is False and not c.count.isVisible() and c.cfg['target']=='2027-11-12T00:00'
 dialog(lambda d:start(d,(2027,11,12),(13,45)))
 assert c.cfg['target']=='2027-11-12T13:45' and c.cfg['show_timer']
 c.cfg['target']='2027-11-12T23:59'
 def legacy(d):
  chk=next(x for x in d.findChildren(m.QCheckBox) if x.text()=='Elegir una hora')
  assert chk.isChecked() and next(x for x in d.findChildren(m.QPushButton) if x.text()=='Detener').isEnabled()
  chk.setChecked(False); assert d.findChild(m.QTimeEdit).time()==QTime(0,0)
  chk.setChecked(True); assert d.findChild(m.QTimeEdit).time()==QTime(23,59)
  next(x for x in d.findChildren(m.QPushButton) if x.text()=='Guardar y empezar').click()
 dialog(legacy); assert c.cfg['target']=='2027-11-12T23:59'
 old=c._show_count; c._show_count=lambda:False; notices.clear()
 dialog(lambda d:start(d,(2027,11,12))); assert notices and 'queda oculto' in notices[-1]
 c._show_count=old; c.tray.hide(); c.window.close(); c.count.close()
 print('Empezar, detener, medianoche, hora elegida, fecha previa y aviso si queda oculto: correctos')
