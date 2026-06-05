export const systemStatus = {
  system: "Sistema activo",
  camera: "Camara principal",
  backend: "Backend conectado",
  fps: 24.6,
  currentTime: "11:42:15",
};

export const stats = {
  detectedToday: 128,
  violationsToday: 15,
  averageSpeed: 28,
  pendingReview: 3,
};

export const events = [
  // ── Infracción moderada con reincidencia ────────────────────────────────────
  {
    id: "EVT-00018",
    db_id: "00000000-0000-0000-0000-000000000018",
    plateOcr: "ABC-1234",
    plateValidated: "ABC-1234",
    speed: 35,
    speedLimit: 20,
    type: "infraccion",
    reviewStatus: "pendiente",
    notificationStatus: "pendiente",
    riskLevel: "alto",
    suggestedPenaltyDays: 2,
    ocrConfidence: 0.94,
    recurrenceCount: 2,
    dateTime: "2026-05-30 11:42:10",
    vehicle: {},
    images: {
      frame: "/mock/principal.png",
      plate: "/mock/placa_sola.png",
    },
    computerVision: {
      vehicleDetection: { label: "Vehiculo", confidence: 0.97, bbox: "x:184, y:84, w:610, h:342" },
      plateDetection:   { label: "Placa",    confidence: 0.95, bbox: "x:408, y:306, w:132, h:54" },
      rectification: "Enderezada a 300×100 px",
      filters:       "Denoise adaptativo + normalización de iluminación",
      segmentation:  "7 caracteres detectados",
      ocr: "ABC-1234",
    },
    fuzzySystem: {
      speedExcess: 15,
      esTemeraria: false,
      crispOutput: 56.4,
      suggestedPenaltyDays: 2,
      risk: "alto",
      pertenenciaExceso: {
        no_excess: 0.0, minor: 0.0, moderate: 0.625, serious: 0.0, critical: 0.0,
      },
      pertenenciaReincidencia: {
        clean: 0.0, low: 0.5, moderate: 0.5, high: 0.0, chronic: 0.0,
      },
      activatedRules: [
        { id: "R13", exceso_set: "moderate", reincidencia_set: "moderate", severidad_set: "medium_susp", activacion: 0.5 },
        { id: "R12", exceso_set: "moderate", reincidencia_set: "low",      severidad_set: "low_susp",    activacion: 0.5 },
      ],
    },
    audit: [],
  },

  // ── Conductor normal (sin infracción) ───────────────────────────────────────
  {
    id: "EVT-00017",
    db_id: "00000000-0000-0000-0000-000000000017",
    plateOcr: "TBC-8821",
    plateValidated: "TBC-8821",
    speed: 16,
    speedLimit: 20,
    type: "normal",
    reviewStatus: "automatica",
    notificationStatus: "enviado",
    riskLevel: "bajo",
    suggestedPenaltyDays: 0,
    ocrConfidence: 0.91,
    recurrenceCount: 0,
    dateTime: "2026-05-30 11:41:33",
    vehicle: {},
    images: { frame: "/mock/principal.png", plate: "/mock/placa_sola.png" },
    computerVision: {
      vehicleDetection: { label: "Vehiculo", confidence: 0.96, bbox: "x:198, y:92, w:584, h:330" },
      plateDetection:   { label: "Placa",    confidence: 0.92, bbox: "x:412, y:312, w:126, h:48" },
      rectification: "Enderezada a 300×100 px",
      filters: "Imagen limpia para segmentación",
      segmentation: "7 caracteres detectados",
      ocr: "TBC-8821",
    },
    fuzzySystem: {
      speedExcess: 0,
      esTemeraria: false,
      crispOutput: 0.0,
      suggestedPenaltyDays: 0,
      risk: "bajo",
      pertenenciaExceso: {
        no_excess: 1.0, minor: 0.0, moderate: 0.0, serious: 0.0, critical: 0.0,
      },
      pertenenciaReincidencia: {
        clean: 1.0, low: 0.0, moderate: 0.0, high: 0.0, chronic: 0.0,
      },
      activatedRules: [],
    },
    audit: [],
  },

  // ── Advertencia leve (FIS → 0 días) ────────────────────────────────────────
  {
    id: "EVT-00016",
    db_id: "00000000-0000-0000-0000-000000000016",
    plateOcr: "PDA-9912",
    plateValidated: "PDA-9912",
    speed: 24,
    speedLimit: 20,
    type: "advertencia",
    reviewStatus: "automatica",
    notificationStatus: "enviado",
    riskLevel: "bajo",
    suggestedPenaltyDays: 0,
    ocrConfidence: 0.89,
    recurrenceCount: 1,
    dateTime: "2026-05-30 11:41:02",
    vehicle: {},
    images: { frame: "/mock/principal.png", plate: "/mock/placa_sola.png" },
    computerVision: {
      vehicleDetection: { label: "Vehiculo", confidence: 0.95, bbox: "x:180, y:90, w:600, h:344" },
      plateDetection:   { label: "Placa",    confidence: 0.90, bbox: "x:406, y:309, w:130, h:50" },
      rectification: "Enderezada a 300×100 px",
      filters: "Normalización aplicada",
      segmentation: "7 caracteres detectados",
      ocr: "PDA-9912",
    },
    fuzzySystem: {
      speedExcess: 4,
      esTemeraria: false,
      crispOutput: 20.0,
      suggestedPenaltyDays: 0,
      risk: "bajo",
      pertenenciaExceso: {
        no_excess: 0.0, minor: 1.0, moderate: 0.0, serious: 0.0, critical: 0.0,
      },
      pertenenciaReincidencia: {
        clean: 0.0, low: 0.8333, moderate: 0.0, high: 0.0, chronic: 0.0,
      },
      activatedRules: [
        { id: "R6", exceso_set: "minor", reincidencia_set: "clean", severidad_set: "warning",  activacion: 0.1667 },
        { id: "R7", exceso_set: "minor", reincidencia_set: "low",   severidad_set: "warning",  activacion: 0.8333 },
      ],
    },
    audit: [],
  },

  // ── Conducta temeraria (≥ 50 km/h) ─────────────────────────────────────────
  {
    id: "EVT-00015",
    db_id: "00000000-0000-0000-0000-000000000015",
    plateOcr: "XYZ-1111",
    plateValidated: "XYZ-1111",
    speed: 63,
    speedLimit: 20,
    type: "grave",
    reviewStatus: "pendiente",
    notificationStatus: "pendiente",
    riskLevel: "critico",
    suggestedPenaltyDays: 0,
    ocrConfidence: 0.96,
    recurrenceCount: 4,
    dateTime: "2026-05-30 11:40:41",
    vehicle: {},
    images: { frame: "/mock/principal.png", plate: "/mock/placa_sola.png" },
    computerVision: {
      vehicleDetection: { label: "Vehiculo", confidence: 0.98, bbox: "x:175, y:82, w:620, h:350" },
      plateDetection:   { label: "Placa",    confidence: 0.96, bbox: "x:410, y:305, w:138, h:52" },
      rectification: "Enderezada a 300×100 px",
      filters: "Denoise fuerte por movimiento",
      segmentation: "7 caracteres detectados",
      ocr: "XYZ-1111",
    },
    fuzzySystem: {
      speedExcess: 43,
      esTemeraria: true,
      crispOutput: null,
      suggestedPenaltyDays: 0,
      risk: "critico",
      pertenenciaExceso: {
        no_excess: 0.0, minor: 0.0, moderate: 0.0, serious: 0.0, critical: 1.0,
      },
      pertenenciaReincidencia: {
        clean: 0.0, low: 0.0, moderate: 0.0, high: 0.2, chronic: 0.8,
      },
      activatedRules: [],
    },
    audit: [],
  },
];

export const notifications = [
  { id: "NOT-041", eventId: "EVT-00017", type: "felicitacion", recipient: "m.solis@uni.edu",   status: "enviado",  subject: "Conducción responsable en campus" },
  { id: "NOT-040", eventId: "EVT-00018", type: "infraccion",   recipient: "c.andrade@uni.edu", status: "pendiente", subject: "Revisión pendiente por exceso de velocidad" },
  { id: "NOT-039", eventId: "EVT-00015", type: "infraccion",   recipient: "a.mora@uni.edu",    status: "pendiente", subject: "Conducta temeraria — revocación de acceso" },
];
