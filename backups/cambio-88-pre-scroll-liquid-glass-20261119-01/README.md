# Cambio 88 — punto previo al ajuste de sincronización de Liquid Glass

Esta carpeta conserva copias exactas de los dos archivos modificados para Cambio 88, tomadas antes de editarlos. Incluyen cualquier cambio local que ya tuvieran esos archivos.

Para revertir solo Cambio 88, desde la raíz del repositorio ejecuta:

```powershell
Copy-Item -LiteralPath 'backups/cambio-88-pre-scroll-liquid-glass-20261119-01/window_glass.py' -Destination 'src/window_glass.py' -Force
Copy-Item -LiteralPath 'backups/cambio-88-pre-scroll-liquid-glass-20261119-01/contraste_vidrio.py' -Destination 'tests/contraste_vidrio.py' -Force
```

SHA-256 previos:

- `src/window_glass.py`: `4FCFB94F0FB650BCA9BBE5645053BCB4345BE93345FF2FA8FB2D186F8C4F5E26`
- `tests/contraste_vidrio.py`: `2484623A7CA77BBE09914853838AAD65A475BCB82CF30D66A230707CA1131E1D`
