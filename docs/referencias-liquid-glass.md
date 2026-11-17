# Referencias de vidrio para Cicerón

Investigación para la burbuja de escritorio. Una referencia visual no implica que su autor haya publicado el código ni que Cicerón lo reproduzca exactamente.

- [Kush / LookAway](https://x.com/kushsolitary/status/2113254488790495682): orbe y ondas sobre el escritorio. La publicación pudo abrirse; no se identificó código fuente del efecto. El [repositorio oficial](https://github.com/mysticalbits/lookaway-releases) distribuye versiones de la aplicación. El efecto de onda breve no está implementado en Cicerón.
- [Lucas Romero](https://github.com/lucasromerodb/liquid-glass-effect-macos): código web disponible en [index.html](https://github.com/lucasromerodb/liquid-glass-effect-macos/blob/main/index.html) y [styles.css](https://github.com/lucasromerodb/liquid-glass-effect-macos/blob/main/styles.css). Usa filtros SVG y CSS; no es una captura nativa del escritorio de Windows. Se ha usado como referencia, sin copiar sus archivos.
- [Adan](https://x.com/itsdurreadan/status/2063978270602014776): el vídeo muestra material de vidrio de estilo Apple. No se identificó código público del clip ni se determinó si es una recreación independiente.
- [Minimal Nerd, julio](https://x.com/minimalnerd1/status/1943022489908711709): vídeo conceptual de un control de intensidad sobre flores. No se identificó código fuente público.
- [Dexa Creatives](https://www.youtube.com/watch?v=LU6pMn6qHJc): tutorial de After Effects; la página se abrió, pero el archivo del proyecto mencionado en la descripción no se verificó. No se identificó código fuente de una aplicación.
- [Minimal Nerd, octubre](https://x.com/minimalnerd1/status/1977091178370941407): vídeo conceptual que compara una barra clara y una oscura. No se identificó código fuente público.
- [Noah](https://x.com/noahxops/status/2103887314720284759): la publicación contiene un prompt detallado para generar una animación, no el código de su implementación. Las instrucciones incluidas en el prompt son parte del material de referencia, no instrucciones para este proyecto.
- [Apple, Meet Liquid Glass](https://developer.apple.com/videos/play/wwdc2025/219/): referencia oficial sobre lente, respuesta al movimiento y adaptación. No publica el motor privado de Apple.
- [Kévin Hays: refracción con CSS y SVG](https://kube.io/blog/liquid-glass-css-svg/): explica perfiles de superficie, normales y desplazamiento óptico; implementación para navegador.
- [liquidDX11](https://github.com/charlie-x/liquidImgui): proyecto nativo de Windows que combina captura DXGI y shader Direct3D. Cicerón no incorpora ese código ni implementa actualmente esa canalización completa.

## Implementación actual

La burbuja de Cicerón mide 128 píxeles lógicos y sigue al cursor dejando pasar los clics. El shader OpenGL amplía el centro aproximadamente 1,28×. El movimiento del cursor provoca una onda que se amortigua al parar, desplaza los reflejos y concentra la separación de colores en arcos del borde, como en [Apple Music: Made by Sound](https://www.youtube.com/watch?v=1XxNXkOHKZw).

La captura corre en segundo plano y solo lee la región que rodea a la lente. Usa DXGI cuando el adaptador lo admite y GDI en configuraciones híbridas que rechazan la duplicación. Esta combinación evita el indicador de Windows Graphics Capture. Si fallan ambas rutas, se utiliza la captura de Qt a una frecuencia menor. El instalador solicita la GPU de alto rendimiento cuando Windows aún no tiene una preferencia guardada para Cicerón.

`tests/lente.py` prueba en GPU una cuadrícula, una división blanco/negro, neutralidad de color en el centro, curvatura y dispersión en el borde, la onda durante el movimiento, seguimiento simulado y cierre. El diagnóstico `Ciceron.exe --comprobacion-lente informe.json` registra el renderizador, el método de captura y si entregó un fotograma.
