# Guía para agentes — Cicerón

## Prioridad: conservar el trabajo existente

- Antes de editar, ejecuta `git status --short --branch` y revisa los cambios relevantes con `git diff`. Este repositorio puede tener trabajo concurrente.
- No uses `git reset --hard`, `git clean`, `git checkout` para reemplazar archivos, `git restore` sobre cambios ajenos ni limpiezas recursivas. No borres archivos ignorados, paquetes compilados, copias de seguridad ni datos del usuario para “limpiar” el proyecto.
- Si otro cambio toca el mismo archivo, léelo e intégralo de forma localizada. No sustituyas el archivo por una versión antigua ni descartes cambios sin autorización explícita.
- Al terminar, vuelve a comprobar `git status --short --branch` y `git diff --check`. Resume qué quedó modificado y qué pruebas corriste. No afirmes que está libre de errores: describe la evidencia y sus límites.

## Mapa del proyecto

- `src/ciceron.pyw`: punto de entrada, ciclo de vida, instancia única y composición de la aplicación.
- `src/center_ui.py`, `src/edge_dock.py`, `src/start_menu.py`: centro de control, barra lateral y accesos.
- `src/browser_ui.py`, `src/browser_setup.py`, `src/browser_bridge.py`: controles, instalación y puente nativo del navegador.
- `src/app_packages.py`, `src/package_ui.py`, `docs/paquetes-ciceron.md`, `paquetes/ejemplo/`: formato y gestión de aplicaciones extensibles. Sigue ese contrato; no inventes un formato paralelo.
- `src/gpu_lens.py`, `src/lens_capture.py`, `src/window_glass.py`, `src/windows_glass.py`: captura y renderizado de Liquid Glass, burbuja y paneles.
- `internos/`: instaladores y paquete de Windows. `navegador/extension/`: fuente de la extensión. `tests/` y `navegador/tests/`: comprobaciones.
- `DESARROLLO.md` contiene comandos y estructura de compilación; mantenlo alineado con los scripts reales.

## Comportamientos sensibles

- Conserva la instancia única, el mutex y la activación entre versiones de Cicerón. El evento de activación se atiende con `WaitForSingleObject` desde un `QTimer`; no reintroduzcas un `QWinEventNotifier` que haga fallar el inicio en el runtime actual.
- La rueda sobre la barra o sus paneles debe seguir desplazando la aplicación que estaba debajo. No consumas ni bloquees `WM_MOUSEWHEEL`. El cierre al hacer clic fuera y la reapertura desde el mismo icono también son parte del flujo.
- El render de vidrio debe seguir usando la ruta GPU/captura existente. No añadas capturas completas o filtros costosos en cada movimiento del ratón. Las imágenes de escritorio no deben guardarse. Excluye las ventanas propias al capturar y restaura la visibilidad para capturas de pantalla mediante el flujo temporal ya implementado.
- Si cambias `PanelMousePress`, `SetWindowDisplayAffinity`, la captura en segundo plano o la limpieza de timers/hooks, verifica tanto inicio como cierre; libera hooks, eventos y workers en todas las salidas.
- Mantén ejecutable, extensión, configuración y datos personales dentro de `Aplicacion\`, con datos mutables en `Aplicacion\datos\`. Resuelve las rutas internas desde la carpeta de la aplicación, nunca desde una ubicación fija ni el directorio de trabajo. `%APPDATA%` y `%LOCALAPPDATA%` se usan solo para migrar instalaciones antiguas o para integraciones que Windows exige ubicar allí, como accesos del menú Inicio. Los valores del Registro y el manifiesto nativo del navegador pueden contener rutas absolutas generadas por Windows; vuelve a generarlos con `Instalar.bat` tras mover la carpeta. Las actualizaciones deben ser idempotentes y conservar configuración, paquetes, accesos y valores ajenos del Registro. Modifica el valor de inicio o los registros de navegador solo si pertenecen a Cicerón.
- Los identificadores de instalaciones antiguas pueden permanecer solo en migraciones y pruebas de compatibilidad; no reintroduzcas nombres ni rutas heredadas en la interfaz, instalaciones nuevas o documentación para usuarios.
- Conserva las dependencias fijadas en `requirements.txt`, la versión 1 clásica y la versión 2 Liquid Glass, además de la compatibilidad de los paquetes de aplicaciones.

## Verificación

- Suite habitual: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\Probar.ps1`.
- Suite ampliada en Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\Probar.ps1 -Graficos -Instalacion`. `-Graficos` requiere una sesión Windows con OpenGL. `-Instalacion` usa carpetas y claves HKCU temporales; comprueba que `tests\.instalacion-temporal` y `tests\.navegador-temporal` no existan antes de iniciarla. No sustituyas sus pruebas aisladas por cambios en el Registro real.
- Para cambios en la lente o el vidrio, ejecuta también `tests\lente.py` y `tests\contraste_vidrio.py`; comprueba refracción, movimiento, limpieza y contraste, no solo que el shader compile.
- Para cambios de inicio, navegación o carga diferida, usa `tests\centro.py`, `tests\inicio.py` e `tests\inicio_cuenta.py` según corresponda. Para formatos y ciclo de vida de aplicaciones, usa `tests\paquetes.py`.
- Prueba primero el alcance afectado y luego la suite completa. Una prueba simulada no demuestra por sí sola la interacción real con el navegador, el escritorio ni el retardo del ratón.
- En la revisión del 17-11-2026 quedaron sin confirmar en uso real el retardo del ratón y el desplazamiento con la rueda sobre un navegador normal mientras el puntero está en Cicerón. Si se informa que esos casos están resueltos, aporta una comprobación en escritorio real; las pruebas automatizadas no bastan.

## Compilación e instalación

- La compilación y el reemplazo del paquete distribuible son manuales: hazlos solo cuando el usuario lo pida explícitamente y confirme que terminó el trabajo concurrente. No compiles automáticamente al cerrar la tarea de cada agente o modelo; varias sesiones pueden compartir los artefactos de `internos\`, `.compilacion\` y `.salida\`.
- `scripts\Crear EXE.bat` genera el programa distribuible como carpeta (`internos\Ciceron\Ciceron.exe` más `internos\Ciceron\_internal`) y el puente auxiliar `internos\CiceronHost.exe`. El instalador usa ese paquete por directorio; no uses un `internos\Ciceron.exe` antiguo como fuente de instalación.
- Antes de reemplazar el paquete, verifica que la compilación terminó correctamente y que no se está ejecutando el ejecutable que se va a sustituir. No elimines artefactos anteriores durante una compilación concurrente.
- Instalar o desinstalar en Windows es una acción separada: hazlo cuando el usuario lo haya pedido. Tras instalar, compara el SHA-256 de `internos\Ciceron\Ciceron.exe` con `Aplicacion\Ciceron.exe`, comprueba `Aplicacion\_internal\base_library.zip`, prueba el inicio solicitado y deja la aplicación cerrada si el usuario pidió cerrarla.
- No publiques, subas cambios ni crees commits como parte de una simple corrección local, salvo que el usuario lo pida.
