# Backend

Este directorio concentra el backend del sistema:

- `src/app`: API FastAPI, WebSocket, MJPEG, eventos y notificaciones.
- `src/vision`: pipeline en vivo y standalone para deteccion, segmentacion y OCR.
- `database`: esquema PostgreSQL y datos seed.
- `storage`: frames e imagenes guardadas por el pipeline.

## Requisitos

- Python 3.10 o 3.11
- Docker Desktop
## Orden recomendado de instalacion

### 1. Crear el entorno virtual

Desde `backend/`:

```bash
python -m venv .venv
```

Activar en Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 2. Instalar dependencias de Python

Instala primero lo del API y luego lo del pipeline:

```bash
pip install -r src/app/requirements.txt
pip install -r src/vision/requirements.txt
```

Si tu equipo usa GPU, ajusta las versiones de `torch` y `tensorflow` segun tu
entorno antes de instalar.

### 3. Levantar PostgreSQL

Desde la raiz del repositorio:

```bash
docker compose up -d postgres
```

Eso usa `backend/database/init.sql` para crear tablas, enums y datos seed.

### 4. Configurar `.env`

En la raiz del repositorio:

```bash
POSTGRES_DB=monitoreo_vehicular
POSTGRES_USER=monitoreo_user
POSTGRES_PASSWORD=monitoreo_pass
POSTGRES_HOST_PORT=5433
```

Si prefieres partir de un ejemplo, copia `backend/.env.example` a `.env` en la
raiz del repo y completa los valores que correspondan.

### 5. Levantar la API

Desde `backend/`:

```bash
python -m uvicorn src.app.main:app --reload --host 127.0.0.1 --port 8000
```

O usa el atajo:

```powershell
.\start_api.ps1
```

### 6. Levantar la vision en vivo

Desde `backend/`:

```bash
python -m src.vision.main
```

O usa el atajo:

```powershell
.\start_vision.ps1
```

Opciones comunes:

```bash
python -m src.vision.main 0
python -m src.vision.main 1
python -m src.vision.main video.mp4
python -m src.vision.main C:\ruta\completa\video.mp4
```

`start_vision.ps1` acepta un argumento opcional:

```powershell
.\start_vision.ps1 1
.\start_vision.ps1 video.mp4
.\start_vision.ps1 C:\ruta\completa\video.mp4
```

La ruta puede ser relativa o absoluta. La absoluta es mas segura.

## Como se conectan las piezas

```text
src.vision.main
  -> src.vision.integration
  -> PostgreSQL
  -> src.app.realtime
  -> src.app.main
```

`src.vision.main` puede correr sin el backend web. `src.vision.integration` solo
entra cuando quieres persistir eventos, publicar WebSocket o servir el MJPEG.

## Entrada rapida

Si solo quieres probar el flujo completo sin frontend:

1. Levanta PostgreSQL.
2. Activa `.venv`.
3. Ejecuta `python -m src.vision.main <video o camara>`.

Si quieres la experiencia completa del backend:

1. Levanta PostgreSQL.
2. Ejecuta la API FastAPI.
3. Ejecuta la vision.

## Referencias utiles

- [API del backend](src/app/README.md)
- [Modelo de datos](database/README.md)
- [Camara](src/vision/camara/README.md)
- [Pipeline](src/vision/pipeline/README.md)
