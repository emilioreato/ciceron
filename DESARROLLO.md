# Desarrollo de Cicerón

La aplicación actual está en `src/ciceron.pyw` y usa PySide6 / Qt. En una instalación, el programa, la extensión, la configuración y los datos viven juntos en `Aplicacion\`; los datos modificables están en `Aplicacion\datos\`. La app resuelve las rutas desde la carpeta de su propio ejecutable, de modo que puedes mover el directorio completo. Ejecuta `Instalar.bat` después de moverlo para renovar las rutas absolutas que Windows necesita en el Registro, los accesos y el puente nativo del navegador. El instalador migra los datos de instalaciones anteriores y conserva los datos locales al actualizar o desinstalar.

## Ejecutar desde el código

1. Instala Python 3.12 y asegúrate de que `py -3` funcione en Windows.
2. Ejecuta `scripts\Ejecutar en desarrollo.bat`. La primera vez crea `.venv` e instala las versiones fijadas en `requirements.txt` (requiere Internet).
3. Cierra la aplicación desde su icono en la bandeja antes de volver a abrirla. No ejecutes simultáneamente la versión instalada: ambas utilizan la misma instancia y configuración.

Para actualizar dependencias del entorno, ejecuta `scripts\preparar.bat`.

## Crear e instalar el ejecutable

Ejecuta `scripts\Crear EXE.bat`: compila el programa en `internos\Ciceron\Ciceron.exe` con sus dependencias en `internos\Ciceron\_internal`, y genera el puente auxiliar `internos\CiceronHost.exe`. Después ejecuta `Instalar.bat` desde la carpeta principal. Instala en `Aplicacion\` y conserva allí los datos. `Desinstalar.bat` retira los componentes administrados y conserva `Aplicacion\datos\` y la extensión cargada.

## Estructura

- `src/`: aplicación Qt. `ciceron.pyw` es el punto de entrada. `edge_dock.py` y `center_ui.py` componen la interfaz. `gpu_lens.py`, `lens_capture.py`, `window_glass.py` y `windows_glass.py` implementan los efectos y la integración con Windows. `app_packages.py` y `package_ui.py` administran las aplicaciones empaquetadas.
- `scripts/`: preparación del entorno, ejecución y compilación.
- `internos/`: ejecutable distribuible y scripts del instalador.
- `navegador/extension/`: fuente de la extensión. El instalador copia la fuente a `Aplicacion\00 EXTENSION\`, que se carga en el navegador. Chromium genera `_metadata/` al cargar la extensión. El archivo `Aplicacion\extension-path.txt` guarda una ruta relativa al directorio de la extensión.
- `Aplicacion\datos\`: preferencias, lista de aplicaciones, paquetes importados y datos persistentes de las apps. Se mantiene dentro de la instalación y no se borra al desinstalar.
- `tests/` y `navegador/tests/`: pruebas de escritorio, instalador y extensión.
- `paquetes/ejemplo/`: ejemplo del formato de aplicaciones de Cicerón.
- `docs/`: documentación técnica vigente.
- `archivo/`: material histórico local excluido de la publicación.
- `.venv/`, `.compilacion/`, `.salida/`: archivos locales de desarrollo generados al ejecutar los scripts; no se versionan.

Las rutas internas siempre se forman respecto de `Aplicacion\`; no las construyas desde el directorio actual ni fijes la unidad o la ruta del usuario. Las excepciones son integraciones administradas por Windows, como el menú Inicio, Run y el registro de Native Messaging, que requieren rutas absolutas. `Instalar.bat` las recrea para la ubicación actual. El instalador y el arranque después de reiniciar deben comprobarse en el equipo de destino. Los avisos dependen del título de la ventana activa, por lo que pueden producir falsos positivos o no detectar una página.

## Pruebas

Ejecuta `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\Probar.ps1` después de preparar el entorno. Usa Qt sin ventanas y Node.js para las pruebas de la extensión. Añade `-Graficos` desde una sesión interactiva de Windows con OpenGL para probar la lente y el contraste. Añade `-Instalacion` para probar los instaladores con claves del Registro temporales.

Ejecuta `powershell -NoProfile -ExecutionPolicy Bypass -File tests\instalacion.ps1`. Usa carpetas y una clave temporal aisladas del Registro, que elimina al terminar. Comprueba reinstalaciones, cancelación, actualización con un proceso de prueba, concurrencia, desinstalación y protección de entradas ajenas.

## Inicio de Windows

El instalador, la opción «Abrir al iniciar sesión» y el desinstalador comparten el valor `Ciceron` en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. La primera instalación lo crea apuntando al ejecutable instalado; una reinstalación reemplaza el ejecutable y conserva el inicio desactivado si el usuario lo había desactivado. No se sobrescriben ni eliminan valores que apunten a otro programa. Al actualizar, el instalador migra la entrada antigua propia. La opción de la aplicación solo cambia el inicio desde el ejecutable instalado y rechaza cambios concurrentes. El desinstalador elimina únicamente la entrada propia y conserva la configuración.

Para comprobar la casilla de inicio sin tocar el Registro real, ejecuta `.venv\Scripts\python.exe tests\inicio.py`.

Las pruebas de instalación también fuerzan un fallo al actualizar el acceso directo y un cambio simultáneo en el Registro. Verifican que se restaure el ejecutable anterior y no se sobrescriba el cambio ajeno.

Para verificar el inicio y parada del contador, la fecha a medianoche, la hora opcional y el calendario, ejecuta `.venv\Scripts\python.exe tests\inicio_cuenta.py`. La prueba usa datos temporales.

## Integración del navegador

`navegador/extension` contiene la extensión MV3 y las reglas originales. `src/browser_bridge.py` implementa mensajería nativa por stdio, sin transmitir URL ni contenido de páginas; el ejecutable independiente se empaqueta como `internos/CiceronHost.exe`. `src/browser_ui.py` y `src/browser_setup.py` proporcionan controles y registro por usuario. El identificador de extensión está fijado mediante la clave pública del manifiesto y debe coincidir con el origen permitido en el instalador; publicar una extensión firmada requerirá gestionar una clave de firma y una migración de ID.

Pruebas: `node --test navegador\tests\*.test.cjs` y `.venv\Scripts\python.exe tests\browser_bridge.py`, `.venv\Scripts\python.exe tests\browser_ui.py` y `powershell -NoProfile -ExecutionPolicy Bypass -File tests\navegador_instalacion.ps1`. La carga manual de una extensión desempaquetada y su integración real deben verificarse en cada navegador y perfil.
# Material de las ventanas

Las tres versiones comparten las páginas, los diálogos, la navegación y las acciones. Para añadir un menú, construye sus controles Qt una sola vez. Usa `GlassDialog` para los diálogos de Cicerón y pasa `attached=True` cuando la barra los aloje. Los formularios declarados en paquetes usan el mismo diálogo y heredan la versión elegida. Una aplicación lanzada en otro proceso controla sus propias ventanas.

`center_ui.py` define las versiones y su estilo. En V3, `draw_clear_material` usa la textura de fondo ya capturada y las posiciones visibles de botones y campos para dibujar el desenfoque directamente en la GPU. Conserva transparentes los contenedores intermedios y usa nombres de rol para las excepciones de estilo.
