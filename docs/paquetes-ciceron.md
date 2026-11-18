# Crear aplicaciones para Cicerón

Cicerón instala paquetes `.ciceron`, los muestra en **General** y puede añadirlos al dock. La aplicación instalada se ejecuta en su propio proceso y dibuja su propia interfaz, con Tk, Qt, .NET, WebView2 u otro entorno que su ejecutable lleve incluido.

## Instrucciones para una IA que crea una app

1. Elige un ID estable como `local.notas`. Conserva ese ID en toda actualización.
2. Compila un ejecutable para Windows. Incluye las DLL, los recursos y el runtime que necesite junto al ejecutable. Asegúrate de que el programa pueda arrancar desde su propia carpeta.
3. Crea una carpeta de distribución. Coloca `ciceron.json` en su raíz y añade el ejecutable, su icono y los recursos. Mantén el código fuente en su proyecto y consérvalo también en el paquete si el usuario lo pide.
4. Ejecuta el empaquetador de este repositorio y valida su salida. El empaquetador y Cicerón usan el mismo validador.
5. En **General → Importar aplicaciones**, selecciona el `.ciceron`. Desde el menú **···** de su tarjeta puedes configurar la app, abrir sus datos o desinstalarla. Ábrela desde la tarjeta o desde su icono.
6. Para publicar un cambio, aumenta `version`, valida el paquete y vuelve a importarlo. Comprueba que se mantiene la configuración. Importa el mismo archivo dos veces y desinstálalo para verificar el ciclo completo.

Desde la raíz de Cicerón, con su entorno virtual de desarrollo preparado

```powershell
& .venv/Scripts/python.exe scripts/paquete.py crear C:/ruta/distribucion .salida/mi-app.ciceron
& .venv/Scripts/python.exe scripts/paquete.py validar .salida/mi-app.ciceron
```

El validador imprime ID, versión y huella de contenido en JSON. Devuelve código de salida 1 si el paquete falla.

## Distribución

```text
distribucion/
  ciceron.json
  MiApp.exe
  icono.png
  recursos/
    ...
```

El formato es ZIP con extensión `.ciceron`. Usa rutas relativas con `/` y nombres compatibles con Windows. El límite es 1 GiB descomprimido, 12 000 entradas y 64 KiB para el manifiesto. El icono admite PNG o ICO de hasta 2 MiB. Las rutas dentro del manifiesto deben coincidir con los nombres del ZIP.

## Manifiesto de versión 1

```json
{
  "schema": 1,
  "id": "local.mi-app",
  "version": "1.0.0",
  "name": "Mi aplicación",
  "description": "Descripción breve para la biblioteca.",
  "entrypoint": "MiApp.exe",
  "args": ["--modo", "normal"],
  "icon": "icono.png",
  "dock": {"visible": true, "wheel": "passthrough"},
  "settings": [
    {"id": "tema", "label": "Tema", "type": "choice", "choices": ["Sistema", "Claro"], "default": "Sistema"},
    {"id": "letra", "label": "Tamaño de letra", "type": "integer", "min": 10, "max": 26, "default": 14},
    {"id": "encima", "label": "Mantener encima", "type": "boolean", "default": false},
    {"id": "titulo", "label": "Título de la ventana", "type": "text", "default": "Mi aplicación"}
  ]
}
```

| Campo | Contrato |
| --- | --- |
| `schema` | Entero obligatorio. Usa `1`. |
| `id` | Obligatorio. Hasta 80 caracteres. Usa letras ASCII minúsculas, dígitos y guiones en al menos dos segmentos separados por puntos. Empieza por letra. |
| `version` | Obligatoria. Tres enteros sin ceros a la izquierda, de hasta seis dígitos cada uno. Cicerón compara los números. |
| `name` | Obligatorio. Hasta 80 caracteres visibles. |
| `description` | Opcional. Hasta 240 caracteres. |
| `tags` | Opcional. Hasta 12 etiquetas de 32 caracteres para buscar en General. El usuario puede editarlas en Cicerón. |
| `entrypoint` | Obligatorio. Ruta del `.exe` dentro del paquete. |
| `args` | Opcional. Hasta 32 argumentos literales de hasta 512 caracteres. Se pasan como lista al ejecutable. |
| `icon` | Opcional. Ruta de un PNG o ICO. Si se omite, Cicerón usa el icono del ejecutable. |
| `dock.visible` | Opcional. Por defecto `true`. Usa `false` para una app visible solo en la biblioteca. |
| `dock.wheel` | Opcional. `passthrough` deja que la rueda sobre el icono llegue a la aplicación de fondo. `consume` evita ese reenvío solo encima de ese icono. |
| `settings` | Opcional. Hasta 24 ajustes. Cada uno declara `id`, `label`, `type` y `default`. Los IDs usan minúsculas ASCII, números y guiones bajos, con letra inicial y hasta 40 caracteres. |

Los tipos de ajuste son `boolean`, `text` de hasta 512 caracteres, `integer` con `min` y `max` entre −1 000 000 y 1 000 000, y `choice` con entre 1 y 24 opciones de texto distintas. Cicerón valida los valores al empaquetar y al guardarlos. Rechaza campos desconocidos del manifiesto.

## Contrato al ejecutar

Cicerón lanza el programa con su carpeta de distribución como directorio de trabajo. El programa recibe estas variables de entorno

| Variable | Contenido |
| --- | --- |
| `CICERON_APP_ID` | ID del manifiesto. |
| `CICERON_APP_DATA` | Carpeta persistente para notas, preferencias o archivos de trabajo de la app. |
| `CICERON_APP_SETTINGS` | Ruta al `settings.json` UTF-8 que escribe Cicerón. Contiene los valores elegidos y los valores por defecto que falten. |

Lee los ajustes al iniciar. Si quieres aplicar cambios mientras la app ya está abierta, vuelve a leer ese archivo desde tu propio código. Usa `CICERON_APP_DATA` para archivos modificables. Cada versión del paquete tiene su propia carpeta de código y recursos.

Para una aplicación Python puedes distribuir un ejecutable con PyInstaller. El ejemplo usa el modo `onefile`. También puedes empaquetar la salida de `onedir` completa. [Opciones de distribución de PyInstaller](https://www.pyinstaller.org/en/stable/usage.html)

El manifiesto controla la rueda sobre el icono de Cicerón. Tu ejecutable controla el ratón en su propia ventana. Por ejemplo, puedes declarar un ajuste booleano para «Mantener encima» y aplicarlo al crear la ventana. Puedes hacer lo mismo con el estilo de captura, atajos o modos de puntero. Los permisos de Windows para micrófono, captura y automatización se gestionan al ejecutar la app.

## Instalar, actualizar y desinstalar

- **Instalar.** Cicerón valida el ZIP y sus rutas, extrae en una carpeta temporal y activa la versión solo cuando la extracción está completa. Abrir la app es una acción separada. El ejecutable usa los permisos de tu cuenta de Windows.
- **Reimportar.** El mismo ID, versión y contenido deja una sola entrada. Cambiar el contenido con el mismo número produce un error. Una versión inferior a la instalada también produce un error.
- **Actualizar.** Vuelve a importar un paquete con el mismo ID y una versión superior. El dock y la biblioteca pasan a apuntar a la versión nueva y se conserva la carpeta de datos. Cierra la versión anterior antes de actualizar si la tienes abierta.
- **Desinstalar.** En el menú de la tarjeta, elige **Desinstalar paquete**. Cicerón retira la entrada y el icono y limpia el código gestionado. Si hay archivos en uso, volverá a intentar retirarlos al arrancar. Conserva los datos de la app para una futura reinstalación. Usa **Abrir datos** antes de desinstalar si quieres localizarlos.
- **Rutas.** Las versiones, el registro de paquetes y los datos persistentes están bajo `Aplicacion\datos\`: paquetes en `paquetes\` y datos por aplicación en `datos-apps\<id>`. Los accesos a ejecutables dentro de `Aplicacion\` se guardan relativamente; los accesos a programas externos conservan su ubicación externa. Las apps deben usar `CICERON_APP_DATA` para escribir sus datos; no deben guardar archivos modificables junto al ejecutable.
- **Mover el centro.** Puedes mover la carpeta del repositorio completa. Las rutas internas se calculan desde el ejecutable y el directorio de cada paquete. Después ejecuta `Instalar.bat` en la nueva ubicación para actualizar los accesos y registros de Windows y del puente del navegador.
- **Retirar el centro.** `Desinstalar.bat` retira Cicerón y conserva `Aplicacion\datos\` y la extensión para que puedas recuperarlas al reinstalar el centro.

## Ejemplo reproducible

[Notas de ejemplo](../paquetes/ejemplo/) incluye código de interfaz, icono, manifiesto y un compilador para Windows. Guarda una nota en la carpeta de datos y lee los ajustes al abrir.

```powershell
& .venv/Scripts/python.exe paquetes/ejemplo/crear.py
& .venv/Scripts/python.exe scripts/paquete.py validar .salida/notas-ejemplo.ciceron
```

Importa el resultado. En **··· → Configurar**, cambia el tema o el tamaño de letra y abre la app. Guarda una nota, vuelve a importar el paquete y comprueba que solo figura una entrada. Desinstala e instala de nuevo. La nota y las preferencias deben seguir ahí.
