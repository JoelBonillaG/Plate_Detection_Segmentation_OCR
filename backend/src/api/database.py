"""
Conexion a PostgreSQL.

Expone `get_connection()` (context manager con filas como dict) que usan
`events_db.py` y los endpoints de la API. La URL sale de `config.py` (`.env`).
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .config import get_settings

# reintentos de CONEXION (no de la query): absorben un parpadeo del contenedor
# Postgres (p.ej. justo despues de `docker compose up` o un restart) sin perder
# el evento. Solo reintenta el connect; el cuerpo de la transaccion no se repite.
_REINTENTOS_CONEXION = 3
_ESPERA_BASE_S = 0.5


def _conectar_con_reintentos(url: str) -> psycopg.Connection:
    ultimo_error: Exception | None = None
    for intento in range(_REINTENTOS_CONEXION):
        try:
            return psycopg.connect(url, row_factory=dict_row)
        except psycopg.OperationalError as exc:
            ultimo_error = exc
            if intento < _REINTENTOS_CONEXION - 1:
                time.sleep(_ESPERA_BASE_S * (intento + 1))   # 0.5s, 1.0s
    raise ultimo_error  # type: ignore[misc]


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    settings = get_settings()
    connection = _conectar_con_reintentos(settings.database_url)
    # `with connection:` mantiene el commit/rollback + cierre de psycopg al salir.
    with connection:
        yield connection


def check_database_connection() -> dict:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  current_database() AS database,
                  current_user AS user_name,
                  NOW() AS server_time
                """
            )
            result = cursor.fetchone()
            return dict(result)


def fetch_pending_notifications(limit: int = 20) -> list[dict]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  n.id,
                  n.evento_id,
                  n.correo_destino,
                  n.tipo_notificacion,
                  n.asunto,
                  n.mensaje,
                  n.estado_envio,
                  e.placa_validada,
                  e.placa_ocr,
                  e.velocidad,
                  e.limite_velocidad
                FROM notificaciones n
                JOIN eventos e ON e.id = n.evento_id
                WHERE n.estado_envio = 'pendiente'
                ORDER BY n.created_at ASC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]


def mark_notification_sent(notification_id: str) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE notificaciones
                SET estado_envio = 'enviado',
                    fecha_envio = NOW(),
                    error_envio = NULL
                WHERE id = %s
                """,
                (notification_id,),
            )
        connection.commit()


def mark_notification_error(notification_id: str, error_message: str) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE notificaciones
                SET estado_envio = 'error',
                    error_envio = %s
                WHERE id = %s
                """,
                (error_message[:1000], notification_id),
            )
        connection.commit()
