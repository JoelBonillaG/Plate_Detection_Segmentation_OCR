# Pipeline de reconocimiento de placas

Cadena por imagen: **foto -> placa -> caracteres -> texto**. Cada etapa es una
carpeta-paquete con su API. `cadena.py` encadena las etapas sobre un frame y
`batch.py` las orquesta en modo batch. En vivo, la entrada viene desde
`src.vision.main`, que llama la misma cadena al cruzar la zona.

```text
camara/imread (BGR)
   |
   v  [ETAPA 0] deteccion_carros/   -> YOLOv11
   |   detecta el carro mas confiable y recorta con margen
   |   si no hay carro, no se busca placa
   |
   v  [ETAPA 1] deteccion_placas/   -> YOLOv11 + enderezado
   |   detecta placa dentro del recorte del carro y la deja horizontal
   |
   v  [ETAPA intermedia] filtros/    -> preprocesado suave
   |   convierte a gris, suaviza y acentua un poco
   |
   v  [ETAPA 2] segmentacion/        -> U-Net
   |   convierte mascara a cajas y crops por caracter
   |
   v  [ETAPA 3] ocr/                 -> CNN clasificador
       clasifica cada crop y devuelve el texto de la placa
```

> ETAPA 0 esta conectada: detecta el carro, lo recorta y ese recorte es lo que
> recibe la red de placas. Si no hay carro, el frame se descarta. Si el modelo
> de carros no esta entrenado, la cadena hace fallback a placa sobre el frame
> completo.

---

## Las redes

| Red | Etapa | Pregunta | Modelo |
|-----|-------|----------|--------|
| YOLOv11 | deteccion carro | donde esta el carro? | `deteccion_carros/modelos/carros_scratch/weights/best.pt` |
| YOLOv11 | deteccion placa | donde esta la placa? | `deteccion_placas/modelos/placas_scratch-90000/weights/best.pt` |
| U-Net | segmentacion | donde esta cada caracter? | `segmentacion/Models/best_char_segmentation_unet.keras` |
| CNN | OCR | que caracter es? | `ocr/Modelos/best_cnn_ocr_uk.keras` |

---

## Colores

- OpenCV siempre entrega BGR.
- Todo el pipeline viaja en BGR hasta el OCR.
- La conversion a gris ocurre una sola vez en `filtros/`.

---

## Tamaños

| Cosa | Tamaño | Nota |
|------|--------|------|
| Frame de entrada | variable | captura real o archivo |
| Enderezada | 300x100 fijo | el resto del pipeline asume estas dimensiones |
| Filtrada | igual que la enderezada | conserva el 3:1 |
| Input U-Net | 256x96 | la red redimensiona internamente |
| Input CNN OCR | 64x64x1 | gris; `prepare_crop` re-encuadra cada caracter |

---

## Como correr

```bash
# pipeline completo (batch): recorre las capturas de la camara
python -m src.vision.pipeline.batch

# en vivo (camara + backend)
python -m src.vision.main
```

---

## Salidas

| Carpeta | Contenido |
|---------|-----------|
| `deteccion_carros/detecciones/<n>.jpg` | frame con la caja del carro |
| `deteccion_placas/detecciones/<n>.jpg` | recorte del carro con bbox de placa |
| `deteccion_placas/enderezadas/<n>.jpg` | placa horizontal |
| `filtros/filtradas/<n>.jpg` | placa gris suavizada |
| `segmentacion/segmentadas/<n>/NN.png` | crops por caracter |
| `ocr/salidas/<n>.txt` | texto de la placa |

---

## Como se mide la velocidad (carro, no placa)

El cruce ENTRA->SALE se mide con el **centro del carro**, no de la placa. El
carro es grande y estable, asi el tiempo de cruce es confiable; la placa solo
aporta el mejor crop para el OCR. Esa logica vive en la camara (ver
[camara](../camara/README.md)); la cadena solo procesa el frame que recibe.

## Nota de integracion

`cadena.py` tiene dos niveles:

1. `procesar_frame()` -> devuelve solo el texto. Uso simple y batch.
2. `procesar_frame_detallado()` -> devuelve un `ResultadoFrame` con placa, crops,
   bboxes de carro/placa y si se uso filtro. Lo consume `integration.py` para
   armar el evento, persistir en DB y emitir el WebSocket sin duplicar etapas.
