# Desarrollo de Cicerón

La aplicación actual está en `src/ciceron.pyw` y usa PySide6 / Qt. La configuración y la lista de aplicaciones se guardan en `%APPDATA%\GanaLaBatalla`; el código no las contiene.

## Ejecutar desde el código

1. Instala Python 3.12 y asegúrate de que `py -3` funcione en Windows.
2. Ejecuta `scripts\Ejecutar en desarrollo.bat`. La primera vez crea `.venv` e instala las versiones fijadas en `requirements.txt` (requiere Internet).
3. Cierra la aplicación desde su icono en la bandeja antes de volver a abrirla. No ejecutes simultáneamente la versión instalada: ambas utilizan la misma instancia y configuración.

Para actualizar dependencias del entorno, ejecuta `scripts\preparar.bat`.

## Crear e instalar el ejecutable

Ejecuta `scripts\Crear EXE.bat`: compila el código actual y copia el resultado a `internos\GanaLaBatalla.exe` y `internos\CiceronHost.exe`. Después cierra la versión instalada y ejecuta `Instalar.bat` desde la carpeta principal. La instalación es por usuario y conserva los datos. `Desinstalar.bat` elimina la aplicación instalada y conserva la configuración.

## Estructura

- `src/`: aplicación Qt. `ciceron.pyw` es el punto de entrada. `edge_dock.py` y `center_ui.py` componen la interfaz. `gpu_lens.py`, `lens_capture.py`, `window_glass.py` y `windows_glass.py` implementan los efectos y la integración con Windows. `app_packages.py` y `package_ui.py` administran las aplicaciones empaquetadas.
- `scripts/`: preparación del entorno, ejecución y compilación.
- `internos/`: ejecutable distribuible y scripts del instalador.
- `navegador/extension/`: fuente de la extensión. El instalador copia la fuente a `00 EXTENSION/`, que se carga en el navegador. Chromium genera `_metadata/` al cargar la extensión.
- `tests/` y `navegador/tests/`: pruebas de escritorio, instalador y extensión.
- `paquetes/ejemplo/`: ejemplo del formato de aplicaciones de Cicerón.
- `docs/`: documentación técnica vigente.
- `archivo/`: material histórico local excluido de la publicación.
- `.venv/`, `.compilacion/`, `.salida/`: archivos locales de desarrollo generados al ejecutar los scripts; no se versionan.

El instalador y el arranque después de reiniciar deben comprobarse en el equipo de destino. Los avisos dependen del título de la ventana activa, por lo que pueden producir falsos positivos o no detectar una página.

## Pruebas

Ejecuta `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\Probar.ps1` después de preparar el entorno. Usa Qt sin ventanas y Node.js para las pruebas de la extensión. Añade `-Graficos` desde una sesión interactiva de Windows con OpenGL para probar la lente y el contraste. Añade `-Instalacion` para probar los instaladores con claves del Registro temporales.

Ejecuta `powershell -NoProfile -ExecutionPolicy Bypass -File tests\instalacion.ps1`. Usa carpetas y una clave temporal aisladas del Registro, que elimina al terminar. Comprueba reinstalaciones, cancelación, actualización con un proceso de prueba, concurrencia, desinstalación y protección de entradas ajenas.

## Inicio de Windows

El instalador, la opción «Abrir al iniciar sesión» y el desinstalador comparten el valor `GanaLaBatalla` en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. La primera instalación lo crea apuntando al ejecutable instalado; una reinstalación reemplaza el ejecutable y conserva el inicio desactivado si el usuario lo había desactivado. No se sobrescriben ni eliminan valores que apunten a otro programa. La opción de la aplicación solo cambia el inicio desde el ejecutable instalado y rechaza cambios concurrentes. El desinstalador elimina únicamente la entrada propia y conserva la configuración.

Para comprobar la casilla de inicio sin tocar el Registro real, ejecuta `.venv\Scripts\python.exe tests\inicio.py`.

Las pruebas de instalación también fuerzan un fallo al actualizar el acceso directo y un cambio simultáneo en el Registro. Verifican que se restaure el ejecutable anterior y no se sobrescriba el cambio ajeno.

Para verificar el inicio y parada del contador, la fecha a medianoche, la hora opcional y el calendario, ejecuta `.venv\Scripts\python.exe tests\inicio_cuenta.py`. La prueba usa datos temporales.

## Integración del navegador

`navegador/extension` contiene la extensión MV3 y las reglas originales. `src/browser_bridge.py` implementa mensajería nativa por stdio, sin transmitir URL ni contenido de páginas; el ejecutable independiente se empaqueta como `internos/CiceronHost.exe`. `src/browser_ui.py` y `src/browser_setup.py` proporcionan controles y registro por usuario. El identificador de extensión está fijado mediante la clave pública del manifiesto y debe coincidir con el origen permitido en el instalador; publicar una extensión firmada requerirá gestionar una clave de firma y una migración de ID.

Pruebas: `node --test navegador\tests\*.test.cjs` y `.venv\Scripts\python.exe tests\browser_bridge.py`, `.venv\Scripts\python.exe tests\browser_ui.py` y `powershell -NoProfile -ExecutionPolicy Bypass -File tests\navegador_instalacion.ps1`. La carga manual de una extensión desempaquetada y su integración real deben verificarse en cada navegador y perfil.
