# Arranca la API FastAPI (REST + WebSocket de eventos y de video).
#
# Uso:
#   .\start_api.ps1
#
# Endpoints principales:
#   WS   /ws/video                  video en vivo (frames JPEG -> canvas)
#   WS   /ws/ingest                 ingesta de frames+eventos desde vision
#   GET  /ws                        WebSocket — eventos y status
#   GET  /api/events                historial de eventos
#   GET  /health                    estado del sistema
#
# Requiere PostgreSQL corriendo (docker compose up -d postgres).

$ErrorActionPreference = "Stop"

$backendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $backendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
  throw "No existe el Python del backend en .venv. Crea el entorno e instala dependencias primero."
}

& $python -m uvicorn src.app.main:app --reload --host 127.0.0.1 --port 8000
