"""Protocolo local de mensajería nativa de Cicerón para Chromium."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
from app_paths import data_root
from power_state import low_power
import queue
import struct
import subprocess
import sys
import threading
import time
import uuid

DATA = data_root()
POLICY = DATA / 'navegador.json'
SESSIONS = DATA / 'navegadores-activos'
LIMIT = 1024 * 1024
DEFAULT = {'enabled': None, 'x_selectors': []}
HEARTBEAT_SECONDS = 25


def validate(value):
    if not isinstance(value, dict): raise ValueError('La configuración debe ser un objeto.')
    enabled = value.get('enabled')
    if enabled is not None and type(enabled) is not bool: raise ValueError('Estado inválido.')
    selectors = value.get('x_selectors', [])
    if not isinstance(selectors, list) or len(selectors) > 25: raise ValueError('Máximo 25 selectores.')
    clean = []
    for selector in selectors:
        if not isinstance(selector, str): raise ValueError('Selector inválido.')
        selector = selector.strip()
        if not selector or len(selector) > 300 or any(c in selector for c in '{};@\r\n'):
            raise ValueError('Cada selector debe ocupar una línea y no contener llaves, punto y coma ni @.')
        if selector not in clean: clean.append(selector)
    return {'enabled': enabled, 'x_selectors': clean}


def load_policy():
    try:
        with POLICY.open(encoding='utf-8') as f: return validate(json.load(f))
    except FileNotFoundError: return dict(DEFAULT)


def save_policy(policy):
    value=validate(policy)
    DATA.mkdir(parents=True, exist_ok=True)
    tmp=DATA / ('navegador-' + uuid.uuid4().hex + '.tmp')
    try:
        with tmp.open('w', encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False,indent=2); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,POLICY)
    finally:
        try: tmp.unlink(missing_ok=True)
        except OSError: pass


def sessions(now=None):
    now=time.time() if now is None else now
    result=[]
    try: files=list(SESSIONS.glob('*.json'))
    except OSError: return []
    for file in files:
        try:
            with file.open(encoding='utf-8') as f: item=json.load(f)
            if isinstance(item,dict) and isinstance(item.get('time'),(int,float)) and 0 <= now-item['time'] < 35:
                result.append(item)
        except (OSError,ValueError,TypeError): continue
    return result


def read_message(stream):
    header=stream.read(4)
    if not header: return None
    if len(header)!=4: raise ValueError('Cabecera incompleta.')
    size=struct.unpack('<I',header)[0]
    if size > LIMIT: raise ValueError('Mensaje demasiado grande.')
    payload=stream.read(size)
    if len(payload)!=size: raise ValueError('Mensaje incompleto.')
    result=json.loads(payload.decode('utf-8'))
    if not isinstance(result,dict): raise ValueError('Mensaje inválido.')
    return result


def send_message(stream, value):
    payload=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(payload)>LIMIT: raise ValueError('Respuesta demasiado grande.')
    stream.write(struct.pack('<I',len(payload))+payload); stream.flush()


def open_ciceron():
    executable = Path(sys.executable).with_name('Ciceron.exe')
    if not executable.is_file():
        return False
    try:
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
        subprocess.Popen([str(executable), '--abrir'], cwd=executable.parent, env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


class BrowserInbox:
    """Wait for the pipe reader, a policy directory change or the next heartbeat."""
    def __init__(self, directory):
        self.queue = queue.SimpleQueue()
        self.lock = threading.Lock()
        self.event = self.watch = None
        if os.name != 'nt':
            return
        kernel = self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateEventW.restype = wintypes.HANDLE
        kernel.FindFirstChangeNotificationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
        kernel.FindFirstChangeNotificationW.restype = wintypes.HANDLE
        kernel.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
                                                 wintypes.BOOL, wintypes.DWORD]
        kernel.WaitForMultipleObjects.restype = wintypes.DWORD
        for name in ('SetEvent', 'CloseHandle', 'FindNextChangeNotification', 'FindCloseChangeNotification'):
            getattr(kernel, name).argtypes = [wintypes.HANDLE]
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        watch = kernel.FindFirstChangeNotificationW(str(directory), False, 0x11)
        if not watch or watch == ctypes.c_void_p(-1).value:
            return
        self.watch = watch
        self.event = kernel.CreateEventW(None, False, False, None)
        if not self.event:
            self.close()

    def put(self, value):
        with self.lock:
            self.queue.put(value)
            if self.event:
                self.kernel.SetEvent(self.event)

    def receive(self, timeout):
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            pass
        if self.watch:
            handles = (wintypes.HANDLE * 2)(self.event, self.watch)
            result = self.kernel.WaitForMultipleObjects(2, handles, False, max(1, int(timeout * 1000 + 1)))
            if result == 0:
                try:
                    return self.queue.get_nowait()
                except queue.Empty:
                    return {}
            if result == 1:
                if not self.kernel.FindNextChangeNotification(self.watch):
                    self.close()
                return {}
            if result == 0x102:
                return {}
            self.close()
        try:
            return self.queue.get(timeout=min(timeout, 8 if low_power() else 2))
        except queue.Empty:
            return {}

    def close(self):
        with self.lock:
            if self.watch:
                self.kernel.FindCloseChangeNotification(self.watch)
                self.watch = None
            if self.event:
                self.kernel.CloseHandle(self.event)
                self.event = None


def main():
    if os.name=='nt':
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(),os.O_BINARY); msvcrt.setmode(sys.stdout.fileno(),os.O_BINARY)
    inbox=BrowserInbox(DATA); stop=object()
    def read_loop():
        try:
            while True:
                item=read_message(sys.stdin.buffer)
                if item is None: break
                inbox.put(item)
        except (OSError,ValueError,UnicodeError): pass
        finally: inbox.put(stop)
    threading.Thread(target=read_loop,daemon=True).start()
    session=uuid.uuid4().hex; status=SESSIONS/(session+'.json'); last=None; label='Navegador'; heartbeat=0; browser_enabled=None; fault=None; browser_error=False
    try:
        while True:
            timeout=max(0, heartbeat + HEARTBEAT_SECONDS - time.monotonic()) if heartbeat else 0
            message=inbox.receive(timeout)
            if message is stop: break
            if message.get('type') == 'open-ciceron':
                send_message(sys.stdout.buffer, {'ok': open_ciceron()})
                continue
            if message.get('type')=='hello':
                candidate=message.get('browser','Navegador')
                if isinstance(candidate,str) and candidate in ('Chrome','Brave','Edge','Chromium','Navegador'): label=candidate
                last=None
            if message.get('type')=='status':
                reported=message.get('enabled')
                enabled=reported if type(reported) is bool else None
                error=message.get('error') is True
                if (enabled, error) != (browser_enabled, browser_error):
                    browser_enabled, browser_error = enabled, error
                    heartbeat=0
            try:
                policy=load_policy(); reply={'type':'policy','policy':policy}; fault=None
            except (OSError,ValueError,TypeError):
                fault='No se pudo leer la configuración de Cicerón.'; reply={'type':'error','message':fault}
            if reply!=last: send_message(sys.stdout.buffer,reply); last=reply
            if not heartbeat or time.monotonic()-heartbeat>=HEARTBEAT_SECONDS:
                try:
                    SESSIONS.mkdir(parents=True,exist_ok=True)
                    status.write_text(json.dumps({'browser':label,'time':time.time(),'enabled':browser_enabled,'error':fault or ('El navegador no pudo aplicar las reglas.' if browser_error else None)}),encoding='utf-8')
                except OSError: pass
                heartbeat=time.monotonic()
    except (OSError,BrokenPipeError): pass
    finally:
        inbox.close()
        try: status.unlink(missing_ok=True)
        except OSError: pass

if __name__=='__main__': main()
