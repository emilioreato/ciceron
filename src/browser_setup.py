"""Preparación explícita del puente nativo para navegadores Chromium en Windows."""
import json
import re
import os
from pathlib import Path
import winreg
from app_paths import application_root

HOST='com.ciceron.browser'
ORIGIN='chrome-extension://cmbcmfhajdjlcepmkhjnfooadbccljpk/'
KEYS={'Chrome':r'Software\Google\Chrome\NativeMessagingHosts'+'\\'+HOST,
      'Brave':r'Software\Google\Chrome\NativeMessagingHosts'+'\\'+HOST,
      'Edge':r'Software\Microsoft\Edge\NativeMessagingHosts'+'\\'+HOST}

def detected():
    roots=[Path(os.environ.get('PROGRAMFILES',r'C:\Program Files')),
           Path(os.environ.get('PROGRAMFILES(X86)',r'C:\Program Files (x86)')),
           Path(os.environ.get('LOCALAPPDATA',str(Path.home())))]
    suffixes={'Chrome':r'Google\Chrome\Application\chrome.exe',
              'Brave':r'BraveSoftware\Brave-Browser\Application\brave.exe',
              'Edge':r'Microsoft\Edge\Application\msedge.exe'}
    result={}
    for name,suffix in suffixes.items():
        for root in roots:
            path=root/suffix
            if path.is_file(): result[name]=path; break
    return result

def prepare(browser):
    if browser not in KEYS: raise ValueError('Navegador no compatible.')
    root=application_root()
    manifest=root/'ciceron-native-host.json'
    if not manifest.is_file(): raise ValueError('Falta el puente nativo. Ejecuta Instalar.bat desde el paquete completo de Cicerón.')
    try: data=json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError,ValueError) as e: raise ValueError('El manifiesto del puente no se puede leer.') from e
    if not isinstance(data,dict) or not isinstance(data.get('path'),str): raise ValueError('El manifiesto del puente tiene un formato inválido.')
    expected_host=Path(data['path'])
    if data.get('name')!=HOST or data.get('type')!='stdio' or data.get('allowed_origins')!=[ORIGIN] or expected_host.parent!=root or not re.fullmatch(r'CiceronHost-[0-9a-f]{16}\.exe',expected_host.name):
        raise ValueError('El manifiesto del puente no coincide con esta instalación; vuelve a instalar Cicerón.')
    if not expected_host.is_file(): raise ValueError('No se encuentra el ejecutable del puente. Vuelve a instalar Cicerón.')
    try:
        configured=Path((root/'extension-path.txt').read_text(encoding='utf-8').strip())
        extension=configured if configured.is_absolute() else root/configured
    except OSError: raise ValueError('No se encuentra la ruta de la extensión. Vuelve a instalar Cicerón.')
    if not (extension/'manifest.json').is_file(): raise ValueError('No se encuentra la carpeta de la extensión. Vuelve a instalar Cicerón.')
    keypath=KEYS[browser]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,keypath,0,winreg.KEY_QUERY_VALUE) as key:
            existing,_=winreg.QueryValueEx(key,None)
            if os.path.normcase(existing)!=os.path.normcase(str(manifest)):
                owned=False
                try:
                    old=json.loads(Path(existing).read_text(encoding='utf-8'))
                    old_host=Path(old.get('path',''))
                    owned=(old.get('name')==HOST and old.get('type')=='stdio' and
                           old.get('allowed_origins')==[ORIGIN] and
                           re.fullmatch(r'CiceronHost-[0-9a-f]{16}\.exe',old_host.name))
                except (OSError,ValueError,TypeError): pass
                if not owned: raise ValueError('Ya existe otro puente con el mismo nombre; no se ha modificado.')
    except FileNotFoundError: pass
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,keypath,0,winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key,None,0,winreg.REG_SZ,str(manifest))
    return 'El registro del puente se guardó solo para este usuario.'
