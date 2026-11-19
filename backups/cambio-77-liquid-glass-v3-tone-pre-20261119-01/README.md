# Cambio 77 - estado previo al tinte de Liquid Glass V3

Copias exactas de los archivos antes de editar, verificadas por SHA-256.
Incluyen cualquier cambio local que ya tuvieran.

Para revertir solo Cambio 77 desde la raiz del repositorio:

    Copy-Item -LiteralPath 'backups/cambio-77-liquid-glass-v3-tone-pre-20261119-01/gpu_lens.py' -Destination 'src/gpu_lens.py' -Force
    Copy-Item -LiteralPath 'backups/cambio-77-liquid-glass-v3-tone-pre-20261119-01/window_glass.py' -Destination 'src/window_glass.py' -Force
    Copy-Item -LiteralPath 'backups/cambio-77-liquid-glass-v3-tone-pre-20261119-01/contraste_vidrio.py' -Destination 'tests/contraste_vidrio.py' -Force

## Hashes previos
- src\gpu_lens.py SHA-256 160B45C116CBBEF4A7925FC21073A6426255724C20E46FBCFE3197B9CFB09499
- src\window_glass.py SHA-256 C179BBCF34CD8F9BF36520A3757D098FDCAE7575E7C314B9420820CA903D5711
- tests\contraste_vidrio.py SHA-256 1935A997679D8F38B12B655DA61F6F90DE4837B17B7948D901DBB731A3837475

