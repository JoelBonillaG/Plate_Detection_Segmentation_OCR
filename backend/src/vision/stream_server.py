"""
Servidor MJPEG minimo para el modulo de vision.

Sirve el ultimo frame anotado en GET /stream.mjpeg.
Corre en un daemon thread junto al loop de camara; no bloquea nada.

La API consume este endpoint en /api/cameras/main/stream (proxy).
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8001

_lock  = threading.Lock()
_frame: bytes | None = None


def set_frame(jpeg_bytes: bytes) -> None:
    """Actualiza el frame actual. Lo llama camara.py via on_frame."""
    global _frame
    with _lock:
        _frame = jpeg_bytes


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/stream.mjpeg":
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        try:
            while True:
                with _lock:
                    frame = _frame
                if frame:
                    self.wfile.write(
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + frame
                        + b"\r\n"
                    )
                    self.wfile.flush()
                time.sleep(0.033)   # ~30 fps max
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass   # silencia un log por cada request


def start(host: str = "0.0.0.0", port: int = PORT) -> None:
    """Arranca el servidor MJPEG en un daemon thread. Llamar una sola vez al inicio."""
    # ThreadingHTTPServer: un hilo por cliente. Con HTTPServer (single-thread) el
    # stream MJPEG infinito del proxy bloqueaba cualquier otro request a :8001.
    server = ThreadingHTTPServer((host, port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[STREAM] MJPEG en http://localhost:{port}/stream.mjpeg")
