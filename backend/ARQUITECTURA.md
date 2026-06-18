# Arquitectura actual — Monitoreo Vehicular

> Documento de **análisis de arquitectura** (estado real del sistema, no guía de
> instalación — para eso ver `README.md`). Foco: cómo fluye el video, a qué
> calidad, dónde se pierde/conserva calidad y qué está sin uso o frágil.

---

## 1. Vista general: 4 piezas, 2 procesos de Python

```
┌─────────────────────┐        WS cliente         ┌──────────────────────┐
│  PROCESO VISIÓN      │  ───── /ws/ingest ──────► │  PROCESO API         │
│  src.vision.main     │   binario: JPEG anotado   │  src.api.main        │
│                      │   texto:  eventos/status  │  (FastAPI + uvicorn) │
│  camara → cadena     │                           │                      │
│  (captura + OCR)     │                           │  reenvía a:          │
└─────────────────────┘                            │   /ws/video (binario)│
        │                                          │   /ws       (json)   │
        │ guarda imágenes                          │  sirve /static       │
        ▼                                          │  REST /api/events    │
   storage/eventos/<id>/*.jpg ◄──────────────────► │  persiste en Postgres│
                              (lectura /static)    └──────────────────────┘
                                                              ▲
                                                              │ WS + REST + /static
                                                       ┌──────────────────┐
                                                       │  FRONTEND (React) │
                                                       │  canvas + cards   │
                                                       └──────────────────┘
```

**Clave:** visión y API son **procesos separados, NO comparten memoria**. Se
hablan SOLO por un WebSocket (`bridge.py` → `/ws/ingest`). Por eso el video viaja
como JPEG por socket, no como objeto en memoria.

- `src.vision.main` puede correr **solo** (standalone, sin API ni DB).
- `src.api.main` (API) reenvía a los navegadores y persiste.
- **Postgres** en Docker (puerto host `5433`).
- **Frontend** React/Vite.

---

## 2. Proceso de visión (captura + pipeline)

### 2.1 Captura — `camara.py`
- Fuente: webcam USB (índice), archivo de video, o URL (RTSP/HTTP). **Hoy se usa
  solo USB / archivo de video.**
- **En vivo:** un hilo lee sin parar y guarda solo el ÚLTIMO frame (descarta
  atrasados → sin lag).
- **Video archivo:** *pacing* a su FPS real; **salta frames** (grab) si el
  pipeline se atrasa → reproduce a velocidad normal, no en cámara lenta.
- Por cada frame procesado se manejan **dos versiones**:
  - `frame_nativo` → resolución REAL de la fuente (ej. 1280×720). **Es lo que se
    guarda y va al OCR.**
  - `frame` → reescalado a `ventana_w × ventana_h` (1280×720) para detección en
    vivo, dibujo del overlay y stream.
- Rastreo del cruce entre dos líneas **ENTRA → SALE** (`lineas.py`). El "mejor"
  frame se elige por **CERCANÍA** (bbox más ancho = más cerca = más píxeles
  reales en la placa). Al cruzar SALE se dispara la captura → `cadena`.

### 2.2 Pipeline por captura — `cadena.procesar_frame_detallado`
Recibe el **frame nativo completo** y corre las etapas (flags actuales entre
paréntesis):

| # | Etapa | Modelo / método | Entrada | ¿Pierde calidad? |
|---|-------|-----------------|---------|------------------|
| 0 | Carros | YOLO `.pt` 640px | frame | **OFF** (no se usa) |
| 1a | Detección placa | YOLO `.pt` **416px** | frame completo | bbox (no toca píxeles) |
| 1b | Recortar | corte nativo + 8% margen | nativo | **No** (corte directo) |
| 1c | Enderezar | warp perspectiva **condicional** | nativo | **Solo si warpea** (ver §5) |
| – | Filtros | bilateral/unsharp | placa | **OFF** |
| 2 | Segmentación | U-Net máscara **256×96** | placa | **No al crop** (máscara localiza; crops salen de la placa nativa) |
| 3 | OCR | CNN **64×64** gris por carácter | crops | Resize obligatorio por carácter |

Cada etapa guarda una imagen de auditoría en `storage/eventos/<id>/`
(`frame.jpg`, `placa_detectada.jpg`, `placa.jpg` enderezada,
`segmentacion.jpg`). Esas son las que ve el frontend en "Visualización del
proceso".

---

## 3. Comunicación frontend ↔ backend

| Canal | Tipo | Qué lleva | Origen → destino |
|-------|------|-----------|------------------|
| `/ws/ingest` | WS binario+texto | frames + eventos | visión → API |
| `/ws/video` | WS **binario** | JPEG en vivo | API → navegador (canvas) |
| `/ws` | WS **JSON** | eventos + status (fps, hora) | API → navegador |
| `/api/events` | REST GET | historial (desde Postgres) | API → navegador |
| `/static/...` | HTTP | imágenes de etapa (`storage/`) | API → navegador |

- **Video en vivo:** `bridge.send_frame` (último frame gana) → `/ws/ingest` →
  `/ws/video` → `VideoPanel` lo dibuja en un `<canvas>` (`createImageBitmap`).
  Reconecta solo, sin F5.
- **Eventos:** al completar un cruce, `integration.py` arma el payload, lo manda
  por `/ws` (vivo) **y** lo persiste en Postgres. El frontend (`RealtimeContext`)
  lo mapea a `event` y pinta las tarjetas + confianzas.
- **Histórico:** `/api/events` lee de Postgres (joins a `vision` y `difuso`).
- El estado "Aplicado / Omitido" de cada etapa **NO lo deduce la base**: es el
  valor literal del flag (`usar_enderezado`, `usar_filtros`) en el momento del
  evento, viajando en `vision.metadata`.

---

## 4. Calidad del video — DOS calidades distintas (no confundir)

> Esto es lo más importante de entender: **la calidad del stream y la calidad del
> OCR son independientes.**

### 4.1 Stream en vivo (lo que ves moverse en "Video en vivo")
- Se arma en `camara.py`: del frame anotado de 1280×720 se reescala a
  `stream_w = 640` de ancho (→ 640×360) y se codifica JPEG a
  `stream_jpeg_q = 60`.
- O sea, el **video en vivo del navegador es 640×360 @ JPEG 60**, dibujado en un
  canvas que el CSS **agranda** para llenar el panel → por eso se ve algo blando.
- **Subir `stream_w` / `stream_jpeg_q`** → video en vivo más nítido, pero **más
  ancho de banda y más CPU/codificación por frame** (puede bajar FPS). **NO mejora
  el OCR en absoluto.**

### 4.2 Imágenes de etapa (las tarjetas "Placa detectada", "Enderezado"…)
- Se guardan con `cv2.imwrite` (JPEG calidad ~95 por defecto) a su **resolución
  nativa del pipeline** (ej. placa ~200×70).
- El navegador las **estira** vía CSS hasta el ancho de la tarjeta (~500px) → se
  ven borrosas/"zoom" **aunque los píxeles nativos estén bien**. Es upscale del
  CSS, no pérdida del pipeline.

### 4.3 OCR (la lectura real)
- Usa el **`frame_nativo`** (resolución real de la fuente), totalmente
  independiente del stream.
- Su calidad depende de: resolución real de la cámara, qué tan cerca se captura
  (ya optimizado por cercanía), `imgsz` de detección, y la robustez de
  segmentación + OCR. **Nada de esto cambia si subes la calidad del stream.**

**Resumen:** subir calidad del stream = video más lindo, **cero** efecto en la
lectura. Para mejorar la lectura hay que tocar la cadena (ver §5–§6), no el stream.

---

## 5. ¿Dónde se conserva y dónde se pierde calidad?

| Punto | Estado | Nota |
|-------|--------|------|
| Captura del frame | **Nativo** ✓ | se guarda el frame real |
| Recorte de placa (bbox YOLO) | **Nativo** ✓ | corte directo, sin remuestreo |
| **Enderezado** | **condicional** | frontal → pasa nativo (sin pérdida); torcida → warp (remuestrea → suaviza un poco) |
| Filtros | OFF | no degrada |
| Crops de carácter | **Nativos** ✓ | salen de la placa, no del 256×96 |
| OCR 64×64 | resize obligatorio | una vez por carácter |
| Stream en vivo | 640 / q60 | solo display |

**La pregunta "¿enderezar sí o no pierde calidad?":**
- **NO enderezar = SIN pérdida** (es el recorte nativo tal cual).
- **Enderezar = pérdida pequeña** (el `warpPerspective` remuestrea todos los
  píxeles → suaviza), **pero** corrige la inclinación, que la segmentación
  necesita para no partir mal los caracteres.
- Por eso el enderezado es **condicional**: placa casi frontal → no se toca;
  claramente torcida → se warpea. Es un *trade-off* calidad ↔ legibilidad.

---

## 6. Qué está MAL o es FRÁGIL (oportunidades)

1. **OCR sin control de longitud/formato.** El texto de salida = número de cajas
   de segmentación. Si la segmentación parte de más (placa torcida o ruido),
   salen 9–11 caracteres en vez de 7 → resultado basura (ej. `IHB124514689` para
   `HBB-5169`). **No se recorta a 3 letras + 4 dígitos.** *(Arreglo de
   post-proceso, sin costo de calidad.)*
2. **Segmentación sensible a inclinación y ruido.** U-Net + corte por proyección
   asume caracteres ~horizontales; con placa torcida corta mal, y a veces toma el
   guion `-` o un tornillo/borde como carácter extra.
3. **Detección de placa a `imgsz=416`.** Rango de detección corto (la encuentra
   solo cuando ya está cerca). El otro proyecto usa 640.
4. **Enderezado por contornos (Canny) poco fiable;** los umbrales condicionales
   pueden disparar o no en el límite.
5. **`conf_ocr` promedia caracteres basura** → confianza engañosa (ej. 58% con
   lectura incorrecta).

### Código sin uso hoy
- **ETAPA 0 (carros):** `detectar_carros=false`. El modelo y sus ramas existen
  pero no se usan.
- **Filtros:** `usar_filtros=false`. `filtros/` presente pero inactivo.
- **Fuentes URL/RTSP** y la lógica de **reconexión** en `camara.py`: solo se usa
  USB / archivo de video.
- **`max_ancho_px`, `min_nitidez`** en `config.json`: en desuso (el "mejor" se
  elige por cercanía).
- **`ancho_placa`, `alto_placa`** en `deteccion_placas/config.json`: ya no los usa
  el enderezado nuevo (legado).
- **Modo `calibrar` / trackbars:** solo para puesta a punto, no para producción.

---

## 7. Diferencia de fondo con `Detecci-n-Placas-YOLOv12-main`

Ese proyecto **no endereza y no segmenta**: pasa el recorte de placa (con
preprocesado suave) a un **YOLO de caracteres** que detecta + clasifica cada
letra en una pasada, y luego **vota** entre variantes y **fuerza el formato**
(3 letras + 3/4 dígitos eligiendo la mejor secuencia). Por eso:
- No pierde calidad por warp (no warpea).
- No tiene el cuello de segmentación (un modelo hace todo).
- Tolera inclinación nativamente.

Replicarlo (a futuro) eliminaría de un golpe los problemas §6.1–§6.4.

---

## 8. Recomendaciones priorizadas (sin perder calidad)

1. **Forzar formato de placa** (3 letras + 4 dígitos, recortar a 7, elegir mejor
   secuencia por confianza). Post-proceso, **cero** costo de calidad. Arregla el
   caso `IHB124514689`.
2. **Filtrar cajas de ruido** en segmentación (altura/aspecto mínimos, descartar
   el guion). Cero costo de calidad.
3. **Subir `imgsz` de detección 416 → 640** (más rango, no toca el crop).
4. (Grande) **Reemplazar U-Net + CNN por YOLO de caracteres** como el otro
   proyecto → mata warp + segmentación frágil.

> Nada de lo anterior pasa por subir la calidad del stream: eso solo cambia el
> video en vivo, no la lectura.
