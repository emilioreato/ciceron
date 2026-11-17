"""Build or validate a Cicerón package using the same contract as the host."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from app_packages import create_package, unpack_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    build = sub.add_parser('crear')
    build.add_argument('carpeta', type=Path)
    build.add_argument('salida', type=Path)
    check = sub.add_parser('validar')
    check.add_argument('archivo', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'crear':
            spec, digest = create_package(args.carpeta, args.salida)
        else:
            spec, digest = unpack_package(args.archivo)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps({'id': spec['id'], 'version': spec['version'], 'sha256': digest}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
