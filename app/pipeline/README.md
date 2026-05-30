# Pipeline de reconocimiento de placas

Cadena por imagen: **foto → placa → caracteres → texto**. Cada etapa es una
carpeta-paquete con su API; `cadena.py` encadena las etapas sobre un frame y
`batch.py` las orquesta en modo batch (recorre la carpeta de capturas).

```
cámara/imread (BGR)
   │
   ▼  [ETAPA 0] deteccion_carros/   ── YOLOv11 (RED 0)  ·  CONECTADA
   │   detecta el carro más confiable → recorta el carro (con margen)
   │   SIN carro ⇒ no se busca placa (descarta falsos positivos no-vehículo)
   │   sale: recorte del carro (BGR, en memoria) → entra a ETAPA 1
   │
   ▼  [ETAPA 1] deteccion_placas/   ── YOLOv11 (RED 1) + enderezado clásico
   │   detecta placa DENTRO del recorte del carro → recorta bbox → endereza a 300×100
   │   sale: placa horizontal (BGR)
   ▼  [ETAPA intermedia] filtros/   ── limpieza + agrandado (clásico)
   │   AQUÍ se convierte a GRIS. Denoise + agrandar + acentuar + normalizar
   │   sale: placa gris ~840×280, limpia y normalizada
   ▼  [ETAPA 2] segmentacion/       ── U-Net (RED 2)
   │   máscara de caracteres → cajas → crops por carácter
   │   sale: crops gris por carácter
   ▼  [ETAPA 3] ocr/                ── CNN clasificador (RED 3)
       clasifica cada crop → texto de la placa
       sale: ocr/salidas/<nombre>.txt
```

> **ETAPA 0 (carros)** está **conectada**: detecta el carro, lo **recorta** y ese
> recorte (en memoria) es lo que recibe la red de placas. Si no hay carro, el frame
> se descarta sin buscar placa → así mueren los falsos positivos que no están dentro
> de un vehículo (un cuadro, un cartel). Si el modelo de carros **no** está entrenado,
> hace *fallback* a placa sobre el **frame completo** (guard `FileNotFoundError`).
>
> ⚠ **Efecto secundario:** como placas ahora trabaja sobre el **recorte** del carro
> (otra escala/encuadre que el frame completo), el enderezado y la segmentación
> downstream cambian → el texto OCR puede variar respecto al flujo sobre frame
> completo. Es comportamiento esperado, no un bug del cableado.

---

## Las redes

| Red | Etapa | Pregunta | Modelo |
|-----|-------|----------|--------|
| **YOLOv11** | detección carro (audit) | ¿**dónde** está el carro? | `deteccion_carros/modelos/carros_scratch/weights/best.pt` |
| **YOLOv11** | detección placa | ¿**dónde** está la placa? | `deteccion_placas/modelos/placas_scratch-90000/weights/best.pt` |
| **U-Net** | segmentación | ¿**dónde** está cada carácter? | `segmentacion/Models/best_char_segmentation_unet.keras` |
| **CNN** | OCR | ¿**qué** carácter es? | `ocr/Modelos/best_cnn_ocr_uk.keras` (HDF5) |

Todos los detectores YOLO se entrenan **desde cero** (`yolo11n.yaml`, pesos
aleatorios, `pretrained=False`) — sin transfer learning ni pesos COCO.

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
| Input CNN OCR | **64×64×1** | gris; `prepare_crop` re-encuadra cada carácter. 36 clases (0-9, A-Z). |

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
# pipeline completo (batch): lee camara/capturas/, hace placa→filtros→seg→OCR
python pipeline/batch.py

# en vivo (cámara): captura al cruzar la zona y corre la misma cadena
python main.py

# entrenar el detector de carros DESDE CERO (genera carros_scratch/weights/best.pt)
python pipeline/deteccion_carros/redes/entrenamiento.py

# detección de carro sola (sobre un archivo)
python pipeline/deteccion_carros/redes/prediccion.py --imagen <foto.jpg>

# segmentación sola (sobre un archivo)
python pipeline/segmentacion/predict_char_segmentation.py --image <placa.png>

# OCR solo (sobre un archivo) — clasifica con su propia segmentación Otsu
python pipeline/ocr/test_plate.py --image <placa.png>
```

---

## Salidas (auditoría por etapa)

| Carpeta | Contenido |
|---------|-----------|
| `deteccion_carros/detecciones/<n>.jpg` | frame con la caja del carro (auditoría) |
| `deteccion_placas/detecciones/<n>.jpg` | **recorte del carro** con el bbox de la placa dibujado |
| `deteccion_placas/enderezadas/<n>.jpg` | placa horizontal 300×100 (BGR) |
| `filtros/filtradas/<n>.jpg` | placa gris limpia, agrandada, normalizada |
| `segmentacion/segmentadas/<n>/NN.png` | crops gris por carácter |
| `ocr/salidas/<n>.txt` | **texto de la placa** |

---

## Configuración

La config es **por etapa** (no hay `app/config.json` global). Cada etapa lee su
propio `config.json`; las rutas de modelo son **relativas a esa etapa**.

- **Detección carros:** `deteccion_carros/config.json` → `modelo`, `conf_min`,
  `imgsz` (640), `margen`, `detecciones`.
- **Detección placas/enderezado:** `deteccion_placas/config.json` → `modelo`,
  `conf_min`, `imgsz` (416), `margen`, `ancho_placa` (300), `alto_placa` (100).
- **Filtros:** `filtros/config.json` → `alto_objetivo`, `amount_min/max`,
  `nitido_ok`, `ruido_ref`, `norm_kernel`, toggles `denoise/acentuar/normalizar`.
- **Segmentación:** defaults en `segmentacion/__init__.py` (`_CFG_DEF`):
  `threshold` 0.50, `min_area_ratio` 0.002, `padding` 0.08, `char_aspect` 0.60.

---

## Formato del modelo OCR (.keras) — IMPORTANTE

El venv usa **TF 2.10 / Keras 2.10**, que solo lee **HDF5** (`\x89HDF`), no el
formato **Keras 3** (archivo ZIP, empieza con `PK`). Por eso:

- ✅ Usar `ocr/Modelos/best_cnn_ocr_uk.keras` → **HDF5**, carga bien.
- ❌ `ocr/Respaldo Modelo/*.keras` → formato **ZIP/Keras 3**, **NO** carga en este venv.

Si re-exportas el modelo OCR, guárdalo como **HDF5** (`save_format="h5"` o
extensión `.h5`) para que Keras 2.10 lo lea. El U-Net ya es HDF5, por eso siempre
cargó. La ruta por defecto está fijada en `ocr/__init__.py` (`_MODELO_DEF`).
