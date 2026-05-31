/**
 * RealtimeContext — provides live WebSocket data to the whole app.
 *
 * Values exposed:
 *   connected       bool          WS connected to backend
 *   systemStatus    object        { system, camera, backend, fps, currentTime }
 *   latestEvent     object|null   Most recent detection from backend
 *   events          array         All events (mock + live, newest first)
 *   videoUrl        string        MJPEG endpoint URL
 */

import React, { createContext, useCallback, useContext, useEffect, useReducer, useRef } from "react";
import { wsService } from "../services/ws";

const API_BASE  = import.meta.env.VITE_API_URL ?? `http://${window.location.hostname}:8000`;
const VIDEO_URL = import.meta.env.VITE_VIDEO_URL ?? `${API_BASE}/api/cameras/main/stream`;

// ── helpers ──────────────────────────────────────────────────────────────────

// ruta relativa de storage -> URL absoluta servida por la API (/static). null si no hay.
const staticUrl = p => (p ? `${API_BASE}/static/${p}` : null);

// Postgres NUMERIC llega como string ("0.7743"); normaliza a number o null.
const num = v => (v === null || v === undefined || v === "" ? null : Number(v));

function mapBackendEvent(raw) {
  return {
    id:                 raw.id ?? `EVT-${Date.now()}`,
    db_id:              raw.db_id ?? raw.id,   // UUID real para llamadas PATCH
    plateOcr:           raw.placa_ocr,
    plateValidated:     raw.placa_validada ?? raw.placa_ocr,
    speed:              raw.velocidad,
    speedLimit:         raw.limite_velocidad,
    type:               raw.tipo_evento,
    reviewStatus:       raw.estado_revision,
    notificationStatus: raw.estado_notificacion,
    riskLevel:          raw.nivel_riesgo,
    suggestedPenaltyDays: raw.dias_sancion_sugeridos ?? 0,
    ocrConfidence:      num(raw.confianza_ocr),
    recurrenceCount:    raw.reincidencias ?? 0,
    dateTime:           raw.fecha_hora?.replace("T", " ").slice(0, 19) ?? new Date().toISOString().replace("T", " ").slice(0, 19),
    vehicle: {
      brand:      raw.vehiculo?.marca      ?? "—",
      model:      raw.vehiculo?.modelo     ?? "—",
      color:      raw.vehiculo?.color      ?? "—",
      ownerName:  raw.vehiculo?.propietario_nombre  ?? "—",
      ownerEmail: raw.vehiculo?.propietario_correo  ?? "—",
    },
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
      caracteresSegmentados: raw.vision?.caracteres_segmentados ?? 0,
      ocr:                   raw.vision?.resultado_ocr ?? raw.placa_ocr,
      // [{ ch, conf }] confianza real por caracter (softmax del OCR)
      ocrPerChar: (raw.vision?.ocr_por_caracter ?? []).map(c => ({
        ch: c.caracter, conf: num(c.confianza),
      })),
    },
    fuzzySystem: {
      speedExcess:         raw.fuzzy?.exceso_velocidad ?? 0,
      speedMembership:     raw.fuzzy?.pertenencia_velocidad
        ? Object.entries(raw.fuzzy.pertenencia_velocidad).sort(([,a],[,b]) => b - a)[0]?.[0] ?? "normal"
        : "normal",
      ocrMembership:       raw.fuzzy?.pertenencia_confianza_ocr
        ? Object.entries(raw.fuzzy.pertenencia_confianza_ocr).sort(([,a],[,b]) => b - a)[0]?.[0] ?? "alta"
        : "alta",
      recurrenceMembership: raw.fuzzy?.pertenencia_reincidencia
        ? Object.entries(raw.fuzzy.pertenencia_reincidencia).sort(([,a],[,b]) => b - a)[0]?.[0] ?? "normal"
        : "normal",
      risk:            raw.fuzzy?.nivel_riesgo     ?? raw.nivel_riesgo,
      suggestedPenalty: raw.fuzzy?.dias_sancion_sugeridos ? `${raw.fuzzy.dias_sancion_sugeridos} dias` : "sin sancion",
      activatedRules:  raw.fuzzy?.reglas_activadas ?? [],
      crispOutput:     raw.fuzzy?.salida_crisp ?? null,
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

  const value = { ...state, videoUrl: VIDEO_URL };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useRealtime() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useRealtime must be inside RealtimeProvider");
  return ctx;
}
