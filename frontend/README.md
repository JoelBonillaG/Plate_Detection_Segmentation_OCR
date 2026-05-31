# Frontend

Interfaz web del sistema de monitoreo vehicular universitario.

No procesa imagen ni corre inferencia. Solo consume lo que expone el backend:

- `GET  /api/cameras/main/stream`  video en vivo (MJPEG, proxy hacia vision)
- `GET  /ws`                       WebSocket — eventos y status en tiempo real
- `GET  /api/events`               historial de eventos
- `GET  /api/events/{id}`          detalle de un evento
- `PATCH /api/events/{id}/approve` aprobar sancion (envia correo si hay SMTP)
- `PATCH /api/events/{id}/reject`  rechazar evento
- `GET  /static/...`               imagenes guardadas (frames y placas)

## Requisitos

- Node.js 18 o superior
- Backend corriendo en `http://127.0.0.1:8000`
- Vision corriendo en `http://127.0.0.1:8001` (el backend le hace proxy)

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
| `VITE_VIDEO_URL` | `http://<host>:8000/api/cameras/main/stream` | Stream MJPEG |

Si no se definen, el frontend infiere el host de `window.location.hostname`.

## Flujo de datos

```text
vision (puerto 8001)
  -> MJPEG /stream.mjpeg
  -> API proxy /api/cameras/main/stream
  -> <img src="/api/cameras/main/stream" /> en el dashboard

API (puerto 8000)
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
