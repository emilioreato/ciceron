# Desarrollo de Cicerón

La aplicación usa PySide6 y Qt desde `src/ciceron.pyw`. La distribución de Windows incluye su propio runtime en `Aplicacion\_internal\`. El ejecutable toma `Aplicacion\` como raíz y guarda los datos modificables en `Aplicacion\datos\`.

## Ejecutar desde el código

1. Instala Python 3.12 para Windows y verifica `py -3.12 --version`.
2. Ejecuta `scripts\Ejecutar en desarrollo.bat`. La primera vez crea `.venv` e instala las versiones fijadas en `requirements.txt` (requiere Internet).
3. Usa la ventana **Cicerón · desarrollo**. Guarda sus datos en `.desarrollo\datos\`, con una instancia y un evento de activación propios. Puedes mantener abierta la copia diaria a la vez. El perfil de desarrollo tiene deshabilitados el registro del puente, los accesos de Inicio y el inicio automático.

Para actualizar dependencias ejecuta `scripts\preparar.bat`. Si el entorno se movió o corresponde a otra versión de Python, el script aparta la carpeta existente y crea un entorno nuevo en la ruta actual.

## Crear e instalar el ejecutable

Las verificaciones normales se hacen desde el código. Si el usuario pide empaquetar una revisión concreta, prepara una copia aislada de esa revisión y ejecuta allí `scripts\Crear EXE.bat`. Los resultados son `internos\Ciceron\Ciceron.exe`, `internos\Ciceron\_internal\` y `internos\CiceronHost.exe`. La instalación diaria es una acción separada. Cuando se autorice, `Instalar.bat` instalará ese paquete en `Aplicacion\`, con la carpeta de datos existente.

## Mover la carpeta y reparar la integración

1. Cierra Cicerón y las miniapps. Mueve la carpeta `Aplicacion\` completa y ejecuta `Reparar integracion.bat` desde la nueva ubicación, o usa **Estado → Reparar integración** en la versión instalada.
2. La reparación vuelve a apuntar los accesos propios, la entrada de inicio automático si estaba activa y el puente del navegador. Los accesos a programas externos conservan su destino. También puedes ejecutar `Instalar.bat -Reparar -InstallDir "D:\Mis programas\Cicerón"` desde el repositorio. Si una copia anterior a esta función ya se movió y aún carece de referencia a su ubicación previa, indica la carpeta anterior con `-PreviousRoot "C:\Ruta anterior\Aplicacion"`.
3. Si Chromium conserva la ruta antigua, abre la página de extensiones de cada perfil, retira la ficha que apunta a esa carpeta y usa **Cargar descomprimida** con la nueva `00 EXTENSION\`. Cierra y vuelve a abrir el navegador si aún tiene una conexión nativa de la ubicación anterior.

## Recuperar una versión

Una actualización que cambia componentes conserva en `Aplicacion\version-anterior\` el ejecutable, su runtime y, si estaban instalados, la extensión y el puente compatibles. Una reparación idéntica conserva el respaldo anterior. Para recuperarlo, cierra Cicerón y ejecuta `Recuperar version anterior.bat` dentro de `Aplicacion\`. El instalador comprueba las huellas del respaldo antes de copiarlo. Abre Cicerón y revisa la integración del navegador.

`internos\formato-datos.txt` declara el formato que escribe la revisión. Increméntalo cuando una revisión vaya a escribir datos que la anterior no pueda leer. Si cambia, el instalador crea `Aplicacion\datos-antes-de-actualizar-…\` antes de reemplazar el programa. La recuperación de la versión mantiene los datos actuales. Una versión anterior al soporte Python puede requerir el índice de paquetes anterior para mostrar su biblioteca.

Si una versión antigua necesita el formato anterior, cierra el centro y las miniapps, duplica el respaldo y conserva aparte una copia completa de los datos actuales. Recupera únicamente los archivos que necesites desde la copia del respaldo o prueba primero con ese respaldo en un perfil separado. Si vas a sustituir el índice completo para recuperar la biblioteca antigua, deja fuera del perfil activo el directorio actual `datos\` como copia identificada y copia el respaldo completo a un nuevo `datos\`. Para volver a la revisión reciente, conserva igualmente los cambios hechos mientras usabas la antigua antes de retornar a los datos actuales.

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

Las rutas internas se forman respecto de `Aplicacion\`. El menú Inicio, Run y Native Messaging requieren rutas absolutas administradas por Windows. **Reparar integración** las recrea para la ubicación actual. El instalador y el arranque después de reiniciar deben comprobarse en el equipo de destino.

## Pruebas

Ejecuta `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\Probar.ps1` después de preparar el entorno. Usa Qt sin ventanas y Node.js para las pruebas de la extensión. Añade `-Graficos` desde una sesión interactiva de Windows con OpenGL para probar la lente y el contraste. Añade `-Instalacion` para probar los instaladores con claves del Registro temporales.

Ejecuta `powershell -NoProfile -ExecutionPolicy Bypass -File tests\instalacion.ps1`. Usa carpetas y una clave temporal aisladas del Registro, que elimina al terminar. Comprueba reinstalaciones, cancelación, actualización con un proceso de prueba, concurrencia, desinstalación y protección de entradas ajenas.

## Inicio de Windows

El instalador, la opción «Abrir al iniciar sesión» y el desinstalador comparten el valor `Ciceron` en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. La primera instalación lo crea apuntando al ejecutable instalado; una reinstalación reemplaza el ejecutable y conserva el inicio desactivado si el usuario lo había desactivado. No se sobrescriben ni eliminan valores que apunten a otro programa. Al actualizar, el instalador migra la entrada antigua propia. La opción de la aplicación solo cambia el inicio desde el ejecutable instalado y rechaza cambios concurrentes. El desinstalador elimina únicamente la entrada propia y conserva la configuración.

Para comprobar la casilla de inicio sin tocar el Registro real, ejecuta `.venv\Scripts\python.exe tests\inicio.py`.

Las pruebas de instalación también fuerzan un fallo al actualizar el acceso directo y un cambio simultáneo en el Registro. Verifican que se restaure el ejecutable anterior y no se sobrescriba el cambio ajeno.

`tests\desarrollo.py` arranca dos procesos de Cicerón desde el código con perfiles distintos y verifica a cuál llega la activación. `tests\portabilidad.ps1` prueba el traslado a una ruta con espacios, la reparación y la recuperación con ejecutables simulados y claves de prueba. `tests\datos.py` prueba dos miniapps Python reales y una exportación selectiva. Los datos y las claves de estas pruebas son temporales.

Para verificar el inicio y parada del contador, la fecha a medianoche, la hora opcional y el calendario, ejecuta `.venv\Scripts\python.exe tests\inicio_cuenta.py`. La prueba usa datos temporales.

## Integración del navegador

`navegador/extension` contiene la extensión MV3 y las reglas originales. `src/browser_bridge.py` implementa mensajería nativa por stdio, sin transmitir URL ni contenido de páginas; el ejecutable independiente se empaqueta como `internos/CiceronHost.exe`. `src/browser_ui.py` y `src/browser_setup.py` proporcionan controles y registro por usuario. El identificador de extensión está fijado mediante la clave pública del manifiesto y debe coincidir con el origen permitido en el instalador; publicar una extensión firmada requerirá gestionar una clave de firma y una migración de ID.

Pruebas: `node --test navegador\tests\*.test.cjs` y `.venv\Scripts\python.exe tests\browser_bridge.py`, `.venv\Scripts\python.exe tests\browser_ui.py` y `powershell -NoProfile -ExecutionPolicy Bypass -File tests\navegador_instalacion.ps1`. La carga manual de una extensión desempaquetada y su integración real deben verificarse en cada navegador y perfil.
# Material de las ventanas

Las tres versiones comparten las páginas, los diálogos, la navegación y las acciones. Para añadir un menú, construye sus controles Qt una sola vez. Usa `GlassDialog` para los diálogos de Cicerón y pasa `attached=True` cuando la barra los aloje. Los formularios declarados en paquetes usan el mismo diálogo y heredan la versión elegida. Una aplicación lanzada en otro proceso controla sus propias ventanas.

`center_ui.py` define las versiones y su estilo. En V3, `draw_clear_material` usa la textura de fondo ya capturada y las posiciones visibles de botones y campos para dibujar el desenfoque directamente en la GPU. Conserva transparentes los contenedores intermedios y usa nombres de rol para las excepciones de estilo.
