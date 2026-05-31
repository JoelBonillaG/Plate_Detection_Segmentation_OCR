# Cámara — captura por líneas virtuales

Abre una fuente de video, dibuja dos líneas inclinadas y dispara la captura
cuando un **carro** cruza la zona. El **carro** manda el cruce y la velocidad
(es grande y estable, casi no parpadea); la **placa** solo aporta el mejor crop
para el OCR. El frame capturado se pasa al pipeline (etapa 0 → OCR).

## Ejecutar

Desde la carpeta `app`:

```
python main.py                      # webcam (índice 0)
python main.py 1                    # otra webcam
python main.py video.mp4            # archivo grabado (desarrollo)
python main.py http://IP:4747/video # celular vía DroidCam / IP Webcam (demo)
```

Una sola app; solo cambia el argumento `fuente`.

## Parámetros (en `camara.py`)

### Líneas — *dónde* mirar
| Param | Qué es | Por qué el nombre |
|---|---|---|
| `LINEA_ENTRA` | línea **lejana**: el carro entra a la zona, empieza el rastreo | "entra" = inicia |
| `LINEA_SALE` | línea **cercana**: el carro sale, dispara la captura | "sale" = cierra y manda al OCR |

Cada línea = dos puntos `((x1,y1),(x2,y2))` en fracciones `0..1` del frame
(`0`=izq/arriba, `1`=der/abajo). Inclinables para seguir el carril. El cruce se
prueba con el **centro del carro**: cuando cruza ENTRA empieza a rastrear, cuando
cruza SALE dispara la captura.

### Parpadeo — *no perder el carro por un frame*
El detector a veces pierde el carro un frame suelto (parpadeo). En vez de soltar
el rastreo al toque, se aguantan unos frames seguidos sin detección antes de
darlo por ido. Así el cronómetro arranca temprano y la velocidad sale real (si
reseteara, re-arrancaría tarde → tiempo corto → velocidad inflada).

| Param | Qué hace |
|---|---|
| `tolerancia_frames` | frames seguidos SIN carro que aguanta sin resetear (el carro casi no parpadea → con 2-3 alcanza) |

### Gates — *cuándo* aceptar  (*gate = compuerta / filtro de paso*)
| Param | Qué filtra |
|---|---|
| `MIN_ANCHO_PX` | ancho mínimo de la **placa** para que su crop valga la pena para el OCR (placa muy chica = ilegible). Ya **no** controla el cruce: eso lo maneja el carro. |
| `MAX_ANCHO_PX` | *(en desuso)* quedaba del rastreo por placa. |
| `MIN_NITIDEZ` | *(en desuso)* antes descartaba capturas borrosas; ahora siempre se guarda. |

**Nitidez** = varianza del Laplaciano. Sirve para **elegir el mejor frame** del
cruce (el más nítido), no para descartar.

### Velocidad — *qué tan rápido*
| Param | Qué es | Por qué el nombre |
|---|---|---|
| `DISTANCIA_M` | distancia REAL en metros entre las dos líneas (calibrable) | numerador de la velocidad |
| `FPS_FALLBACK` | FPS asumido si la fuente no lo reporta | convierte frames → segundos |

Cálculo: `velocidad_km/h = DISTANCIA_M / (t_sale − t_entra) × 3.6`.
Se mide con el **centro del carro**: arranca al cruzar ENTRA, para al cruzar
SALE. El tiempo se toma según la fuente: **video** → `frame/FPS` (confiable, FPS
fijo); **vivo (celu/webcam)** → reloj real (aproximado, el FPS del WiFi varía).
Sale `n/d` si el carro no cruzó ambas líneas limpio.

### Control
| Param | Qué hace |
|---|---|
| `CALIBRAR` | `True` = modo debug (sliders + arrastrar líneas + overlay de números). `False` = limpio para demo/producción |
| `fuente` (argv) | webcam `0` / `video.mp4` / URL del celular |

## Idea clave

- **Carro = cuándo** (cruza ENTRA→SALE: marca el tiempo y dispara la captura).
- **Placa = qué leer** (aporta el mejor crop para el OCR).
- **Captura** = el frame más nítido del cruce (con placa si la hubo; si no, el
  frame de carro más nítido como respaldo).

## Calibrar (modo debug, `CALIBRAR=True`)

1. Corre con el video del sitio real.
2. Arrastra los puntos magenta para alinear ENTRA/SALE al carril.
3. Mueve los sliders mirando el overlay (verde = pasa el gate, rojo = no).
4. Tecla `s` → imprime la config actual en consola.
5. Pega esa config en `camara.py` para dejarla fija.
6. Demo/producción → `CALIBRAR = False`.

Teclas: `s` guarda config (solo en calibración), `q` sale.

## Flujo

```
carro cruza ENTRA → arranca cronómetro (t_entra), guarda frame de entrada
carro en zona     → cada frame: ¿hay placa? mide su nitidez → guarda el más nítido
                    (si la placa no aparece, guarda el frame de carro más nítido)
parpadeo (1 frame sin carro) → aguanta (no resetea) hasta tolerancia_frames
carro cruza SALE  → guarda frame de salida, para cronómetro (t_sale) → velocidad
                  → arma la captura y la manda al OCR (siempre se guarda)
```

## Qué se guarda (una carpeta por carro)

```
capturas/
  20260530_102215_carro001/
    entra.jpg     ← frame al cruzar ENTRA (lejos)
    mejor.jpg     ← frame más nítido → el que va al OCR
    sale.jpg      ← frame al cruzar SALE (cerca)
    datos.json    ← velocidad, nitidez, ancho px, tiempo de cruce, hora
```

`datos.json` (solo métricas de la **cámara**, sin el número de placa):
```json
{
  "carro": "20260530_102215_carro001",
  "con_placa": true,
  "velocidad_kmh": 38.4,
  "tiempo_cruce_s": 0.47,
  "nitidez": 145.2,
  "ancho_placa_px": 210,
  "hora": "2026-05-30 10:22:15"
}
```

- **`con_placa`**: `true` = el mejor frame tenía placa detectada (lo normal).
  `false` = nunca se vio la placa en el cruce y se guardó el frame de carro más
  nítido como respaldo (el OCR quizá no lea, pero la velocidad sí sale). Con
  `con_placa: false`, `ancho_placa_px` es `0`.

**La cámara detecta la placa (dónde está) pero NO lee el número.** Leer el texto
es trabajo del pipeline (OCR), una capa aparte; por eso no aparece en este JSON.
El pipeline guarda su propia auditoría (detecciones/, enderezadas/, resultado
del OCR, etc.) con el mismo `nombre` de carro.

## Overlay en pantalla (2 niveles)

| Elemento | `CALIBRAR=True` | `CALIBRAR=False` (demo) |
|---|---|---|
| Velocidad del último carro | ✅ | ✅ **siempre** |
| Líneas ENTRA/SALE + estado | ✅ | ✅ |
| Caja del **carro** (naranja, solo dentro de la zona) | ✅ | ✅ |
| Caja de la **placa** (verde, solo dentro de la zona) | ✅ | ✅ |
| Sliders, puntos magenta, ancho/nitidez/distancia | ✅ | ❌ |

Las cajas **naranja** (carro, ETAPA 0) y **verde** (placa) solo se dibujan cuando
su centro cae dentro de la zona ENTRA–SALE. YOLO igual corre sobre todo el frame:
la zona filtra qué se dibuja y la captura se dispara al cruzar SALE (la placa se
sigue rastreando aunque salga de la zona, para no perder el cruce).
