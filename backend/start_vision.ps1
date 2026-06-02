# Arranca el modulo de vision (camara + pipeline + puente WS hacia la API).
#
# Uso:
#   .\start_vision.ps1              # webcam por defecto (indice 0)
#   .\start_vision.ps1 1            # otra webcam
#   .\start_vision.ps1 video.mp4    # archivo de video
#   .\start_vision.ps1 C:\ruta\video.mp4
#
# Vision empuja los frames a la API por WebSocket (/ws/ingest); la API los
# reenvia al browser en /ws/video. Puede arrancar antes o despues de la API.

param(
  [string]$Fuente = "0"
)

$ErrorActionPreference = "Stop"

$backendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $backendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
  throw "No existe el Python del backend en .venv. Crea el entorno e instala dependencias primero."
}

& $python -m src.vision.main $Fuente
