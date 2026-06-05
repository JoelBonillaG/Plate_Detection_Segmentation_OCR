# Frontend

Interfaz web del sistema de monitoreo vehicular universitario.

No procesa imagen ni corre inferencia. Solo consume lo que expone el backend:

- `WS   /ws/video`                 video en vivo (frames JPEG binarios -> canvas)
- `GET  /ws`                       WebSocket — eventos y status en tiempo real
- `GET  /api/events`               historial de eventos
- `GET  /api/events/{id}`          detalle de un evento
- `PATCH /api/events/{id}/approve` aprobar sancion (envia correo si hay SMTP)
- `PATCH /api/events/{id}/reject`  rechazar evento
- `GET  /static/...`               imagenes guardadas (frames y placas)

## Requisitos

- Node.js 18 o superior
- Backend corriendo en `http://127.0.0.1:8000`
- Vision corriendo (`start_vision`); empuja video/eventos a la API por WebSocket

## Instalar y ejecutar

Desde este directorio:

```bash
npm install
npm run dev       # http://127.0.0.1:5173
```

O:

```bash
npm start
```

## Variables de entorno (opcionales)

Crear `.env` junto a `package.json` (ver `.env.example`):

| Variable | Default | Para que |
|---|---|---|
| `VITE_API_URL` | `http://<host>:8000` | URL base de la API |
| `VITE_WS_URL` | `ws://<host>:8000/ws` | WebSocket del backend |
| `VITE_VIDEO_WS_URL` | `ws://<host>:8000/ws/video` | WebSocket de video (frames JPEG) |

Si no se definen, el frontend infiere el host de `window.location.hostname`.

## Flujo de datos

```text
vision (proceso aparte)
  -> WS cliente a la API /ws/ingest  (frames JPEG binarios + eventos/status JSON)

API (puerto 8000)
  -> /ws/video    reenvia frames -> <canvas> en el dashboard
  -> /ws          eventos y status en tiempo real
  -> /api/events  historial paginado
```

## Estructura

```text
src/
  App.jsx               paginas y componentes (Dashboard, Eventos, Detalle)
  context/
    RealtimeContext.jsx conexion WebSocket + estado global
  services/
    ws.js               singleton WebSocket con reconexion y ping/pong
  mocks/
    mockData.js         datos de ejemplo mientras no hay backend
  styles/
    app.css             estilos globales
```

## Comportamiento sin backend

Si el backend o la vision no estan corriendo, el frontend muestra los datos
de `mocks/mockData.js` (eventos de ejemplo). El WebSocket intenta reconectar
automaticamente cada vez que se cae.
