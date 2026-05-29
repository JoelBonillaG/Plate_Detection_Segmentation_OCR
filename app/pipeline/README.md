# Pipeline de reconocimiento de placas

Cadena por imagen: **foto → placa → caracteres → texto**. Cada etapa es una
carpeta-paquete con su API; `pipeline.py` las orquesta en modo batch.

```
cámara/imread (BGR)
   │
   ▼  [ETAPA 1] deteccion_placas/   ── YOLOv11 (RED 1) + enderezado clásico
   │   detecta placa → recorta bbox → endereza a 300×100
   │   sale: placa horizontal (BGR)
   ▼  [ETAPA intermedia] filtros/   ── limpieza + agrandado (clásico)
   │   AQUÍ se convierte a GRIS. Denoise + agrandar + acentuar + normalizar
   │   sale: placa gris ~840×280, limpia y normalizada
   ▼  [ETAPA 2] segmentacion/       ── U-Net (RED 2)
   │   máscara de caracteres → cajas → crops por carácter
   │   sale: crops gris por carácter
   ▼  [ETAPA 3] ocr/                ── CNN clasificador (RED 3)  ⚠ NO CONECTADO
       clasifica cada crop → texto de la placa
       sale: ocr/salidas/<nombre>.txt
```

---

## Las 3 redes

| Red | Etapa | Pregunta | Modelo |
|-----|-------|----------|--------|
| **YOLOv11** | detección | ¿**dónde** está la placa? | `modelos/placas_scratch/weights/best.pt` |
| **U-Net** | segmentación | ¿**dónde** está cada carácter? | `segmentacion/Models/best_char_segmentation_unet.keras` |
| **CNN** | OCR | ¿**qué** carácter es? | `ocr/Respaldo Modelo/best_cnn_ocr_uk.keras` ⚠ |

La segmentación U-Net da la **máscara**; las cajas se sacan con post-proceso
clásico (`mask_to_boxes`: umbral + morfología + contornos + corte por proyección).

---

## Colores (IMPORTANTE)

- **OpenCV (`cv2.imread`, cámara) SIEMPRE da BGR**, nunca RGB.
- Todo el pipeline viaja en **BGR** hasta el OCR.
- **La conversión a GRIS ocurre UNA sola vez: en `filtros/`.** De ahí en adelante
  todo es gris (segmentación y OCR lo esperan gris).

| Punto | Color |
|-------|-------|
| cámara / `imread` | **BGR** |
| YOLO (detección) | entra BGR; internamente RGB; **entrenó en COLOR** |
| recorte + enderezado | **BGR** |
| filtros | **convierte a GRIS** (punto único) |
| U-Net (segmentación) | **GRIS** (entrenó/espera gris 1 canal) |
| CNN (OCR) | **GRIS** 1 canal (entrenó en gris) |

---

## Tamaños

| Cosa | Tamaño | Nota |
|------|--------|------|
| Frame de entrada | variable | las pruebas son 416×416 (dataset Roboflow) → placa diminuta → borrosa inevitablemente. Cámara HD = recorte nítido. |
| bbox YOLO | en coords del **frame original** | YOLO infiere a 416 pero devuelve la caja en resolución original; el recorte sale del frame original. |
| Enderezada | **300×100 fijo** (3:1) | no cambiar: el resto del pipeline asume estas dimensiones. |
| Filtrada | **alto 280**, ancho proporcional (≈840×280) | conserva el 3:1 de la enderezada. |
| Input U-Net | **256×96** (W×H) | el U-Net **redimensiona solo** por dentro; NO hace falta darle ese tamaño. Las cajas vuelven a la escala de la imagen que le pasas → conviene darle la filtrada **grande** para crops nítidos. |
| Crops de carácter | variable | recorte de cada caja sobre la imagen filtrada. |
| Input CNN OCR | **48×48×1** | gris; `prepare_crop` re-encuadra cada carácter. |

**El borroso NO viene de redimensionar** — viene de que la placa de origen tiene
pocos píxeles reales. Redimensionar nunca agrega detalle. El arreglo de raíz es
**resolución de origen mayor** (frames HD / `imgsz` mayor), no reordenar filtros.

---

## La etapa de filtros (qué hace y por qué)

Entrada: enderezada 300×100 (BGR). Todo es **automático y por-imagen** (no se
elige filtro ni fuerza a mano):

1. **BGR → gris**.
2. **Denoise adaptativo** (Non-Local Means): estima el ruido real (Immerkaer) y
   dosifica → no borra trazos en placas limpias, limpia fuerte las ruidosas.
3. **Agrandar** (Lanczos) a `alto_objetivo` (280) → caracteres con más píxeles
   para MSER/U-Net y crops más nítidos.
4. **Acentuar** (unsharp): la fuerza sale del desenfoque medido **sobre la imagen
   ya limpia** (así el ruido no engaña la métrica).
5. **Normalizar iluminación** (división por fondo, closing kernel 51): fondo
   blanco parejo + carácter negro sólido, aunque el recorte traiga carrocería
   alrededor. Esto ayuda a Otsu/U-Net, que asumen oscuro-sobre-claro.

Por qué ahí: las dos redes downstream (U-Net y CNN) y los umbrales clásicos
asumen **carácter oscuro / fondo claro** → el filtro entrega justo eso.

---

## Cómo correr

```bash
# pipeline completo (batch): lee camara/capturas/, deja crops en segmentadas/
python pipeline/pipeline.py

# segmentación sola (sobre un archivo)
python pipeline/segmentacion/predict_char_segmentation.py --image <placa.png>

# OCR solo (sobre un archivo) — clasifica con su propia segmentación Otsu
python pipeline/ocr/test_plate.py --image <placa.png>
```

---

## Salidas (auditoría por etapa)

| Carpeta | Contenido |
|---------|-----------|
| `deteccion_placas/detecciones/<n>.jpg` | frame con el bbox dibujado |
| `deteccion_placas/enderezadas/<n>.jpg` | placa horizontal 300×100 (BGR) |
| `filtros/filtradas/<n>.jpg` | placa gris limpia, agrandada, normalizada |
| `segmentacion/segmentadas/<n>/NN.png` | crops gris por carácter |
| `ocr/salidas/<n>.txt` | texto de la placa ⚠ pendiente |

---

## Configuración

- **Global:** `app/config.json` → `modelo` (ruta YOLO), `conf_min`, `imgsz`.
- **Detección/enderezado:** `deteccion_placas/config.json` → `margen`,
  `ancho_placa` (300), `alto_placa` (100).
- **Filtros:** `filtros/config.json` → `alto_objetivo`, `amount_min/max`,
  `nitido_ok`, `ruido_ref`, `norm_kernel`, toggles `denoise/acentuar/normalizar`.
- **Segmentación:** defaults en `segmentacion/__init__.py` (`_CFG_DEF`):
  `threshold` 0.50, `min_area_ratio` 0.002, `padding` 0.08, `char_aspect` 0.60.

---

## ⚠ Pendiente: conectar el OCR

La etapa 3 (`ocr/__init__.py`) está **escrita y lista** (`cargar_modelo`,
`clasificar`, `guardar_resultado`), pero **NO conectada** en `pipeline.py`
(comentada). Motivo del bloqueo:

> El `.keras` del clasificador es **formato Keras 3** (archivo ZIP, empieza con
> `PK`). El venv tiene **TF 2.10 / Keras 2.10**, que solo lee **HDF5**
> (`\x89HDF`). Por eso no carga. El U-Net sí carga porque es HDF5.

Para conectarlo, una de dos:
1. **Re-exportar el modelo OCR como `.h5`** (HDF5) compatible con Keras 2.10.
2. **Actualizar TF/Keras** del venv (riesgo: romper el U-Net HDF5 y
   YOLO/ultralytics).

Una vez resuelto el modelo, descomentar el bloque ETAPA 3 en `pipeline.py`:
```python
texto = etapa3.clasificar(crops, modelo_ocr, classes_ocr)
etapa3.guardar_resultado(nombre, texto)
```
y cargar el modelo en `main()` con `etapa3.cargar_modelo()`.
