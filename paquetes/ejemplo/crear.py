"""Compile the sample app and write a valid .ciceron package."""
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from app_packages import create_package


def main():
    output = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / '.salida/notas-ejemplo.ciceron'
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent, prefix='notas-') as temporary:
        work = Path(temporary)
        payload = work / 'contenido'
        subprocess.run(
            [sys.executable, '-m', 'PyInstaller', '--log-level', 'WARN', '--noconfirm',
             '--windowed', '--onefile', '--name', 'Notas', '--distpath', str(payload),
             '--workpath', str(work / 'build'), '--specpath', str(work), str(HERE / 'notas.pyw')],
            check=True,
        )
        for filename in ('ciceron.json', 'icono.png'):
            shutil.copyfile(HERE / filename, payload / filename)
        create_package(payload, output)
    print(output)


if __name__ == '__main__':
    main()
