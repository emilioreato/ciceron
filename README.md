# Cicerón

<img src="assets/ciceron.png" alt="Icono de Cicerón" width="96">

Cicerón es un centro de control para aplicaciones personales de Windows. Su barra lateral reúne accesos, aplicaciones empaquetadas, un temporizador, efectos de escritorio y los controles de Pausa Feed del navegador.

## Ejecutar desde el código

1. Instala Python 3.12 en Windows.
2. Ejecuta `scripts\Ejecutar en desarrollo.bat` para abrir un perfil de prueba que puede convivir con la copia instalada.

## Compilar e instalar

Empaqueta la revisión elegida en una copia aislada con `scripts\Crear EXE.bat`. Cuando quieras actualizar tu copia diaria, ejecuta `Instalar.bat` desde ese paquete. Abre la versión instalada con `Abrir Ciceron.bat` o busca **Cicerón** en Inicio. Para moverla o recuperar la versión anterior, usa los comandos de `Aplicacion\`.

- [Guía de uso](LEEME.txt)
- [Desarrollo y pruebas](DESARROLLO.md)
- [Crear un paquete para Cicerón](docs/paquetes-ciceron.md)
- [Integración del navegador](navegador/ESTADO.md)
