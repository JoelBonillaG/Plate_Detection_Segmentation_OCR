# Camara - captura por lineas virtuales

Abre una fuente de video, dibuja dos lineas inclinadas y dispara una captura
cuando un **carro** cruza la zona. El frame capturado se entrega por callback al
pipeline; lo consume `cadena.py` (standalone) o `integration.py` (backend).

La idea central del diseno nuevo:

- el **carro** manda el cruce (ENTRA -> SALE) y la **velocidad**: es grande y
  estable, casi no parpadea, asi el tiempo de cruce sale confiable.
- la **placa** solo aporta el mejor crop para el OCR cuando aparece. No decide el
  cruce (es chica y parpadea, no sirve para medir).

## Ejecutar

Desde `backend/`:

```bash
python -m src.vision.main             # webcam (indice 0)
python -m src.vision.main 1           # otra webcam
python -m src.vision.main video.mp4   # archivo grabado (desarrollo)
python -m src.vision.main http://IP:4747/video   # celular DroidCam / IP Webcam
```

`src/vision/main.py` solo carga modelos, arma los callbacks y llama a
`camara.iniciar()`. La camara no sabe nada de DB, WebSocket ni MJPEG.

## Que hace `camara.py`

`camara.py` es reusable y agnostico del backend. Su trabajo es:

1. Abrir la fuente de video.
2. Pedir al detector (callback) el carro y la placa de cada frame.
3. Rastrear el cruce del carro y elegir el mejor frame.
4. Dibujar lineas, cajas (carro naranja, placa verde) y velocidad.
5. Guardar una captura por cruce y entregarla por `al_capturar`.

## Parametros (en `camara/config.json`)

Toda la configuracion vive en `camara/config.json` (no en el codigo). `camara.py`
lo lee al arrancar; si falta el archivo o una clave, usa los defaults de `_DEFAULTS`.
Las claves del JSON van en minuscula con guion bajo (`linea_entra`, `detectar_carros`,
`mostrar_ventana`, ...); abajo se nombran en MAYUSCULA solo por costumbre.

En modo calibracion, la tecla **`s`** guarda lineas + gates + distancia de vuelta
en `config.json` (conserva las demas claves) — ya no se pega nada en el codigo.

### Lineas - donde mirar

| Clave | Que es |
|---|---|
| `linea_entra` | linea lejana: el carro entra a la zona, empieza el rastreo |
| `linea_sale` | linea cercana: el carro sale, dispara la captura |

Cada linea = dos puntos `((x1,y1),(x2,y2))` en fracciones `0..1` del frame.
Inclinables para seguir el carril. El cruce se prueba con el **centro del carro**
(signo del producto cruz contra cada recta).

### Parpadeo - no perder el carro por un frame

El detector a veces pierde el carro un frame suelto (parpadeo). En vez de soltar
el rastreo al toque, se aguantan unos frames seguidos sin verlo antes de darlo
por ido. Asi el cronometro arranca temprano y la velocidad sale real (si
reseteara, re-arrancaria tarde -> tiempo corto -> velocidad inflada).

| Param | Que hace |
|---|---|
| `tolerancia_frames` | frames seguidos SIN carro que se aguantan antes de resetear (el carro casi no parpadea -> con 2-3 alcanza) |

### Gates - calidad del crop

| Param | Que filtra |
|---|---|
| `MIN_ANCHO_PX` | ancho minimo de la **placa** para que su crop valga para el OCR (placa muy chica = ilegible). Ya **no** controla el cruce. |
| `MAX_ANCHO_PX` | *(en desuso)* quedaba del rastreo por placa |
| `MIN_NITIDEZ` | *(en desuso)* antes descartaba capturas borrosas; ahora siempre se guarda |

**Nitidez** = varianza del Laplaciano. Sirve para **elegir el mejor frame** del
cruce (el mas nitido), no para descartar.

### Velocidad - que tan rapido

| Param | Que es |
|---|---|
| `DISTANCIA_M` | distancia real en metros entre las dos lineas (calibrable) |
| `FPS_FALLBACK` | FPS asumido si la fuente no lo reporta |

Calculo: `velocidad_km/h = DISTANCIA_M / (t_sale - t_entra) * 3.6`, medido con el
**centro del carro**. En video el tiempo sale de `frame/FPS`; en vivo, del reloj.

### Control

| Clave | Que hace |
|---|---|
| `calibrar` | `true` = modo debug (sliders, arrastrar lineas, overlay; tecla `s` guarda). `false` = limpio |
| `mostrar_ventana` | `true` = abre ventana OpenCV local. `false` = headless (solo alimenta el video al backend) |
| `detectar_carros` | `true` = el CARRO maneja el cruce/velocidad (placa dentro del carro). `false` = la PLACA maneja el cruce (sin ETAPA 0) |
| `fuente` (argv) | webcam `0` / `video.mp4` / URL del celular |

## Idea clave

- **Carro = cuando** (cruza ENTRA->SALE: marca el tiempo y dispara la captura).
- **Placa = que leer** (aporta el mejor crop para el OCR).
- **Captura** = el frame mas nitido del cruce (con placa si la hubo; si no, el
  frame de carro mas nitido como respaldo).

## Flujo

```text
carro cruza ENTRA -> arranca cronometro, guarda frame de entrada
carro en zona     -> cada frame: ¿hay placa? mide su nitidez -> guarda el mas nitido
                     (si la placa no aparece, guarda el frame de carro mas nitido)
parpadeo          -> aguanta (no resetea) hasta tolerancia_frames
carro cruza SALE  -> calcula velocidad, arma la captura y la manda al OCR
```

## Que se guarda (una carpeta por carro)

```text
capturas/
  20260531_000411_carro001/
    entra.jpg     <- frame al cruzar ENTRA (lejos)
    mejor.jpg     <- frame mas nitido -> el que va al OCR
    sale.jpg      <- frame al cruzar SALE (cerca)
    datos.json    <- velocidad, nitidez, ancho px, tiempo de cruce, con_placa
```

`datos.json` guarda solo metricas de la **camara**, sin el numero de placa:

```json
{
  "carro": "20260531_000411_carro001",
  "con_placa": true,
  "velocidad_kmh": 38.4,
  "tiempo_cruce_s": 0.47,
  "nitidez": 145.2,
  "ancho_placa_px": 210,
  "hora": "2026-05-31 00:04:11"
}
```

- **`con_placa`**: `true` = el mejor frame tenia placa (lo normal). `false` =
  nunca se vio la placa y se guardo el frame de carro como respaldo (el OCR quiza
  no lea, pero la velocidad si sale); en ese caso `ancho_placa_px` es `0`.

## Integracion con el backend

`iniciar()` acepta dos callbacks opcionales que son los **unicos** puentes con el
backend. Si no se pasan, la camara funciona 100% standalone:

| Callback | Para que |
|---|---|
| `on_frame(jpeg_bytes)` | cada frame ya anotado, en JPEG -> feed MJPEG |
| `on_fps(fps)` | ~1 vez por segundo con el FPS real -> status WebSocket |

La lectura del texto de la placa la hace el **pipeline** (`cadena.py`), no la
camara. Ver [pipeline](../pipeline/README.md).
