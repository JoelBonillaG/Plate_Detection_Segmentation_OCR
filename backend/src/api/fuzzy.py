"""
Motor de Inferencia Difusa (FIS) Mamdani — sanciones vehiculares UTA.

Diseño: Exceso de velocidad × Reincidencia → Severidad de sanción (0–100)
        → Días de suspensión (0–4) o revocación definitiva (conducta temeraria)

Límites:
    LIMITE_VELOCIDAD = 20 km/h   (zonas educativas, Art. 191 RLOTTTSV)
    UMBRAL_TEMERARIA = 50 km/h   (límite máximo urbano — compuerta crisp)

Ref: seccion_logica_difusa.md
"""
from __future__ import annotations

from dataclasses import dataclass, field

LIMITE_VELOCIDAD: float = 20.0
UMBRAL_TEMERARIA: float = 50.0

# ── Funciones de membresía ─────────────────────────────────────────────────────

def _trimf(x: float, a: float, b: float, c: float) -> float:
    """Función triangular: vértice en b, base [a, c]."""
    if x <= a or x >= c:
        return 0.0
    if x <= b:
        return (x - a) / (b - a) if b != a else 1.0
    return (c - x) / (c - b) if c != b else 1.0


def _trapmf(x: float, a: float, b: float, c: float, d: float) -> float:
    """Función trapezoidal: meseta [b, c], base [a, d]. Fronteras inclusivas."""
    if x < a or x > d:
        return 0.0
    if b <= x <= c:
        return 1.0
    if x < b:
        return (x - a) / (b - a) if b != a else 1.0
    return (d - x) / (d - c) if d != c else 1.0


def _eval(x: float, defn: tuple) -> float:
    kind, params = defn
    return _trimf(x, *params) if kind == "tri" else _trapmf(x, *params)


# ── Conjuntos difusos ──────────────────────────────────────────────────────────

# Exceso de velocidad — universo [0, 30] km/h
# Zona escolar/universitaria: limite 20, conduccion temeraria (expulsion) a 50 km/h
# -> el exceso UTIL es [0, 30]. Las funciones escalan a ese rango: a 20 km/h de
# limite, pasarse 14 km/h (ir a 34) YA es grave, no "moderado".
EXCESO: dict[str, tuple] = {
    # Conjuntos que se cruzan al ~0.5 (cobertura uniforme) -> salida del FIS monotona,
    # sin huecos que hundan el centroide. Picos ~3,8,14,20,26 sobre [0,30].
    "no_excess": ("trap", (0,  0,  2,  5 )),    # ~limite (20-25)
    "minor":     ("tri",  (2,  8,  14  )),      # leve (~28)
    "moderate":  ("tri",  (8,  14, 20  )),      # moderado (~34)
    "serious":   ("tri",  (14, 20, 26  )),      # grave (~40)
    "critical":  ("trap", (20, 26, 30, 30)),    # critico (~46-49, casi expulsion)
}

# Reincidencia — universo [0, 10] infracciones previas
# Conjuntos cruzados al ~0.5 (sin huecos) -> salida monotona tambien en reincidencia.
REINCI: dict[str, tuple] = {
    "clean":    ("trap", (0,   0,   1,   2.5)),
    "low":      ("tri",  (0,   2.5, 5    )),
    "moderate": ("tri",  (2.5, 5,   7.5  )),
    "high":     ("tri",  (5,   7.5, 10   )),
    "chronic":  ("trap", (7.5, 9,   10,  10 )),
}

# Severidad de la sanción — universo [0, 100]
SEVERIDAD: dict[str, tuple] = {
    "no_action":     ("trap", (0,  0,  5,  15 )),
    "warning":       ("tri",  (10, 20, 30  )),
    "low_susp":      ("tri",  (25, 40, 55  )),
    "medium_susp":   ("tri",  (50, 65, 80  )),
    "high_susp":     ("tri",  (75, 85, 95  )),
    "critical_susp": ("trap", (90, 96, 100, 100)),
}

# ── Base de reglas (5 exceso × 5 reincidencia = 25 reglas) ────────────────────
# Formato: (exceso_set, reincidencia_set, severidad_set)
RULES: list[tuple[str, str, str]] = [
    # R1–R5: Sin exceso (~20-23 km/h)
    ("no_excess", "clean",    "no_action"),
    ("no_excess", "low",      "no_action"),
    ("no_excess", "moderate", "no_action"),
    ("no_excess", "high",     "warning"),
    ("no_excess", "chronic",  "warning"),
    # R6–R10: Leve (~25 km/h) -> advertencia con historial limpio.
    ("minor",     "clean",    "warning"),
    ("minor",     "low",      "warning"),
    ("minor",     "moderate", "low_susp"),
    ("minor",     "high",     "low_susp"),
    ("minor",     "chronic",  "medium_susp"),
    # R11–R15: Moderado (~31 km/h) -> suspension inicial incluso con historial limpio.
    ("moderate",  "clean",    "low_susp"),
    ("moderate",  "low",      "low_susp"),
    ("moderate",  "moderate", "medium_susp"),
    ("moderate",  "high",     "medium_susp"),
    ("moderate",  "chronic",  "high_susp"),
    # R16–R20: Grave (~38 km/h) -> 2+ dias
    ("serious",   "clean",    "medium_susp"),
    ("serious",   "low",      "medium_susp"),
    ("serious",   "moderate", "high_susp"),
    ("serious",   "high",     "high_susp"),
    ("serious",   "chronic",  "critical_susp"),
    # R21–R25: Critico (~42-49 km/h) -> severidad alta con historial limpio y
    # severidad critica cuando existe reincidencia.
    ("critical",  "clean",    "high_susp"),
    ("critical",  "low",      "high_susp"),
    ("critical",  "moderate", "critical_susp"),
    ("critical",  "high",     "critical_susp"),
    ("critical",  "chronic",  "critical_susp"),
]

# ── Defuzzificación por centroide ──────────────────────────────────────────────

_Y_VALS = [i * 0.5 for i in range(201)]  # 0.0, 0.5, …, 100.0


def _defuzzify(activated: list[tuple[float, str]]) -> float:
    """Centroide sobre la unión Mamdani (max-min)."""
    if not activated:
        return 0.0
    num = den = 0.0
    for y in _Y_VALS:
        mu = max(min(alpha, _eval(y, SEVERIDAD[sev])) for alpha, sev in activated)
        num += y * mu
        den += mu
    return num / den if den > 1e-9 else 0.0


# ── Política de conversión severidad → días ────────────────────────────────────

def _severity_to_days(s: float) -> int:
    if s < 30: return 0
    if s < 53: return 1
    if s < 75: return 2
    if s < 91: return 3
    return 4


def _days_to_risk(days: int) -> str:
    return ("bajo", "medio", "alto", "critico", "critico")[min(days, 4)]


def _days_to_tipo(days: int, exceso: float) -> str:
    if exceso <= 0:  return "normal"
    if days == 0:    return "advertencia"
    if days <= 2:    return "infraccion"
    return "grave"


# ── Resultado ──────────────────────────────────────────────────────────────────

@dataclass
class FuzzyResult:
    tipo_evento: str             # "normal" | "advertencia" | "infraccion" | "grave"
    nivel_riesgo: str            # "bajo" | "medio" | "alto" | "critico"
    dias_sancion: int            # 0–4; -1 = revocación definitiva del acceso
    exceso: float                # km/h (positivo)
    es_temeraria: bool
    salida_crisp: float | None   # índice 0–100; None si temeraria o normal
    pertenencia_exceso: dict[str, float]
    pertenencia_reincidencia: dict[str, float]
    reglas_activadas: list[dict] = field(default_factory=list)


# ── Punto de entrada ───────────────────────────────────────────────────────────

def evaluar(velocidad: float, reincidencia: int) -> FuzzyResult:
    """Evalúa el FIS Mamdani completo para un evento vehicular."""
    r = max(0, min(10, int(reincidencia)))
    exceso_raw = velocidad - LIMITE_VELOCIDAD
    exceso_clamped = max(0.0, min(30.0, exceso_raw))

    mem_e = {k: round(_eval(exceso_clamped, v), 4) for k, v in EXCESO.items()}
    mem_r = {k: round(_eval(float(r), v),        4) for k, v in REINCI.items()}

    # Tramo 1: sin infracción (velocidad ≤ límite)
    if velocidad <= LIMITE_VELOCIDAD:
        return FuzzyResult(
            tipo_evento="normal", nivel_riesgo="bajo", dias_sancion=0,
            exceso=0.0, es_temeraria=False, salida_crisp=0.0,
            pertenencia_exceso=mem_e, pertenencia_reincidencia=mem_r,
        )

    # Tramo 3: conducta temeraria — compuerta determinista
    if velocidad >= UMBRAL_TEMERARIA:
        return FuzzyResult(
            tipo_evento="grave", nivel_riesgo="critico", dias_sancion=-1,
            exceso=round(exceso_raw, 2), es_temeraria=True, salida_crisp=None,
            pertenencia_exceso=mem_e, pertenencia_reincidencia=mem_r,
        )

    # Tramo 2: evaluación FIS Mamdani (20 < velocidad < 50)
    activated: list[tuple[float, str]] = []
    rules_out: list[dict] = []

    for idx, (exc_set, rec_set, sev_set) in enumerate(RULES):
        alpha = min(mem_e[exc_set], mem_r[rec_set])
        if alpha > 1e-4:
            activated.append((alpha, sev_set))
            rules_out.append({
                "id": f"R{idx + 1}",
                "exceso_set": exc_set,
                "reincidencia_set": rec_set,
                "severidad_set": sev_set,
                "activacion": round(alpha, 4),
            })

    rules_out.sort(key=lambda x: x["activacion"], reverse=True)

    crisp = round(_defuzzify(activated), 2)
    dias  = _severity_to_days(crisp)
    tipo  = _days_to_tipo(dias, exceso_raw)
    riesgo = _days_to_risk(dias)

    return FuzzyResult(
        tipo_evento=tipo, nivel_riesgo=riesgo, dias_sancion=dias,
        exceso=round(exceso_raw, 2), es_temeraria=False, salida_crisp=crisp,
        pertenencia_exceso=mem_e, pertenencia_reincidencia=mem_r,
        reglas_activadas=rules_out,
    )
