# Frontend

Interfaz web del sistema de monitoreo vehicular.

Este frontend no procesa imagen ni corre inferencia. Solo consume lo que expone
el backend:

- `GET /video_feed` para el video MJPEG en vivo
- `GET /ws` para eventos y estado en tiempo real
- `GET /events` y `GET /events/{id}` para historial
- `PATCH /events/{id}/approve` y `/reject` para revision

## Requisitos

- Node.js 18 o superior
- Backend corriendo en `http://127.0.0.1:8000`

## Como instalar

Desde este directorio:

```bash
npm install
```

## Como ejecutar

```bash
npm run dev
```

El servidor de desarrollo corre en `http://127.0.0.1:5173`.

Tambien puedes usar:

```bash
npm start
```

## Como se integra con el backend

La app usa estas variables opcionales:

- `VITE_WS_URL`: URL del WebSocket del backend
- `VITE_VIDEO_URL`: URL del MJPEG del backend

Si no las defines, usa por defecto:

- `ws://<host>:8000/ws`
- `http://<host>:8000/video_feed`

Si quieres fijarlas, crea un archivo `.env` junto a `package.json` usando como
base `frontend/.env.example`.

## Flujo de datos

```text
src.app.main
  -> /ws          eventos y status
  -> /video_feed  video MJPEG
  -> /events      listado de eventos
```

El frontend solo presenta la informacion; no reemplaza al backend ni a la
vision.
