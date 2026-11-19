# Instalar Cicerón en Windows

La versión desde fuentes usa Python 3.12 para Windows con el lanzador `py`. Si falta y WinGet está disponible, el instalador te ofrece instalarlo.

| Quiero… | Qué ejecutar |
| --- | --- |
| Instalar o actualizar desde una revisión del repositorio | `Instalar.bat` desde esa revisión |
| Iniciar Cicerón en la flecha lateral | `Abrir Ciceron.bat` |
| Abrir el menú principal | Ícono de Cicerón en la bandeja o **Cicerón** en el menú Inicio |
| Mover Cicerón | Cierra el centro y las miniapps, mueve la carpeta completa y ejecuta `Abrir Ciceron.bat` desde la nueva ubicación |
| Recuperar la revisión anterior | `Aplicacion\Recuperar version anterior.bat` |
| Desinstalar | `Desinstalar.bat` o su copia dentro de `Aplicacion\` |

La primera instalación prepara las dependencias de `requirements-runtime.txt` en un entorno de Python dentro de `Aplicacion\.entornos\`. Puede necesitar Internet en ese momento. El pequeño lanzador de Windows se genera con .NET Framework la primera vez y se reutiliza entre revisiones. Ejecuta el centro con Python desde `Aplicacion\_internal\src\ciceron.pyw`. Al abrir Cicerón se usa el entorno ya preparado. Puedes seguir usando una distribución autocontenida con `Instalar.bat -Empaquetado` desde un paquete preparado.

## Actualizar, mover y recuperar

- Repite `Instalar.bat` desde una revisión lista para usar. Puedes actualizar una instalación movida con `Instalar.bat -InstallDir "D:\Mis programas\Ciceron"`. El instalador verifica la copia antes de activarla y pide cerrar el centro si está abierto. En automatización, usa `-CloseRunning` solo si ya tienes autorización para cerrarlo. `-NoLaunch` deja la nueva revisión instalada sin abrirla.
- **`Aplicacion\datos\` es la carpeta de datos.** Incluye preferencias, biblioteca, miniapps instaladas y sus datos. La actualización, la recuperación y el desinstalador la conservan. El desinstalador retira el lanzador activo y sus integraciones y conserva también los archivos que permiten recuperar la instalación.
- Abre Cicerón una vez desde la ruta nueva antes del próximo inicio de sesión. En modo Python, el lanzador detecta el traslado, repara la integración y abre el centro. Hasta entonces Windows usa la ruta anterior. La reparación conserva tu preferencia de inicio automático. Para la copia empaquetada, ejecuta `Reparar integracion.bat`. Si Chromium sigue apuntando a la ruta anterior, vuelve a cargar la extensión desempaquetada.
- Si falta parte del entorno o Python falla al arrancar, el lanzador ofrece repararlo. También puedes ejecutar `Reparar integracion.bat`.
- Si una actualización falla, conserva el mensaje y vuelve a abrir la versión anterior. Si la actualización terminó pero encuentras un problema después, usa **Recuperar versión anterior**. Si cambió el formato de datos, hay una copia previa en `Aplicacion\datos-antes-de-actualizar-…\`. La recuperación activa el código anterior con los datos actuales. Consulta los pasos para recuperar datos por separado antes de abrir una revisión que necesite el formato antiguo. [Recuperación y formatos](DESARROLLO.md#recuperar-una-versión)

## Desarrollo y miniapps

Para ejecutar con un perfil de prueba, vincular la instalación diaria a fuentes vivas, verificar cambios o preparar una distribución, consulta [Desarrollo de Cicerón](DESARROLLO.md). El formato `.ciceron`, su ejemplo y el traslado selectivo de datos están en [Aplicaciones y datos](docs/paquetes-ciceron.md). Importar datos no instala ni ejecuta código.
