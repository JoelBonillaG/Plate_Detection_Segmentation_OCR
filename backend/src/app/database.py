from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .config import get_settings


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    settings = get_settings()
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
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
