# Instalar Cicerón en Windows

Necesitas Python 3.12 para Windows con el lanzador `py`. Comprueba la instalación con `py -3.12 --version` desde PowerShell.

| Quiero… | Qué ejecutar |
| --- | --- |
| Instalar o actualizar desde una revisión del repositorio | `Instalar.bat` desde esa revisión |
| Abrir Cicerón | `Abrir Ciceron.bat` o **Cicerón** en el menú Inicio |
| Mover la instalación | Cierra el centro y las miniapps, mueve toda la carpeta `Aplicacion\` y ejecuta allí `Reparar integracion.bat` |
| Recuperar la revisión anterior | `Aplicacion\Recuperar version anterior.bat` |
| Desinstalar | `Desinstalar.bat` o su copia dentro de `Aplicacion\` |

La primera instalación prepara las dependencias de `requirements-runtime.txt` en un entorno de Python dentro de `Aplicacion\.entornos\`. Puede necesitar Internet en ese momento. El pequeño lanzador de Windows se genera con .NET Framework la primera vez y se reutiliza entre revisiones. Ejecuta el centro con Python desde `Aplicacion\_internal\src\ciceron.pyw`. Al abrir Cicerón se usa el entorno ya preparado. Puedes seguir usando una distribución autocontenida con `Instalar.bat -Empaquetado` desde un paquete preparado.

## Actualizar, mover y recuperar

- Repite `Instalar.bat` desde una revisión lista para usar. Puedes actualizar una instalación movida con `Instalar.bat -InstallDir "D:\Mis programas\Ciceron"`. El instalador verifica la copia antes de activarla y pide cerrar el centro si está abierto. En automatización, usa `-CloseRunning` solo si ya tienes autorización para cerrarlo. `-NoLaunch` deja la nueva revisión instalada sin abrirla.
- **`Aplicacion\datos\` es la carpeta de datos.** Incluye preferencias, biblioteca, miniapps instaladas y sus datos. La actualización, la recuperación y el desinstalador la conservan. El desinstalador retira el lanzador activo y sus integraciones y conserva también los archivos que permiten recuperar la instalación.
- Windows conserva rutas absolutas en Inicio y en el registro del navegador. Ejecuta la reparación después de mover la carpeta y antes del próximo inicio de sesión. La reparación conserva tu preferencia de inicio automático. Si Chromium sigue apuntando a la ruta anterior, usa **Cargar descomprimida** con la nueva carpeta `00 EXTENSION\` desde la página de extensiones del navegador.
- Si una actualización falla, conserva el mensaje y vuelve a abrir la versión anterior. Si la actualización terminó pero encuentras un problema después, usa **Recuperar versión anterior**. Si cambió el formato de datos, hay una copia previa en `Aplicacion\datos-antes-de-actualizar-…\`. La recuperación activa el código anterior con los datos actuales. Consulta los pasos para recuperar datos por separado antes de abrir una revisión que necesite el formato antiguo. [Recuperación y formatos](DESARROLLO.md#recuperar-una-versión)

## Cambiar código y añadir miniapps

Para vincular la copia diaria al repo, ejecuta una vez `Instalar.bat -FuentesVivas` con `Aplicacion\` dentro del repositorio. Los cambios guardados en los módulos Python de `src\` reinician el centro automáticamente. Si hay un diálogo modal abierto, espera a que lo cierres. El perfil diario y sus datos permanecen en `Aplicacion\datos\`. Si una edición tiene un error de sintaxis, el proceso actual sigue abierto. Si falla el arranque desde el repo, se utiliza la copia estable instalada y se guarda el error en `datos\recarga-error.log`.

Los cambios al instalador, las dependencias y la extensión del navegador mantienen sus propios pasos de actualización. Si mueves solo `Aplicacion\`, se usa su copia local. **Recuperar versión anterior** activa una revisión fija. También puedes instalar una revisión fija con `Instalar.bat`.

Para probar con otro perfil, usa `scripts\Ejecutar en desarrollo.bat`. Lee los archivos actuales del repositorio y usa `.desarrollo\datos\`. Si ya está abierto, sal de **Cicerón · desarrollo** desde la bandeja y vuelve a lanzarlo.

Una miniapp puede entregarse como `.ciceron` con un `.exe` o un punto de entrada Python 3.12. Mantén su ID entre versiones y guarda los datos persistentes declarados dentro de `CICERON_APP_DATA`. En el centro, importa el paquete desde **General**. Para trasladar los datos de una o varias apps, usa **Datos → Exportar / Importar**. En el destino, instala primero las apps compatibles. Si ya hay datos, la importación omite esa app por defecto y ofrece respaldo previo si eliges reemplazarla. [Formato, ejemplo y comandos para crear un paquete](docs/paquetes-ciceron.md)

## Comprobación para agentes

Lee [AGENTS.md](AGENTS.md) antes de cambiar el repo. Prueba primero el recorrido afectado en el perfil de desarrollo. Para cambios al instalador o al ciclo de arranque, usa `tests\fuentes.ps1` con el entorno de desarrollo preparado. Prueba las migraciones con datos temporales. Actualiza la copia diaria solo cuando el usuario pida instalar esa revisión.
