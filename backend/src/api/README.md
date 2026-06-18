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
python -m uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

Lee variables desde `.env` en la raiz del repo (ver `backend/README.md`).

## Endpoints

### Estado

- `GET /health` — estado general y config visible.
- `GET /health/db` — prueba la conexion a PostgreSQL.

### Video en vivo

- `WS /ws/video` — frames JPEG en binario. El frontend los dibuja en un
  `<canvas>` y reconecta solo (no necesita F5).
- `WS /ws/ingest` — ingesta desde el proceso de vision: recibe frames (binario)
  y eventos/status (JSON) y los reenvia a `/ws/video` y `/ws` respectivamente.
  Es el unico puente vision -> api (procesos separados).

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

- Abre un WebSocket **cliente** a `/ws/ingest` (ver `vision/bridge.py`) y empuja
  cada frame anotado (binario) + eventos/status (JSON). La API los reenvia.
- El puente reconecta solo: vision y api pueden arrancar en cualquier orden.
- Cuando un carro cruza, `integration.py` llama `broadcast_event` (-> puente)
  e `insert_evento` (DB, conexion directa a Postgres desde vision).

Si la API no esta levantada, vision sigue capturando y el puente reintenta.
