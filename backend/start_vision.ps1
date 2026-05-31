# Arranca el modulo de vision (camara + pipeline + servidor MJPEG).
#
# Uso:
#   .\start_vision.ps1              # webcam por defecto (indice 0)
#   .\start_vision.ps1 1            # otra webcam
#   .\start_vision.ps1 video.mp4    # archivo de video
#   .\start_vision.ps1 C:\ruta\video.mp4
#
# El video se sirve en: http://localhost:8001/stream.mjpeg
# La API lo proxea en:  http://localhost:8000/api/cameras/main/stream

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
