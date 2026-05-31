# Cámara — captura por líneas virtuales

Abre una fuente de video, dibuja dos líneas inclinadas y dispara la captura del
frame más nítido cuando una placa cruza la zona. El frame capturado se pasa al
pipeline (etapa 1 → OCR).

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
(`0`=izq/arriba, `1`=der/abajo). Inclinables para seguir el carril.

### Gates — *cuándo* aceptar  (*gate = compuerta / filtro de paso*)
| Param | Qué filtra | Por qué el nombre |
|---|---|---|
| `MIN_ANCHO_PX` | placa más chica = muy lejos → ignora | ancho mínimo de placa en píxeles |
| `MAX_ANCHO_PX` | placa más grande = muy cerca / de perfil → ignora (`0`=sin tope) | ancho máximo en px |
| `MIN_NITIDEZ` | frame más borroso que esto → descarta | nitidez mínima (anti motion-blur) |

**Nitidez** = varianza del Laplaciano del crop de la placa. Alto = enfocado,
bajo = borroso. Se usa para 1) elegir el mejor frame del cruce y 2) descartar si
todo salió borroso.

### Velocidad — *qué tan rápido*
| Param | Qué es | Por qué el nombre |
|---|---|---|
| `DISTANCIA_M` | distancia REAL en metros entre las dos líneas (calibrable) | numerador de la velocidad |
| `FPS_FALLBACK` | FPS asumido si la fuente no lo reporta | convierte frames → segundos |

Cálculo: `velocidad_km/h = DISTANCIA_M / (t_sale − t_entra) × 3.6`.
Se mide al cruzar SALE (mismo disparo de la captura). El tiempo se toma según
la fuente: **video** → `frame/FPS` (confiable, FPS fijo); **vivo (celu/webcam)**
→ reloj real (aproximado, el FPS del WiFi varía). Sale `n/d` si el carro no
cruzó ambas líneas limpio.

### Control
| Param | Qué hace |
|---|---|
| `CALIBRAR` | `True` = modo debug (sliders + arrastrar líneas + overlay de números). `False` = limpio para demo/producción |
| `fuente` (argv) | webcam `0` / `video.mp4` / URL del celular |

## Idea clave

- **Líneas = espacio** (dónde capturar).
- **Gates = calidad** (tamaño + nitidez suficientes).
- **Captura** = mejor frame entre las líneas que pase los gates.

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
carro lejos      → placa chica → gate de tamaño la bloquea (espera)
cruza ENTRA       → arranca cronómetro (t_entra), guarda frame de entrada
carro en zona    → mide nitidez por frame → guarda el más nítido
cruza SALE        → guarda frame de salida, para cronómetro (t_sale) → velocidad
                  → ¿mejor frame ≥ MIN_NITIDEZ? sí→guarda + OCR  no→descarta
```

## Qué se guarda (una carpeta por carro)

```
capturas/
  20260530_102215_carro001/
    entra.jpg     ← frame al cruzar ENTRA (lejos)
    mejor.jpg     ← frame más nítido → el que va al OCR
    sale.jpg      ← frame al cruzar SALE (cerca)
    datos.json    ← placa, velocidad, nitidez, ancho px, tiempos, hora
```

`datos.json` (solo métricas de la **cámara**, sin el número de placa):
```json
{
  "carro": "20260530_102215_carro001",
  "velocidad_kmh": 38.4,
  "nitidez": 145.2,
  "ancho_placa_px": 210,
  "t_entra_s": 1.23,
  "t_sale_s": 1.70,
  "hora": "2026-05-30 10:22:15"
}
```

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
