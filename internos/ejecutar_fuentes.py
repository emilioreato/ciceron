"""Start the daily center from its linked repository or its local fallback."""
from hashlib import sha256
import os
from pathlib import Path
import runpy
import subprocess
import sys
import traceback


def start(entry, arguments):
    sys.argv[:] = [str(entry), *arguments]
    sys.path.insert(0, str(entry.parent))
    runpy.run_path(str(entry), run_name='__main__')


def source_digest(source):
    digest = sha256()
    for path in sorted(source.glob('*')):
        if path.suffix in ('.py', '.pyw'):
            digest.update(path.name.encode('utf-8') + b'\0' + sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def main():
    runtime = Path(__file__).resolve().parent
    root = runtime.parent
    launcher = root / 'Ciceron.exe'
    snapshot = runtime / 'src' / 'ciceron.pyw'
    linked = (root.parent / 'src').resolve()
    live = ((runtime / 'fuentes-vivas.txt').is_file() and
            (linked / 'ciceron.pyw').is_file() and (root.parent / 'requirements-runtime.txt').is_file())
    fallback = '--ciceron-respaldo' in sys.argv
    arguments = [arg for arg in sys.argv[1:] if arg not in ('--ciceron-respaldo', '--ciceron-recarga')]
    entry = linked / 'ciceron.pyw' if live and not fallback else snapshot
    os.environ['CICERON_SOURCE_ROOT'] = str(root)
    os.environ['CICERON_LIVE_SOURCE'] = str(linked) if live else ''
    sys.pycache_prefix = str(runtime / 'sin-cache')
    try:
        os.environ['CICERON_LIVE_DIGEST'] = source_digest(linked) if live else ''
        start(entry, arguments)
    except SystemExit as result:
        if result.code not in (75, 76) or not live:
            raise
        mode = '--abrir' if result.code == 76 else '--inicio-silencioso'
        subprocess.Popen([str(launcher), '--ciceron-recarga', mode], cwd=root)
    except Exception:
        if entry == snapshot:
            raise
        try:
            (root / 'datos').mkdir(exist_ok=True)
            (root / 'datos' / 'recarga-error.log').write_text(traceback.format_exc(), encoding='utf-8')
        finally:
            subprocess.Popen([str(launcher), '--ciceron-respaldo', *arguments], cwd=root)


if __name__ == '__main__':
    main()
