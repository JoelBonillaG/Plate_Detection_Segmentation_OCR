# Arranca el modulo de vision (camara + pipeline + puente WS hacia la API).
#
# Uso:
#   .\start_vision.ps1              # usa la 'fuente' de vision/config.json
#   .\start_vision.ps1 1            # otra webcam (pisa el config)
#   .\start_vision.ps1 video.mp4    # archivo de video (pisa el config)
#   .\start_vision.ps1 C:\ruta\video.mp4
#
# Vision empuja los frames a la API por WebSocket (/ws/ingest); la API los
# reenvia al browser en /ws/video. Puede arrancar antes o despues de la API.

param(
  # vacio por defecto -> NO se pasa argumento y main.py usa la 'fuente' de
  # vision/config.json. Si pasas un valor, ESE tiene prioridad sobre el config.
  [string]$Fuente = ""
)

$ErrorActionPreference = "Stop"

$backendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $backendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
  throw "No existe el Python del backend en .venv. Crea el entorno e instala dependencias primero."
}

# sin argumento -> arranca sin fuente CLI (main.py toma la del config.json).
# con argumento -> se pasa y tiene prioridad.
if ($Fuente -ne "") {
  & $python -m src.vision.main $Fuente
} else {
  & $python -m src.vision.main
}
