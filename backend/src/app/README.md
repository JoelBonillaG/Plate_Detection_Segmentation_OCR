# API (FastAPI)

Capa web del sistema. Expone eventos al frontend, transmite el video en
vivo (proxy hacia vision), empuja eventos por WebSocket y envia notificaciones.

No procesa imagen: eso lo hace vision (`src/vision`). La API solo lee/escribe
la base de datos y publica lo que vision genera.

## Modulos

| Archivo | Rol |
|---|---|
| `main.py` | rutas FastAPI (REST, WebSocket, MJPEG proxy) |
| `realtime.py` | manager de WebSocket |
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

- `GET /health` — estado general y config visible.
- `GET /health/db` — prueba la conexion a PostgreSQL.

### Video en vivo

- `GET /api/cameras/main/stream` — proxy MJPEG hacia vision (puerto 8001).
  El frontend lo consume con `<img src="/api/cameras/main/stream">`.
  La URL de vision es configurable con `VISION_STREAM_URL` en `.env`
  (default: `http://localhost:8001/stream.mjpeg`).

### Eventos

- `GET  /api/events?limit=&offset=` — ultimos eventos con joins a vision y difuso.
- `GET  /api/events/{id}` — un evento con todo su detalle.
- `PATCH /api/events/{id}/approve` — aprueba la sancion; crea notificacion y
  envia correo al propietario (si tiene). Body: `{ placa_corregida?, motivo? }`.
- `PATCH /api/events/{id}/reject` — rechaza el evento. Body: `{ motivo? }`.

### Tiempo real

- `GET /ws` — WebSocket. Empuja:
  - `{ "type": "event",  "data": {...} }` — deteccion nueva (placa, velocidad, infraccion, evidencia)
  - `{ "type": "status", "data": {...} }` — fps, camara conectada, hora
  - Responde `{ "type": "pong" }` al `{ "type": "ping" }` del cliente.

### Notificaciones

- `POST /notifications/test-email` — correo de prueba.
- `POST /notifications/send-pending` — envia notificaciones pendientes.

### Estaticos

- `GET /static/...` — sirve `backend/storage/` (frames y placas guardadas).

## Como recibe los datos de vision

Vision corre en su propio proceso (`python -m src.vision.main`):

- Sirve video MJPEG en `http://localhost:8001/stream.mjpeg` directamente.
- La API hace **proxy** en `/api/cameras/main/stream` con `httpx`.
- Cuando un carro cruza, `integration.py` llama `broadcast_event` (WebSocket)
  e `insert_evento` (DB) desde el mismo proceso de vision.

Si la API no esta levantada, vision sigue en modo standalone.
