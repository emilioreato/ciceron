"""Package the sample's Python entry point without compiling it."""
from pathlib import Path
import shutil
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
        payload = Path(temporary)
        for filename in ('ciceron.json', 'icono.png', 'notas.pyw'):
            shutil.copyfile(HERE / filename, payload / filename)
        create_package(payload, output)
    print(output)


if __name__ == '__main__':
    main()
