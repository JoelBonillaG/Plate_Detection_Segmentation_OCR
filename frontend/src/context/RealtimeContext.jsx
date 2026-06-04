/**
 * RealtimeContext — provides live WebSocket data to the whole app.
 *
 * Values exposed:
 *   connected       bool          WS connected to backend
 *   systemStatus    object        { system, camera, backend, fps, currentTime }
 *   latestEvent     object|null   Most recent detection from backend
 *   events          array         All events (mock + live, newest first)
 *   videoUrl        string        WebSocket de video (/ws/video) — frames JPEG a canvas
 */

import React, { createContext, useCallback, useContext, useEffect, useReducer, useRef } from "react";
import { wsService } from "../services/ws";

const API_BASE  = import.meta.env.VITE_API_URL ?? `http://${window.location.hostname}:8000`;
// Video en vivo por WebSocket binario (frames JPEG -> <canvas>). Default: /ws/video.
const WS_BASE       = import.meta.env.VITE_WS_URL ?? `ws://${window.location.hostname}:8000/ws`;
const VIDEO_WS_URL  = import.meta.env.VITE_VIDEO_WS_URL ?? `${WS_BASE}/video`;

// ── helpers ──────────────────────────────────────────────────────────────────

// ruta relativa de storage -> URL absoluta servida por la API (/static). null si no hay.
const staticUrl = p => (p ? `${API_BASE}/static/${p}` : null);

// Postgres NUMERIC llega como string ("0.7743"); normaliza a number o null.
const num = v => (v === null || v === undefined || v === "" ? null : Number(v));
// velocidad cruda llega con muchos decimales (ej. 1.4535666218035004) -> 1 decimal.
const round1 = v => { const n = num(v); return n === null ? null : Math.round(n * 10) / 10; };

function mapBackendEvent(raw) {
  return {
    id:                 raw.id ?? `EVT-${Date.now()}`,
    db_id:              raw.db_id ?? raw.id,   // UUID real para llamadas PATCH
    plateOcr:           raw.placa_ocr,
    plateValidated:     raw.placa_validada ?? raw.placa_ocr,
    speed:              round1(raw.velocidad),
    speedLimit:         raw.limite_velocidad,
    type:               raw.tipo_evento,
    reviewStatus:       raw.estado_revision,
    notificationStatus: raw.estado_notificacion,
    riskLevel:          raw.nivel_riesgo,
    suggestedPenaltyDays: raw.dias_sancion_sugeridos ?? 0,
    ocrConfidence:      num(raw.confianza_ocr),
    recurrenceCount:    raw.reincidencias ?? 0,
    dateTime:           raw.fecha_hora?.replace("T", " ").slice(0, 19) ?? new Date().toISOString().replace("T", " ").slice(0, 19),
    images: {
      // backend sirve archivos estaticos bajo /static/. null = no disponible.
      frame:         staticUrl(raw.imagen_frame),
      plate:         staticUrl(raw.imagen_placa),
      plateDetected: staticUrl(raw.vision?.ruta_placa_detectada),
      plateStraight: staticUrl(raw.vision?.ruta_placa_enderezada) ?? staticUrl(raw.imagen_placa),
      plateFiltered: staticUrl(raw.vision?.ruta_placa_filtrada),
      segmentation:  staticUrl(raw.vision?.ruta_segmentacion),
    },
    computerVision: {
      vehicleDetection: {
        confidence: num(raw.vision?.confianza_vehiculo),
        bbox: raw.vision?.bbox_vehiculo
          ? `x:${raw.vision.bbox_vehiculo.x}, y:${raw.vision.bbox_vehiculo.y}, w:${raw.vision.bbox_vehiculo.w}, h:${raw.vision.bbox_vehiculo.h}`
          : "—",
      },
      plateDetection: {
        confidence: num(raw.vision?.confianza_placa),
        bbox: raw.vision?.bbox_placa
          ? `x:${raw.vision.bbox_placa.x}, y:${raw.vision.bbox_placa.y}, w:${raw.vision.bbox_placa.w}, h:${raw.vision.bbox_placa.h}`
          : "—",
      },
      usoFiltros:            raw.vision?.metadata?.filtros === "activos",
      // ausente (eventos viejos) -> se asume aplicado; "omitido" -> no se enderezo
      usoEnderezado:         raw.vision?.metadata?.enderezado !== "omitido",
      caracteresSegmentados: raw.vision?.caracteres_segmentados ?? 0,
      ocr:                   raw.vision?.resultado_ocr ?? raw.placa_ocr,
      // [{ ch, conf, crop }] confianza real por caracter (softmax del OCR) + crop del char
      ocrPerChar: (raw.vision?.ocr_por_caracter ?? []).map(c => ({
        ch: c.caracter, conf: num(c.confianza), crop: staticUrl(c.ruta),
      })),
    },
    fuzzySystem: {
      speedExcess:            round1(raw.fuzzy?.exceso_velocidad) ?? 0,
      risk:                   raw.fuzzy?.nivel_riesgo ?? raw.nivel_riesgo,
      suggestedPenaltyDays:   raw.fuzzy?.dias_sancion_sugeridos ?? 0,
      activatedRules:         raw.fuzzy?.reglas_activadas ?? [],
      crispOutput:            raw.fuzzy?.salida_crisp ?? null,
      esTemeraria:            raw.fuzzy?.es_temeraria ?? (raw.velocidad >= 50),
      pertenenciaExceso:      raw.fuzzy?.pertenencia_velocidad ?? {},
      pertenenciaReincidencia: raw.fuzzy?.pertenencia_reincidencia ?? {},
    },
    audit: [],
  };
}

// ── reducer ───────────────────────────────────────────────────────────────────

const INIT = {
  connected: false,
  systemStatus: { system: "Conectando…", camera: "—", backend: "—", fps: 0, currentTime: "—" },
  latestEvent:  null,
  events:       [],   // sin mocks: se llena con eventos reales del WebSocket
};

function reducer(state, action) {
  switch (action.type) {
    case "CONNECTION":
      return { ...state, connected: action.connected };

    case "STATUS":
      return {
        ...state,
        systemStatus: {
          system:      action.data.camera_connected ? "Sistema activo" : "Sin cámara",
          camera:      "Cámara principal",
          backend:     action.data.backend_connected ? "Backend conectado" : "Desconectado",
          fps:         action.data.fps ?? state.systemStatus.fps,
          currentTime: action.data.current_time ?? state.systemStatus.currentTime,
        },
      };

    case "HYDRATE": {
      // historial inicial desde GET /api/events (eventos reales ya persistidos)
      const events = action.events.map(mapBackendEvent);
      return { ...state, events, latestEvent: events[0] ?? null };
    }

    case "EVENT": {
      const ev = mapBackendEvent(action.data);
      const withoutDuplicate = state.events.filter(e => e.id !== ev.id);
      return {
        ...state,
        latestEvent: ev,
        events: [ev, ...withoutDuplicate],
      };
    }

    default:
      return state;
  }
}

// ── context ───────────────────────────────────────────────────────────────────

const Ctx = createContext(null);

export function RealtimeProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, INIT);

  // historial inicial: consume GET /api/events una vez al montar (eventos reales).
  useEffect(() => {
    let vivo = true;
    fetch(`${API_BASE}/api/events?limit=50`)
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(data => {
        // el endpoint devuelve un array plano; tolera tambien {events:[...]}
        const list = Array.isArray(data) ? data : data?.events;
        if (vivo && Array.isArray(list)) {
          dispatch({ type: "HYDRATE", events: list });
        }
      })
      .catch(() => { /* API caida -> queda vacio hasta que llegue un evento por WS */ });
    return () => { vivo = false; };
  }, []);

  useEffect(() => {
    wsService.connect();

    const unsubs = [
      wsService.on("connection", ({ connected }) =>
        dispatch({ type: "CONNECTION", connected })
      ),
      wsService.on("status", data =>
        dispatch({ type: "STATUS", data })
      ),
      wsService.on("event", data =>
        dispatch({ type: "EVENT", data })
      ),
    ];

    return () => {
      unsubs.forEach(fn => fn());
      // Keep WS alive for the whole session — do NOT disconnect here
    };
  }, []);

  const value = { ...state, videoUrl: VIDEO_WS_URL };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useRealtime() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useRealtime must be inside RealtimeProvider");
  return ctx;
}
