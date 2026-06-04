"""
DB queries para eventos — insert + fetch con joins a visión y difuso.
"""

from __future__ import annotations

import uuid
from typing import Any

from .database import get_connection


# ── Insert ────────────────────────────────────────────────────────────────────

def insert_evento(
    *,
    placa_ocr: str,
    placa_validada: str | None,
    velocidad: float,
    limite_velocidad: float,
    tipo_evento: str,
    estado_revision: str,
    estado_notificacion: str,
    nivel_riesgo: str,
    dias_sancion_sugeridos: int,
    confianza_ocr: float,
    reincidencias: int,
    imagen_frame: str,
    imagen_placa: str,
    observacion_admin: str | None = None,
) -> str:
    """Inserta un evento y devuelve su UUID."""
    evento_id = str(uuid.uuid4())
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO eventos (
                    id, placa_ocr, placa_validada,
                    velocidad, limite_velocidad, tipo_evento, estado_revision,
                    estado_notificacion, nivel_riesgo, dias_sancion_sugeridos,
                    confianza_ocr, reincidencias, imagen_frame, imagen_placa,
                    observacion_admin
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s
                )
                """,
                (
                    evento_id, placa_ocr.upper(), (placa_validada or placa_ocr).upper(),
                    velocidad, limite_velocidad, tipo_evento, estado_revision,
                    estado_notificacion, nivel_riesgo, dias_sancion_sugeridos,
                    confianza_ocr, reincidencias, imagen_frame, imagen_placa,
                    observacion_admin,
                ),
            )
        conn.commit()
    return evento_id


def insert_vision(
    *,
    evento_id: str,
    vehiculo_detectado: bool = True,
    confianza_vehiculo: float | None = None,
    bbox_vehiculo: dict | None = None,
    placa_detectada: bool = True,
    confianza_placa: float | None = None,
    bbox_placa: dict | None = None,
    ruta_placa_detectada: str | None = None,
    ruta_placa_enderezada: str | None = None,
    ruta_placa_filtrada: str | None = None,
    ruta_segmentacion: str | None = None,
    caracteres_segmentados: int | None = None,
    resultado_ocr: str | None = None,
    confianza_ocr: float | None = None,
    metadata: dict | None = None,
) -> None:
    import json
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO evento_vision_computadora (
                    evento_id, vehiculo_detectado, confianza_vehiculo, bbox_vehiculo,
                    placa_detectada, confianza_placa, bbox_placa,
                    ruta_placa_detectada, ruta_placa_enderezada, ruta_placa_filtrada,
                    ruta_segmentacion,
                    caracteres_segmentados, resultado_ocr, confianza_ocr, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (evento_id) DO NOTHING
                """,
                (
                    evento_id, vehiculo_detectado, confianza_vehiculo,
                    json.dumps(bbox_vehiculo) if bbox_vehiculo else None,
                    placa_detectada, confianza_placa,
                    json.dumps(bbox_placa) if bbox_placa else None,
                    ruta_placa_detectada, ruta_placa_enderezada, ruta_placa_filtrada,
                    ruta_segmentacion,
                    caracteres_segmentados, resultado_ocr, confianza_ocr,
                    json.dumps(metadata or {}),
                ),
            )
        conn.commit()


def insert_difuso(
    *,
    evento_id: str,
    exceso_velocidad: float,
    pertenencia_velocidad: dict,
    pertenencia_reincidencia: dict,
    pertenencia_confianza_ocr: dict,
    nivel_riesgo: str,
    dias_sancion_sugeridos: int,
    reglas_activadas: list[str],
    salida_crisp: float | None = None,
) -> None:
    import json
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO evento_sistema_difuso (
                    evento_id, exceso_velocidad,
                    pertenencia_velocidad, pertenencia_reincidencia, pertenencia_confianza_ocr,
                    nivel_riesgo, dias_sancion_sugeridos, reglas_activadas, salida_crisp
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (evento_id) DO NOTHING
                """,
                (
                    evento_id, exceso_velocidad,
                    json.dumps(pertenencia_velocidad),
                    json.dumps(pertenencia_reincidencia),
                    json.dumps(pertenencia_confianza_ocr),
                    nivel_riesgo, dias_sancion_sugeridos,
                    json.dumps(reglas_activadas),
                    salida_crisp,
                ),
            )
        conn.commit()


def count_reincidencias(placa: str) -> int:
    """Cuenta infracciones/graves previas del vehículo."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS n FROM eventos
                WHERE placa_validada = %s
                  AND tipo_evento IN ('infraccion', 'grave')
                """,
                (placa.upper(),),
            )
            row = cur.fetchone()
            return int(row["n"]) if row else 0


# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_eventos(limit: int = 50, offset: int = 0) -> list[dict]:
    """Devuelve eventos con joins a vehículo, visión y difuso."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    e.id, e.placa_ocr, e.placa_validada,
                    e.velocidad, e.limite_velocidad,
                    e.tipo_evento, e.estado_revision, e.estado_notificacion,
                    e.nivel_riesgo, e.dias_sancion_sugeridos,
                    e.confianza_ocr, e.reincidencias,
                    e.imagen_frame, e.imagen_placa,
                    e.fecha_hora, e.observacion_admin,

                    vis.vehiculo_detectado, vis.confianza_vehiculo,
                    vis.bbox_vehiculo, vis.placa_detectada,
                    vis.confianza_placa, vis.bbox_placa,
                    vis.ruta_placa_detectada,
                    vis.ruta_placa_enderezada, vis.ruta_placa_filtrada,
                    vis.ruta_segmentacion,
                    vis.caracteres_segmentados, vis.resultado_ocr,
                    vis.confianza_ocr AS vision_confianza_ocr,
                    vis.metadata AS vision_metadata,

                    d.exceso_velocidad,
                    d.pertenencia_velocidad, d.pertenencia_reincidencia,
                    d.pertenencia_confianza_ocr, d.nivel_riesgo AS fuzzy_riesgo,
                    d.dias_sancion_sugeridos AS fuzzy_dias,
                    d.reglas_activadas, d.salida_crisp

                FROM eventos e
                LEFT JOIN evento_vision_computadora vis ON vis.evento_id = e.id
                LEFT JOIN evento_sistema_difuso     d   ON d.evento_id   = e.id
                ORDER BY e.fecha_hora DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return [dict(row) for row in cur.fetchall()]


def fetch_evento(evento_id: str) -> dict | None:
    rows = fetch_eventos(limit=1, offset=0)
    # Single fetch by id
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    e.id, e.placa_ocr, e.placa_validada,
                    e.velocidad, e.limite_velocidad,
                    e.tipo_evento, e.estado_revision, e.estado_notificacion,
                    e.nivel_riesgo, e.dias_sancion_sugeridos,
                    e.confianza_ocr, e.reincidencias,
                    e.imagen_frame, e.imagen_placa,
                    e.fecha_hora, e.observacion_admin,
                    vis.confianza_vehiculo, vis.bbox_vehiculo,
                    vis.confianza_placa, vis.bbox_placa,
                    vis.ruta_placa_detectada, vis.ruta_placa_enderezada,
                    vis.ruta_placa_filtrada, vis.ruta_segmentacion,
                    vis.caracteres_segmentados,
                    vis.resultado_ocr, vis.confianza_ocr AS vision_confianza_ocr,
                    vis.metadata AS vision_metadata,
                    d.exceso_velocidad, d.pertenencia_velocidad,
                    d.pertenencia_reincidencia, d.pertenencia_confianza_ocr,
                    d.nivel_riesgo AS fuzzy_riesgo, d.dias_sancion_sugeridos AS fuzzy_dias,
                    d.reglas_activadas, d.salida_crisp
                FROM eventos e
                LEFT JOIN evento_vision_computadora vis ON vis.evento_id = e.id
                LEFT JOIN evento_sistema_difuso d ON d.evento_id = e.id
                WHERE e.id = %s
                """,
                (evento_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def approve_evento(evento_id: str, placa_corregida: str | None, motivo: str | None) -> None:
    """Aprueba la sanción: actualiza estado, crea notificación y encola envío."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Actualizar evento
            if placa_corregida:
                cur.execute(
                    "UPDATE eventos SET estado_revision='aprobado', placa_validada=%s, revisado_at=NOW(), updated_at=NOW() WHERE id=%s",
                    (placa_corregida.upper(), evento_id),
                )
            else:
                cur.execute(
                    "UPDATE eventos SET estado_revision='aprobado', revisado_at=NOW(), updated_at=NOW() WHERE id=%s",
                    (evento_id,),
                )

            # Obtener datos para la notificación al ingeniero
            cur.execute(
                """
                SELECT e.placa_validada, e.placa_ocr, e.velocidad, e.limite_velocidad,
                       e.dias_sancion_sugeridos, e.tipo_evento, e.nivel_riesgo,
                       e.confianza_ocr, e.reincidencias,
                       vis.confianza_vehiculo, vis.confianza_placa,
                       vis.caracteres_segmentados, vis.metadata AS vision_metadata,
                       d.exceso_velocidad, d.reglas_activadas, d.salida_crisp,
                       d.pertenencia_velocidad, d.pertenencia_reincidencia,
                       d.nivel_riesgo AS fuzzy_riesgo, d.dias_sancion_sugeridos AS fuzzy_dias
                FROM eventos e
                LEFT JOIN evento_vision_computadora vis ON vis.evento_id = e.id
                LEFT JOIN evento_sistema_difuso d ON d.evento_id = e.id
                WHERE e.id = %s
                """,
                (evento_id,),
            )
            ev = cur.fetchone()
            if ev:
                from .config import get_settings
                engineer_email = get_settings().engineer_email
                placa  = ev.get("placa_validada") or ev.get("placa_ocr")
                asunto = f"[Monitoreo UTA] Sanción aprobada — Placa {placa}"
                from .mailer import build_detection_body
                ocr_chars = (ev.get("vision_metadata") or {}).get("ocr_por_caracter", [])
                data_correo = {
                    **dict(ev),
                    "vision": {
                        "confianza_vehiculo": ev.get("confianza_vehiculo"),
                        "confianza_placa":    ev.get("confianza_placa"),
                        "caracteres_segmentados": ev.get("caracteres_segmentados"),
                        "ocr_por_caracter":   ocr_chars,
                    },
                    "fuzzy": {
                        "es_temeraria":           float(ev.get("velocidad", 0)) >= 50,
                        "salida_crisp":           ev.get("salida_crisp"),
                        "reglas_activadas":       ev.get("reglas_activadas") or [],
                        "pertenencia_velocidad":  ev.get("pertenencia_velocidad") or {},
                        "pertenencia_reincidencia": ev.get("pertenencia_reincidencia") or {},
                        "nivel_riesgo":           ev.get("fuzzy_riesgo"),
                        "dias_sancion_sugeridos": ev.get("fuzzy_dias"),
                    },
                }
                mensaje = build_detection_body(data_correo)
                if motivo:
                    mensaje += f"\nObservación del operador: {motivo}\n"
                cur.execute(
                    """
                    INSERT INTO notificaciones (evento_id, correo_destino, tipo_notificacion, asunto, mensaje)
                    VALUES (%s, %s, 'infraccion', %s, %s)
                    """,
                    (evento_id, engineer_email, asunto, mensaje),
                )
        conn.commit()


def reject_evento(evento_id: str, motivo: str | None) -> None:
    """Rechaza el evento — solo actualiza estado."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE eventos SET estado_revision='rechazado', observacion_admin=%s, revisado_at=NOW(), updated_at=NOW() WHERE id=%s",
                (motivo, evento_id),
            )
        conn.commit()


def _row_to_payload(row: dict) -> dict[str, Any]:
    """Convierte una fila de DB al formato EventPayload que el frontend espera."""
    raw_id = str(row["id"])
    display_id = f"EVT-{raw_id.replace('-','').upper()[:8]}"
    return {
        "id":     display_id,
        "db_id":  raw_id,          # UUID real, para llamadas API
        "placa_ocr":  row["placa_ocr"],
        "placa_validada": row["placa_validada"],
        "velocidad":  float(row["velocidad"]),
        "limite_velocidad": float(row["limite_velocidad"]),
        "tipo_evento": row["tipo_evento"],
        "estado_revision": row["estado_revision"],
        "estado_notificacion": row["estado_notificacion"],
        "nivel_riesgo": row["nivel_riesgo"],
        "dias_sancion_sugeridos": row["dias_sancion_sugeridos"],
        "confianza_ocr": float(row["confianza_ocr"]),
        "reincidencias": row["reincidencias"],
        "imagen_frame": row["imagen_frame"],
        "imagen_placa": row["imagen_placa"],
        "fecha_hora": row["fecha_hora"].isoformat() if row.get("fecha_hora") else None,
        "observacion_admin": row.get("observacion_admin"),
        "vision": {
            "confianza_vehiculo": row.get("confianza_vehiculo"),
            "bbox_vehiculo": row.get("bbox_vehiculo"),
            "confianza_placa": row.get("confianza_placa"),
            "bbox_placa": row.get("bbox_placa"),
            "ruta_placa_detectada": row.get("ruta_placa_detectada"),
            "ruta_placa_enderezada": row.get("ruta_placa_enderezada"),
            "ruta_placa_filtrada": row.get("ruta_placa_filtrada"),
            "ruta_segmentacion": row.get("ruta_segmentacion"),
            "caracteres_segmentados": row.get("caracteres_segmentados"),
            "resultado_ocr": row.get("resultado_ocr"),
            "confianza_ocr": row.get("vision_confianza_ocr"),
            "ocr_por_caracter": (row.get("vision_metadata") or {}).get("ocr_por_caracter", []),
            "metadata": row.get("vision_metadata") or {},
        },
        "fuzzy": {
            "exceso_velocidad": float(row["exceso_velocidad"]) if row.get("exceso_velocidad") is not None else 0,
            "pertenencia_velocidad": row.get("pertenencia_velocidad") or {},
            "pertenencia_reincidencia": row.get("pertenencia_reincidencia") or {},
            "pertenencia_confianza_ocr": row.get("pertenencia_confianza_ocr") or {},
            "nivel_riesgo": row.get("fuzzy_riesgo"),
            "dias_sancion_sugeridos": row.get("fuzzy_dias"),
            "reglas_activadas": row.get("reglas_activadas") or [],
            "salida_crisp": float(row["salida_crisp"]) if row.get("salida_crisp") is not None else None,
            "es_temeraria": float(row.get("velocidad") or 0) >= 50.0,
        },
    }
