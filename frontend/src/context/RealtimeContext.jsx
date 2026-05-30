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
import { events as MOCK_EVENTS, systemStatus as MOCK_STATUS } from "../data/mockData";

const VIDEO_URL = import.meta.env.VITE_VIDEO_URL ?? `http://${window.location.hostname}:8000/video_feed`;

// ── helpers ──────────────────────────────────────────────────────────────────

function mapBackendEvent(raw) {
  return {
    id:                 raw.id ?? `EVT-${Date.now()}`,
    plateOcr:           raw.placa_ocr,
    plateValidated:     raw.placa_validada ?? raw.placa_ocr,
    speed:              raw.velocidad,
    speedLimit:         raw.limite_velocidad,
    type:               raw.tipo_evento,
    reviewStatus:       raw.estado_revision,
    notificationStatus: raw.estado_notificacion,
    riskLevel:          raw.nivel_riesgo,
    suggestedPenaltyDays: raw.dias_sancion_sugeridos ?? 0,
    ocrConfidence:      raw.confianza_ocr,
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
      // backend serves static files under /static/
      frame: raw.imagen_frame ? `http://${window.location.hostname}:8000/static/${raw.imagen_frame}` : "/mock/principal.png",
      plate: raw.imagen_placa ? `http://${window.location.hostname}:8000/static/${raw.imagen_placa}` : "/mock/placa_sola.png",
    },
    computerVision: {
      vehicleDetection: {
        confidence: raw.vision?.confianza_vehiculo ?? 0.95,
        bbox: raw.vision?.bbox_vehiculo
          ? `x:${raw.vision.bbox_vehiculo.x}, y:${raw.vision.bbox_vehiculo.y}, w:${raw.vision.bbox_vehiculo.w}, h:${raw.vision.bbox_vehiculo.h}`
          : "—",
      },
      plateDetection: {
        confidence: raw.vision?.confianza_placa ?? 0.92,
        bbox: raw.vision?.bbox_placa
          ? `x:${raw.vision.bbox_placa.x}, y:${raw.vision.bbox_placa.y}, w:${raw.vision.bbox_placa.w}, h:${raw.vision.bbox_placa.h}`
          : "—",
      },
      rectification: raw.vision?.ruta_placa_enderezada ?? "—",
      filters:       raw.vision?.metadata?.filtros ?? "—",
      segmentation:  raw.vision?.caracteres_segmentados ? `${raw.vision.caracteres_segmentados} caracteres` : "—",
      ocr:           raw.vision?.resultado_ocr ?? raw.placa_ocr,
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
  systemStatus: MOCK_STATUS,
  latestEvent:  MOCK_EVENTS[0],
  events:       MOCK_EVENTS,
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
