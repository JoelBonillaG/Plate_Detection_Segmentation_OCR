# API (FastAPI)

Capa web del sistema. Expone los eventos al frontend, transmite el video en
vivo, empuja eventos por WebSocket y envia notificaciones por correo.

No procesa imagen: eso lo hace la vision (`src/vision`). La API solo lee/escribe
la base de datos y publica lo que la vision genera.

## Modulos

| Archivo | Rol |
|---|---|
| `main.py` | rutas FastAPI (REST, WebSocket, MJPEG) |
| `realtime.py` | manager de WebSocket + buffer del frame MJPEG |
| `events_db.py` | queries de eventos (insert + fetch con joins) |
| `database.py` | conexion a PostgreSQL |
| `mailer.py` | envio de correos por SMTP |
| `config.py` | settings desde `.env` (DB y SMTP) |

## Ejecutar

Desde `backend/`:

```bash
python -m uvicorn src.app.main:app --reload --host 127.0.0.1 --port 8000
```

Lee variables desde `.env` en la raiz del repo (ver `backend/README.md`).

## Endpoints

### Estado

- `GET /health` — estado general y config visible (no sensible).
- `GET /health/db` — prueba la conexion a PostgreSQL.

### Eventos (lo que ve el frontend)

- `GET /events?limit=&offset=` — ultimos eventos con joins a vision y difuso.
- `GET /events/{id}` — un evento con todo su detalle.
- `PATCH /events/{id}/approve` — aprueba la sancion; crea la notificacion y
  envia el correo al propietario (si tiene). Body: `{ placa_corregida?, motivo? }`.
- `PATCH /events/{id}/reject` — rechaza el evento. Body: `{ motivo? }`.

### Tiempo real

- `GET /ws` — WebSocket. Empuja `event` (evento nuevo) y `status` (fps, camara).
  Responde `ping`/`pong` para mantener viva la conexion.
- `GET /video_feed` — video MJPEG (`multipart/x-mixed-replace`). El frontend lo
  consume con `<img src=".../video_feed">`.

### Notificaciones

- `POST /notifications/test-email` — envia un correo de prueba por SMTP.
- `POST /notifications/send-pending` — toma notificaciones pendientes, las envia
  y actualiza su estado.

### Estaticos

- `GET /static/...` — sirve `backend/storage/` (frames y placas guardados por la
  vision; las rutas se devuelven en cada evento).

## Como recibe los datos de la vision

La vision corre en su propio proceso (`python -m src.vision.main`). Cuando un
carro completa un cruce, `src/vision/integration.py` llama:

- `set_current_frame(jpeg)` — actualiza el frame del `/video_feed`.
- `insert_evento / insert_vision / insert_difuso` — persisten en DB.
- `broadcast_event(payload)` — empuja el evento por `/ws`.

Si la API no esta levantada, la vision sigue corriendo en modo standalone (los
puentes quedan como no-ops).
