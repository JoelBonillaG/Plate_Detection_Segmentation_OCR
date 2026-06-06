import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, ArrowLeft, BadgeCheck, Bell, Camera, Car, Check, CheckCircle2,
  ChevronLeft, ChevronRight, CircleAlert, ClipboardList, Clock3, Cpu,
  Database, Eye, FileText, Filter, Gauge, GitBranch, Info, LayoutDashboard,
  Lock, Mail, Maximize2, Minimize2, Menu, Minus, Play, Search, Settings, ShieldAlert, SlidersHorizontal,
  Unlock, UserRound, Wifi, WifiOff, X, Zap,
} from "lucide-react";
import { useRealtime } from "./context/RealtimeContext.jsx";

const API = import.meta.env.VITE_API_URL ?? `http://${window.location.hostname}:8000`;

const NAV = [
  { id: "dashboard", label: "Dashboard",    icon: LayoutDashboard },
  { id: "events",    label: "Eventos",      icon: Car },
  { id: "settings",  label: "Configuración", icon: Settings },
];

const TYPE_LABEL = { normal: "Normal", advertencia: "Advertencia", infraccion: "Infracción", grave: "Grave" };
const REV_LABEL  = { automatica: "Automática", pendiente: "Pendiente", aprobado: "Aprobado", rechazado: "Rechazado" };

// Severidad crisp (0-100) -> horas de suspensión. LINEAL: horas DIRECTAMENTE
// PROPORCIONALES a la severidad del FIS (sin curvas a mano). Debe coincidir con
// _crisp_to_horas en backend/src/api/mailer.py.
//   severidad <= 30 -> 0 (región de advertencia) · 30..100 -> 0..168 h (7 días, techo).
function crispToHours(crisp) {
  if (crisp === null || crisp === undefined) return 0;
  const c = Math.max(0, Math.min(100, crisp));
  return Math.max(0, (c - 30) / 70) * 168;
}
function fmtDuracion(hours) {
  const h = Math.round(hours);
  if (h <= 0) return null;                 // sin suspensión (advertencia)
  const d = Math.floor(h / 24), r = h % 24;
  if (d === 0) return `${r} h`;
  if (r === 0) return `${d} d`;
  return `${d} d ${r} h`;
}
// Texto de sanción para un evento (fuzzySystem): expulsión / duración / sin sanción.
function sancionTexto(fz) {
  if (fz?.esTemeraria) return "Expulsión definitiva";
  return fmtDuracion(crispToHours(fz?.crispOutput)) ?? "Sin sanción";
}
// Placa formateada ABC-1234 (3 letras + guion + resto).
function fmtPlaca(s) {
  return s && s.length > 3 ? `${s.slice(0, 3)}-${s.slice(3)}` : (s ?? "—");
}

export default function App() {
  const [view, setView]           = useState("dashboard");
  const [eventId, setEventId]     = useState(null);
  const [query, setQuery]         = useState("");
  const [collapsed, setCollapsed] = useState(false);

  const { events, latestEvent, connected } = useRealtime();

  const selectedEvent = (eventId ? events.find(e => e.id === eventId) : null) ?? events[0];

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return events;
    return events.filter(e =>
      [e.plateOcr, e.plateValidated, e.type, e.reviewStatus, e.id].join(" ").toLowerCase().includes(q)
    );
  }, [query, events]);

  const openDetail = id => { setEventId(id); setView("detail"); };

  return (
    <div className={`app-shell${collapsed ? " sidebar-collapsed" : ""}`}>
      <Sidebar
        view={view}
        setView={setView}
        collapsed={collapsed}
        onToggle={() => setCollapsed(v => !v)}
        connected={connected}
      />
      <div className="main-area">
        <Topbar connected={connected} onOpenDetail={openDetail} />
        <div className="page-content">
          {view === "dashboard" && <Dashboard event={latestEvent ?? events[0]} onOpen={openDetail} />}
          {view === "events"    && <EventsView filtered={filtered} query={query} setQuery={setQuery} onOpen={openDetail} />}
          {view === "detail"    && <DetailPage event={selectedEvent} onBack={() => setView("events")} onDash={() => setView("dashboard")} onEvents={() => setView("events")} />}
          {view === "settings"  && <SettingsView />}
        </div>
      </div>
    </div>
  );
}

/* ─── Sidebar ────────────────────────────────────────────── */

function Sidebar({ view, setView, collapsed, onToggle, connected }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-logo-wrap">
          <img src="/mock/logo_uta.png" alt="UTA" className="brand-logo" />
        </div>
        {!collapsed && (
          <div className="brand-text">
            <strong>Monitoreo UTA</strong>
            <span>Campus inteligente</span>
          </div>
        )}
        <button
          className="sidebar-toggle-btn"
          onClick={onToggle}
          title={collapsed ? "Expandir menú" : "Colapsar menú"}
        >
          {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
        </button>
      </div>

      <nav className="nav-list">
        {NAV.map(({ id, label, icon: Icon }) => {
          const active = view === id || (view === "detail" && id === "events");
          return (
            <button
              key={id}
              className={`nav-item${active ? " active" : ""}${collapsed ? " nav-item-icon-only" : ""}`}
              onClick={() => setView(id)}
              title={collapsed ? label : undefined}
            >
              <Icon size={18} />
              {!collapsed && <span>{label}</span>}
            </button>
          );
        })}
      </nav>

      <div className={`sidebar-footer${collapsed ? " sidebar-footer-collapsed" : ""}`}>
        <div className="sidebar-avatar">A</div>
        {!collapsed && (
          <div className="sidebar-footer-text">
            <strong>Administrador</strong>
            <span>admin@uta.edu.ec</span>
          </div>
        )}
        <div className="online-dot" style={{ marginLeft: collapsed ? 0 : "auto" }}
          title={connected ? "Backend conectado" : "Sin conexión"} />
      </div>
    </aside>
  );
}

/* ─── Toggle de envío de correo (kill-switch global) ──────── */

function EmailToggle() {
  const [enabled, setEnabled] = useState(null);   // null = cargando
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/email/status`)
      .then(r => r.json())
      .then(d => setEnabled(!!d.enabled))
      .catch(() => setEnabled(null));
  }, []);

  const toggle = async () => {
    if (busy || enabled === null) return;
    const next = !enabled;
    setBusy(true);
    setEnabled(next);                       // optimista
    try {
      const r = await fetch(`${API}/api/email/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: next }),
      });
      const d = await r.json();
      setEnabled(!!d.enabled);
    } catch {
      setEnabled(!next);                     // revierte si falla
    } finally {
      setBusy(false);
    }
  };

  const on = enabled === true;
  const cls = enabled === null ? "loading" : on ? "on" : "off";
  return (
    <button
      className={`email-toggle ${cls}`}
      onClick={toggle}
      disabled={busy || enabled === null}
      title={on
        ? "Correo ENCENDIDO — se envían correos al aprobar"
        : "Correo APAGADO — no se envían correos (ideal para probar con video)"}
    >
      <Mail size={15} />
      <span>{enabled === null ? "Correo…" : on ? "Correo ON" : "Correo OFF"}</span>
    </button>
  );
}

/* ─── Speed boost (presentación): suma km/h a la velocidad detectada ─── */

function SpeedBoost() {
  const [enabled, setEnabled] = useState(false);
  const [kmh, setKmh] = useState(20);

  useEffect(() => {
    fetch(`${API}/api/speed-boost`)
      .then(r => r.json())
      .then(d => { setEnabled(!!d.enabled); setKmh(Number(d.kmh ?? 20)); })
      .catch(() => {});
  }, []);

  const push = next => {
    fetch(`${API}/api/speed-boost`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(next),
    })
      .then(r => r.json())
      .then(d => { setEnabled(!!d.enabled); setKmh(Number(d.kmh ?? 0)); })
      .catch(() => {});
  };

  const toggle = () => { const v = !enabled; setEnabled(v); push({ enabled: v, kmh }); };
  const onKmh = e => {
    const v = Math.max(0, Number(e.target.value) || 0);
    setKmh(v);
    if (enabled) push({ enabled, kmh: v });
  };

  return (
    <div className={`speed-boost ${enabled ? "on" : "off"}`}
         title="Suma km/h a la velocidad detectada (solo presentación)">
      <Gauge size={15} />
      <span className="speed-boost-lab">+</span>
      <input type="number" className="speed-boost-input" value={kmh}
             min="0" step="1" onChange={onKmh} />
      <span className="speed-boost-lab">km/h</span>
      <button className="speed-boost-btn" onClick={toggle}>{enabled ? "ON" : "OFF"}</button>
    </div>
  );
}

/* ─── Topbar ─────────────────────────────────────────────── */

function Topbar({ connected, onOpenDetail }) {
  const { systemStatus, events } = useRealtime();
  const [bellOpen, setBellOpen] = useState(false);

  // Eventos pendientes de revisión (infracciones sin aprobar)
  const pending = events.filter(e =>
    ["infraccion", "grave"].includes(e.type) && e.reviewStatus === "pendiente"
  );

  const handleBellItem = id => {
    setBellOpen(false);
    onOpenDetail(id);
  };

  return (
    <header className="topbar">
      {/* Un solo indicador de conexión (a la izquierda); evita repetir Sistema/Backend */}
      <div className="ws-indicator" title={connected ? "WebSocket activo" : "Sin conexión WebSocket"}>
        {connected
          ? <><Wifi size={14} style={{ color: "#16a34a" }} /><span style={{ fontSize: ".72rem", color: "#16a34a", fontWeight: 600 }}>En línea</span></>
          : <><WifiOff size={14} style={{ color: "var(--uta-red)" }} /><span style={{ fontSize: ".72rem", color: "var(--uta-red)", fontWeight: 600 }}>Sin conexión</span></>
        }
      </div>
      <StatusPill icon={Gauge}        label="FPS"     value={`${systemStatus.fps}`}   tone="red" />
      <StatusPill icon={Clock3}       label="Hora"    value={systemStatus.currentTime} tone="slate" />
      <div className="topbar-spacer" />

      {/* Boost de velocidad (presentación) + toggle global de correo */}
      <SpeedBoost />
      <EmailToggle />

      {/* Bell notification */}
      <div className="bell-wrap">
        <button
          className="bell-btn"
          onClick={() => setBellOpen(v => !v)}
          title="Infracciones pendientes"
        >
          <Bell size={18} />
          {pending.length > 0 && (
            <span className="bell-badge">{pending.length > 9 ? "9+" : pending.length}</span>
          )}
        </button>

        {bellOpen && (
          <>
            <div className="bell-overlay" onClick={() => setBellOpen(false)} />
            <div className="bell-dropdown">
              <div className="bell-dropdown-header">
                <ShieldAlert size={15} color="var(--uta-red)" />
                <span>Infracciones pendientes</span>
                <span className="bell-count">{pending.length}</span>
              </div>
              {pending.length === 0 ? (
                <div className="bell-empty">Sin infracciones pendientes</div>
              ) : (
                <div className="bell-list">
                  {pending.slice(0, 8).map(e => (
                    <button key={e.id} className="bell-item" onClick={() => handleBellItem(e.id)}>
                      <div className={`bell-item-dot ${e.type}`} />
                      <div className="bell-item-body">
                        <div className="bell-item-plate">{e.plateOcr}</div>
                        <div className="bell-item-meta">
                          {e.speed} km/h · {TYPE_LABEL[e.type]} · {e.dateTime?.split(" ")[1]}
                        </div>
                      </div>
                      <ChevronRight size={13} color="var(--muted)" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Admin chip */}
      <div className="admin-chip">
        <div className="admin-avatar">A</div>
        <div className="admin-chip-text">
          <strong>Administrador</strong>
          <span>admin@uta.edu.ec</span>
        </div>
      </div>
    </header>
  );
}

function StatusPill({ icon: Icon, label, value, tone }) {
  return (
    <div className="status-pill">
      <div className={`status-pill-icon ${tone}`}><Icon size={15} /></div>
      <div className="status-pill-text">
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

/* ─── Dashboard ──────────────────────────────────────────── */

function Dashboard({ event, onOpen }) {
  const { videoUrl, events } = useRealtime();
  return (
    <div className="view-stack">
      {/* Estilo NVR: camara grande a la izquierda, feed de eventos a la derecha */}
      <div className="cctv-grid">
        <VideoPanel videoUrl={videoUrl} event={event} />
        <EventFeed events={events} onOpen={onOpen} />
      </div>
    </div>
  );
}

function EventFeed({ events, onOpen }) {
  return (
    <div className="card cctv-feed">
      <div className="card-header">
        <div className="card-header-left">
          <div className="live-dot" />
          <span style={{ fontSize: ".875rem", fontWeight: 700 }}>Eventos en vivo</span>
        </div>
        <span className="stream-tag">{events.length}</span>
      </div>
      <div className="cctv-feed-list">
        {events.length === 0 && (
          <div className="cctv-feed-empty">Esperando detecciones de la cámara…</div>
        )}
        {events.map(e => {
          const over = e.speed > e.speedLimit;
          return (
            <button key={e.id} className="cctv-feed-item" onClick={() => onOpen(e.id)}>
              <div className="cctv-feed-thumb">
                {e.images?.frame
                  ? <img src={e.images.frame} alt={e.plateValidated ?? e.plateOcr} />
                  : <Car size={20} />}
              </div>
              <div className="cctv-feed-body">
                <div className="cctv-feed-plate">{e.plateValidated ?? e.plateOcr}</div>
                <span className={`badge ${e.type}`}><span className="badge-dot" />{TYPE_LABEL[e.type]}</span>
                <div className="cctv-feed-sub">
                  <span className={over ? "text-danger" : "text-success"}>{e.speed} km/h</span>
                  {" · "}{e.dateTime?.split(" ")[1]}
                </div>
              </div>
              <ChevronRight size={15} color="var(--muted)" />
            </button>
          );
        })}
      </div>
    </div>
  );
}

// Badge de fuente: EN VIVO (cámara) o VIDEO · nombre, desde el status real.
function SourceBadge() {
  const { systemStatus } = useRealtime();
  const t = systemStatus.sourceType, n = systemStatus.sourceName;
  if (!t) return null;
  if (t === "idle") return <span className="src-badge video">DETENIDO</span>;
  return t === "live"
    ? <span className="src-badge live"><span className="src-dot" /> EN VIVO</span>
    : <span className="src-badge video" title={n}>VIDEO · {n}</span>;
}

// Selector de fuente: UN solo desplegable 'Fuente' con todo (en vivo por nombre de
// cámara, elegir video, detener). Mantiene el header del panel limpio.
function SourcePicker() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState(false);
  const [cams, setCams] = useState([]);     // [{index, name}] desde /api/cameras
  const [camSel, setCamSel] = useState(""); // índice de la cámara activa (para el ◉)

  // escanea las cámaras conectadas (por nombre, vía pygrabber en el backend)
  const cargarCams = () => {
    fetch(`${API}/api/cameras`)
      .then(r => r.json())
      .then(d => setCams(Array.isArray(d.cameras) ? d.cameras : []))
      .catch(() => setCams([]));
  };
  useEffect(() => { cargarCams(); }, []);

  const post = async (url, body) => {
    setOpen(false);
    setBusy(true);
    setMsg(url.endsWith("browse") ? "Abriendo explorador…"
         : url.endsWith("stop")   ? "Deteniendo…" : "");
    let delay = 4000;
    try {
      const r = await fetch(`${API}${url}`, body
        ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
        : { method: "POST" });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail ?? "Error");
      const s = body?.source;
      if (d.cancelled) setMsg("");
      else if (d.stopped) setMsg("Detenido — cámara liberada.");
      else if (d.vision_launched) { setMsg("Iniciando visión… (~15 s la primera vez)"); delay = 16000; }
      else if (s === "live") setMsg("Cambiando a EN VIVO…");
      else if (/^\d+$/.test(String(s))) {
        const cam = cams.find(c => String(c.index) === String(s));
        setMsg(cam ? `Cámara: ${cam.name}…` : `Cámara #${s}…`);
      }
      else setMsg(`Reproduciendo ${d.name ?? ""}…`);
    } catch (e) { setMsg(e.message); }
    finally { setBusy(false); setTimeout(() => setMsg(""), delay); }
  };

  const elegirCamara = idx => { setCamSel(String(idx)); post("/api/source", { source: String(idx) }); };
  const usarConfig   = ()  => { setCamSel(""); post("/api/source", { source: "live" }); };

  const item = {
    display: "flex", alignItems: "center", gap: 8, width: "100%", textAlign: "left",
    padding: "7px 12px", background: "none", border: "none", cursor: "pointer",
    fontSize: ".82rem", color: "var(--text, #1e293b)", borderRadius: 6,
  };
  const radio = on => ({ color: on ? "var(--uta-red, #c12028)" : "var(--muted, #94a3b8)", width: 14 });

  return (
    <div className="source-picker" style={{ position: "relative" }}>
      <button disabled={busy}
              onClick={() => { setOpen(o => !o); if (!open) cargarCams(); }}
              title="Elegir la fuente de video"
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "7px 14px", borderRadius: 8, cursor: busy ? "default" : "pointer",
                background: open ? "var(--uta-red, #c12028)" : "#fff",
                color: open ? "#fff" : "var(--text, #1e293b)",
                border: "1px solid " + (open ? "var(--uta-red, #c12028)" : "var(--border, #cbd5e1)"),
                fontSize: ".82rem", fontWeight: 600, opacity: busy ? 0.6 : 1,
                boxShadow: "0 1px 2px rgba(0,0,0,.05)",
              }}>
        <Camera size={15} /> {busy ? "…" : "Fuente"} <span style={{ fontSize: ".7rem" }}>▾</span>
      </button>

      {open && (
        <>
          {/* capa para cerrar al hacer clic fuera */}
          <div onClick={() => setOpen(false)}
               style={{ position: "fixed", inset: 0, zIndex: 40 }} />
          <div style={{
            position: "absolute", top: "calc(100% + 6px)", right: 0, zIndex: 50,
            minWidth: 220, background: "#fff", border: "1px solid var(--border, #e2e8f0)",
            borderRadius: 10, boxShadow: "0 8px 24px rgba(0,0,0,.14)", padding: 5,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
                          padding: "6px 12px 2px", fontSize: ".68rem", fontWeight: 700,
                          letterSpacing: ".4px", color: "var(--muted, #94a3b8)" }}>
              <span>EN VIVO</span>
              <span onClick={cargarCams} title="Re-escanear cámaras"
                    style={{ cursor: "pointer", fontSize: ".9rem" }}>↻</span>
            </div>
            {cams.length === 0 && (
              <div style={{ ...item, color: "var(--muted, #94a3b8)", cursor: "default" }}>
                (sin cámaras detectadas)
              </div>
            )}
            {cams.map(c => (
              <button key={c.index} style={item} onClick={() => elegirCamara(c.index)}>
                <span style={radio(camSel === String(c.index))}>
                  {camSel === String(c.index) ? "◉" : "○"}
                </span>
                {c.name || `Cámara ${c.index}`}
              </button>
            ))}
            <button style={item} onClick={usarConfig}>
              <span style={radio(camSel === "")}>{camSel === "" ? "◉" : "○"}</span>
              Cámara (config)
            </button>

            <div style={{ borderTop: "1px solid var(--border, #e2e8f0)", margin: "5px 0" }} />

            <button style={item} onClick={() => post("/api/source/browse")}>
              <Play size={14} /> Elegir video…
            </button>
            <button style={{ ...item, color: "var(--uta-red, #c12028)" }}
                    onClick={() => post("/api/source/stop")}>
              <Minus size={14} /> Detener
            </button>
          </div>
        </>
      )}
      {msg && <span className="source-msg">{msg}</span>}
    </div>
  );
}

function VideoPanel({ videoUrl, event }) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const [isFs, setIsFs] = useState(false);
  const [live, setLive] = useState(false);   // true cuando llega el primer frame

  const toggleFullscreen = () => {
    const el = containerRef.current;
    if (!el) return;
    if (!document.fullscreenElement) {
      el.requestFullscreen().then(() => setIsFs(true)).catch(() => {});
    } else {
      document.exitFullscreen().then(() => setIsFs(false)).catch(() => {});
    }
  };

  // Sync state if user presses Esc
  React.useEffect(() => {
    const handler = () => setIsFs(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  // Video en vivo: WebSocket binario (/ws/video). Cada mensaje es un JPEG que se
  // dibuja en el <canvas>. Reconecta solo si la API/vision aun no estan listas
  // -> NO se necesita F5. El stream ya viene anotado por vision (lineas + cajas).
  React.useEffect(() => {
    let ws = null;
    let cerrado = false;
    let reconnect = null;

    const draw = async (blob) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      try {
        const bmp = await createImageBitmap(blob);
        if (canvas.width !== bmp.width || canvas.height !== bmp.height) {
          canvas.width = bmp.width;
          canvas.height = bmp.height;
        }
        canvas.getContext("2d").drawImage(bmp, 0, 0);
        bmp.close?.();
        setLive(true);
      } catch { /* frame corrupto: ignorar */ }
    };

    const open = () => {
      if (cerrado) return;
      ws = new WebSocket(videoUrl);
      ws.binaryType = "blob";
      ws.onmessage = ({ data }) => { if (data instanceof Blob) draw(data); };
      ws.onclose = () => {
        setLive(false);
        if (!cerrado) reconnect = setTimeout(open, 2000);   // reintento auto
      };
      ws.onerror = () => ws?.close();
    };

    open();
    return () => {
      cerrado = true;
      clearTimeout(reconnect);
      ws?.close();
    };
  }, [videoUrl]);

  return (
    <div className="card">
      <div className="card-header video-card-header">
        <div className="card-header-left">
          <div className="live-dot" />
          <span style={{ fontSize: ".875rem", fontWeight: 700 }}>Video en vivo</span>
          <SourceBadge />
        </div>
        <SourcePicker />
      </div>
      <div className="video-frame" ref={containerRef}>
        <canvas ref={canvasRef} />
        {!live && (
          <div className="video-placeholder">
            {event?.images?.frame
              ? <img src={event.images.frame} alt="Última detección" />
              : <span>Conectando con la cámara…</span>}
          </div>
        )}
        <button className="video-fullscreen-btn" onClick={toggleFullscreen} title={isFs ? "Salir de pantalla completa" : "Pantalla completa"}>
          {isFs ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
        </button>
      </div>
    </div>
  );
}

function LatestDetection({ event, onOpen }) {
  if (!event) return null;
  const over = event.speed > event.speedLimit;
  return (
    <div className="card">
      <div className="card-header">
        <div className="card-header-left">
          <Car size={17} color="var(--uta-red)" />
          <h2>Última detección</h2>
        </div>
      </div>
      <div className="card-body">
        {/* Frame completo del vehículo */}
        <div className="latest-vehicle-img">
          <img src={event.images.frame} alt="Imagen capturada" />
        </div>

        <dl className="kv-list" style={{ marginTop: 12 }}>
          <div className="kv-row">
            <dt>Placa (OCR)</dt>
            <dd style={{ fontFamily: "monospace", fontSize: "1rem", fontWeight: 800, color: "var(--uta-red)" }}>{event.plateOcr}</dd>
          </div>
          <div className="kv-row">
            <dt>Velocidad</dt>
            <dd className={over ? "text-danger" : "text-success"}>{event.speed} km/h</dd>
          </div>
          <div className="kv-row"><dt>Límite</dt><dd>{event.speedLimit} km/h</dd></div>
          <div className="kv-row">
            <dt>Estado</dt>
            <dd><span className={`badge ${event.type}`}><span className="badge-dot" />{TYPE_LABEL[event.type]}</span></dd>
          </div>
          <div className="kv-row">
            <dt>Hora</dt>
            <dd style={{ color: "var(--muted)", fontSize: ".82rem" }}>{event.dateTime?.split(" ")[1] ?? "—"}</dd>
          </div>
        </dl>

        <div className={`speed-callout${!over ? " normal" : ""}`} style={{ marginTop: 12 }}>
          <Gauge size={34} />
          <div>
            <div className="speed-callout-value">{event.speed} km/h</div>
            <div className="speed-callout-sub">{over ? "Exceso de velocidad" : "Dentro del límite"}</div>
          </div>
        </div>

        <button className="btn btn-primary btn-md" style={{ width: "100%", marginTop: 12 }} onClick={() => onOpen(event.id)}>
          <Eye size={16} /> Ver detalle completo
        </button>
      </div>
    </div>
  );
}

function MetricGrid() {
  const { events } = useRealtime();
  const today = new Date().toISOString().slice(0, 10);
  const todayEvents = events.filter(e => e.dateTime?.startsWith(today));
  const violations  = todayEvents.filter(e => ["infraccion","grave"].includes(e.type));
  const avgSpeed    = todayEvents.length
    ? Math.round(todayEvents.reduce((s, e) => s + e.speed, 0) / todayEvents.length)
    : 0;
  const pending     = events.filter(e => e.reviewStatus === "pendiente");

  return (
    <div className="metric-grid">
      {[
        { icon: Car,          label: "Detectados hoy",   value: todayEvents.length, tone: "blue",  sub: "vehículos" },
        { icon: ShieldAlert,  label: "Infracciones hoy", value: violations.length,  tone: "red",   sub: "eventos" },
        { icon: Gauge,        label: "Vel. promedio",    value: `${avgSpeed} km/h`, tone: "amber", sub: "hoy" },
        { icon: ClipboardList,label: "Pendientes",       value: pending.length,     tone: "rose",  sub: "de revisión" },
      ].map(({ icon: Icon, label, value, tone, sub }) => (
        <div key={label} className="metric-card">
          <div className={`metric-icon ${tone}`}><Icon size={22} /></div>
          <div>
            <span className="metric-value">{value}</span>
            <span className="metric-label">{label}</span>
            <span className="metric-sub">{sub}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function RecentTable({ onOpen }) {
  const { events } = useRealtime();
  return (
    <div className="card">
      <div className="card-header">
        <div className="card-header-left"><Clock3 size={17} /><h2>Historial reciente</h2></div>
      </div>
      <div style={{ padding: "0 0 8px" }}>
        <EventTable rows={events.slice(0, 5)} onOpen={onOpen} />
      </div>
    </div>
  );
}

/* ─── Events view ────────────────────────────────────────── */

function EventsView({ filtered, query, setQuery, onOpen }) {
  return (
    <div className="view-stack">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 4 }}>
        <div>
          <h1 style={{ fontSize: "1.75rem" }}>Eventos detectados</h1>
          <p style={{ color: "var(--muted)", fontSize: ".9rem", marginTop: 5 }}>Consulta, filtra y abre cada detección para revisión.</p>
        </div>
        <button className="btn btn-ghost btn-md"><SlidersHorizontal size={16} /> Filtros avanzados</button>
      </div>
      <div className="filter-bar">
        <Search size={16} />
        <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Buscar por placa, estado o ID…" />
      </div>
      <div className="card">
        <EventTable rows={filtered} onOpen={onOpen} />
      </div>
    </div>
  );
}

function EventTable({ rows, onOpen }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Hora</th><th>ID</th><th>Placa</th><th>Velocidad</th><th>Límite</th>
            <th>Evento</th><th>Revisión</th><th></th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={8} style={{ textAlign: "center", color: "var(--muted)", padding: "28px 0" }}>
                Sin eventos aún. Esperando detecciones de la cámara…
              </td>
            </tr>
          )}
          {rows.map(e => (
            <tr key={e.id}>
              <td style={{ color: "var(--muted)", fontSize: ".8rem" }}>{e.dateTime?.split(" ")[1]}</td>
              <td style={{ fontWeight: 700, fontSize: ".82rem", fontFamily: "monospace" }}>{e.id}</td>
              <td style={{ fontWeight: 700 }}>{e.plateValidated}</td>
              <td className={e.speed > e.speedLimit ? "text-danger" : "text-success"}>{e.speed} km/h</td>
              <td style={{ color: "var(--muted)" }}>{e.speedLimit} km/h</td>
              <td><span className={`badge ${e.type}`}><span className="badge-dot" />{TYPE_LABEL[e.type]}</span></td>
              <td><span className={`status-badge ${e.reviewStatus}`}>{REV_LABEL[e.reviewStatus]}</span></td>
              <td><button className="btn-icon" onClick={() => onOpen(e.id)}><Eye size={15} /></button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Detail page ────────────────────────────────────────── */

const DETAIL_TABS = [
  { id: "resumen", label: "Resumen general",        icon: FileText },
  { id: "vision",  label: "Visión por computadora", icon: Eye },
  { id: "fuzzy",   label: "Sistema difuso",          icon: Zap },
];

function DetailPage({ event, onBack, onDash, onEvents }) {
  const [tab, setTab] = useState("resumen");
  if (!event) return null;

  return (
    <div className="detail-page">
      <div className="detail-topnav">
        <button className="btn btn-outline btn-sm" onClick={onBack}>
          <ArrowLeft size={15} /> Volver
        </button>
        <nav className="breadcrumb">
          <button onClick={onDash}>Dashboard</button>
          <ChevronRight size={13} />
          <button onClick={onEvents}>Eventos</button>
          <ChevronRight size={13} />
          <span>{event.id}</span>
        </nav>
      </div>

      <EventHeroStrip event={event} />

      <div className="detail-tabs-bar">
        {DETAIL_TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} className={`tab-btn${tab === id ? " active" : ""}`} onClick={() => setTab(id)}>
            <Icon size={15} />{label}
          </button>
        ))}
      </div>

      {tab === "resumen" && <ResumenTab event={event} />}
      {tab === "vision"  && <VisionTab  event={event} />}
      {tab === "fuzzy"   && <FuzzyTab   event={event} />}
    </div>
  );
}

function EventHeroStrip({ event }) {
  const over   = event.speed > event.speedLimit;
  const excess = Math.round((event.speed - event.speedLimit) * 10) / 10;
  return (
    <div className="event-hero-strip">
      <div className="hero-top-row">
        <div>
          <div className={`hero-event-badge ${event.type}`}>
            <ShieldAlert size={12} /> {TYPE_LABEL[event.type]}
          </div>
          <div className="hero-evt-id">{event.id}</div>
          <div className="hero-subtitle">
            {event.dateTime}
          </div>
        </div>
        <div className="hero-status-block">
          <div className={`hero-status-pill ${event.type}`}>
            <ShieldAlert size={13} /> {TYPE_LABEL[event.type]}
          </div>
          <div className="hero-status-pill advertencia" style={{ fontSize: ".72rem" }}>
            <Clock3 size={12} /> {REV_LABEL[event.reviewStatus]}
          </div>
        </div>
      </div>
      <div className="hero-kpi-row">
        {[
          { label: "Placa OCR",       value: event.plateOcr,           icon: FileText },
          { label: "Velocidad",       value: `${event.speed} km/h`,    icon: Gauge, cls: over ? "danger" : "success" },
          { label: "Límite",          value: `${event.speedLimit} km/h`, icon: Gauge },
          { label: "Exceso",          value: over ? `+${excess} km/h` : "—", icon: CircleAlert, cls: over ? "danger" : "success" },
          { label: "Riesgo",          value: event.riskLevel?.toUpperCase(), icon: ShieldAlert, cls: ["alto","critico"].includes(event.riskLevel) ? "danger" : "success" },
          { label: "Fecha",           value: event.dateTime?.split(" ")[0], icon: Clock3 },
        ].map(({ label, value, icon: Icon, cls = "" }) => (
          <div key={label} className="hero-kpi">
            <div className="hero-kpi-label"><Icon size={13} />{label}</div>
            <div className={`hero-kpi-value ${cls}`}>{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Human review box ───────────────────────────────────── */

function ReviewModal({ event, onClose }) {
  const [placa, setPlaca]   = useState(event.plateOcr ?? "");
  const [motivo, setMotivo] = useState("");
  const [unlocked, setUnlocked] = useState(false);  // candado: editable solo si se desbloquea
  const [status, setStatus] = useState("idle"); // idle | loading | ok | error
  const [msg, setMsg]       = useState("");
  const { markReviewed }    = useRealtime();

  const dbId = event.db_id ?? event.id;
  const original = (event.plateOcr ?? "").toUpperCase();
  const modified = placa.trim().toUpperCase() !== original;

  const cropImg = event.images?.plateStraight ?? event.images?.plateDetected ?? event.images?.plate;
  const over    = event.speed > event.speedLimit;
  const excess  = Math.round((event.speed - event.speedLimit) * 10) / 10;

  const call = async (action) => {
    setStatus("loading"); setMsg("");
    try {
      const res = await fetch(`${API}/api/events/${dbId}/${action}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          placa_corregida: modified ? placa.trim().toUpperCase() : null,
          motivo: motivo || null,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Error del servidor");
      setStatus("ok");
      // refleja el nuevo estado en la app: el evento deja de estar 'pendiente' y el
      // boton "Revisar" desaparece -> no se puede aprobar (ni reenviar correo) dos veces.
      markReviewed(event.id, action === "approve" ? "aprobado" : "rechazado",
                   modified ? placa.trim().toUpperCase() : undefined);
      setMsg(action === "approve"
        ? (data["email-sent"] > 0 ? "Correo enviado."
                                  : "Sanción aprobada (correo en cola u OFF).")
        : "Evento rechazado correctamente.");
    } catch (e) { setStatus("error"); setMsg(e.message); }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="review-modal" onClick={e => e.stopPropagation()}>
        <div className="review-modal-head">
          <span><ShieldAlert size={18} /> Revisión y aprobación</span>
          <button className="modal-close" onClick={onClose}><X size={18} /></button>
        </div>

        {status === "ok" ? (
          <div className="review-modal-body" style={{ textAlign: "center", padding: "36px 24px" }}>
            <Check size={44} color="#16a34a" />
            <p style={{ fontWeight: 700, color: "#15803d", margin: "12px 0 16px" }}>{msg}</p>
            <button className="btn btn-approve btn-md" onClick={onClose}>Cerrar</button>
          </div>
        ) : (
          <div className="review-modal-body">
            {/* Evidencia: recorte de la placa (no el carro entero) */}
            {cropImg && (
              <div className="review-crop">
                <img src={cropImg} alt="Placa detectada" />
                <span>Recorte de la placa — evidencia</span>
              </div>
            )}

            {/* Placa leída (vistosa) + corrección */}
            <div className="review-plate-block">
              <div className="review-plate-big">{fmtPlaca(placa.toUpperCase())}</div>
              <div className="review-plate-conf">OCR {Math.round((event.ocrConfidence ?? 0) * 100)}%</div>
            </div>
            <div className="form-field">
              <label className="form-label">Placa {unlocked ? "(editable)" : "(bloqueada)"}</label>
              <div className="plate-edit-row">
                <input className="form-input" value={placa} disabled={!unlocked}
                       onChange={e => setPlaca(e.target.value.toUpperCase())} />
                <button type="button"
                        className={`lock-btn${unlocked ? " unlocked" : ""}`}
                        onClick={() => setUnlocked(u => !u)}
                        title={unlocked ? "Bloquear placa" : "Desbloquear para corregir"}>
                  {unlocked ? <Unlock size={15} /> : <Lock size={15} />}
                </button>
              </div>
            </div>
            {(unlocked || modified) && (
              <div className="review-warn">
                <ShieldAlert size={14} />
                <span>Estás por <b>modificar</b> la placa — el cambio quedará <b>registrado</b> en el historial.</span>
              </div>
            )}

            {/* Resolución del sistema difuso (lo que se sanciona) */}
            <div className="review-fuzzy">
              <div className="review-fuzzy-title"><Zap size={14} /> Resolución del sistema difuso</div>
              <div className="review-fuzzy-grid">
                <div><span>Velocidad</span><b className={over ? "text-danger" : ""}>{event.speed} km/h</b></div>
                <div><span>Exceso</span><b className={over ? "text-danger" : ""}>{over ? `+${excess} km/h` : "—"}</b></div>
                <div><span>Riesgo</span><b style={{ color: ["alto","critico"].includes(event.riskLevel) ? "var(--uta-red)" : "var(--green)" }}>{event.riskLevel?.toUpperCase()}</b></div>
              </div>
              <div className="review-susp">
                <span>Suspensión sugerida</span>
                <b>{sancionTexto(event.fuzzySystem)}</b>
              </div>
            </div>

            <div className="form-field">
              <label className="form-label">Motivo (opcional)</label>
              <textarea className="form-textarea" placeholder="Registrar motivo si se modifica…"
                value={motivo} onChange={e => setMotivo(e.target.value)} />
            </div>

            {status === "error" && (
              <p style={{ fontSize: ".78rem", color: "var(--uta-red)", margin: 0 }}>{msg}</p>
            )}

            <div className="review-actions">
              <button className="btn btn-approve btn-md" disabled={status === "loading"} onClick={() => call("approve")}>
                <Check size={15} /> {status === "loading" ? "Enviando…" : "Aprobar y notificar"}
              </button>
              <button className="btn btn-reject btn-md" disabled={status === "loading"} onClick={() => call("reject")}>
                <X size={15} /> Rechazar
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Tab: Resumen ───────────────────────────────────────── */

function ResumenTab({ event }) {
  const over   = event.speed > event.speedLimit;
  const excess = Math.round((event.speed - event.speedLimit) * 10) / 10;
  const [reviewOpen, setReviewOpen] = useState(false);
  const cropImg = event.images?.plateStraight ?? event.images?.plateDetected ?? event.images?.plate;

  return (
    <div className="tab-panel">
      <div className="resumen-grid">
        <div className="resumen-left">
          {/* Evidencia */}
          <div className="card">
            <div className="card-header">
              <div className="card-header-left"><Eye size={16} /><h2>Evidencia del evento</h2></div>
            </div>
            <div className="evidence-images" style={cropImg ? undefined : { gridTemplateColumns: "1fr" }}>
              <div className="main-img-wrap">
                <img src={event.images.frame} alt="Imagen capturada" />
              </div>
              {cropImg && (
                <div className="plate-img-wrap">
                  <img src={cropImg} alt="Placa detectada" />
                  <span style={{ fontSize: ".72rem", color: "var(--muted)", textAlign: "center" }}>
                    Placa leída · {event.plateOcr}
                  </span>
                </div>
              )}
            </div>
          </div>

          <div className="detail-two-col">
            <div className="card">
              <div className="card-header"><div className="card-header-left"><FileText size={16} /><h2>Detalles del evento</h2></div></div>
              <dl className="info-list">
                {[
                  { label: "ID evento",     val: event.id,                   icon: FileText },
                  { label: "Fecha/hora",    val: event.dateTime,             icon: Clock3 },
                  { label: "Vel. medida",   val: `${event.speed} km/h`,      icon: Gauge, cls: over ? "text-danger" : "text-success" },
                  { label: "Límite",        val: `${event.speedLimit} km/h`, icon: Gauge },
                  { label: "Exceso",        val: over ? `+${excess} km/h` : "Sin exceso", icon: CircleAlert, cls: over ? "text-danger" : "text-success" },
                  { label: "Confianza OCR", val: `${Math.round(event.ocrConfidence * 100)}%`, icon: BadgeCheck },
                ].map(({ label, val, icon: Icon, cls = "" }) => (
                  <div key={label} className="info-row">
                    <dt><Icon size={13} />{label}</dt><dd className={cls}>{val}</dd>
                  </div>
                ))}
              </dl>
            </div>

            <div className="card">
              <div className="card-header"><div className="card-header-left"><Car size={16} /><h2>Detección</h2></div></div>
              <dl className="info-list">
                {[
                  { label: "Placa OCR",      val: event.plateOcr },
                  { label: "Placa validada", val: event.plateValidated },
                  { label: "Reincidencias",  val: `${event.recurrenceCount} previas` },
                ].map(({ label, val }) => (
                  <div key={label} className="info-row">
                    <dt>{label}</dt><dd>{val ?? "—"}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        </div>

        {/* Sidebar derecho */}
        <div className="key-info-sidebar">
          <div className="card">
            <div className="card-header"><div className="card-header-left"><Info size={16} /><h2>Información clave</h2></div></div>
            <dl className="info-kv">
              {[
                { label: "Tipo de evento",    val: <span className={`badge ${event.type}`}><span className="badge-dot"/>{TYPE_LABEL[event.type]}</span> },
                { label: "Estado revisión",   val: <span className={`status-badge ${event.reviewStatus}`}>{REV_LABEL[event.reviewStatus]}</span> },
                { label: "Nivel de riesgo",   val: <strong style={{ color: ["alto","critico"].includes(event.riskLevel) ? "var(--uta-red)" : "var(--green)" }}>{event.riskLevel?.toUpperCase()}</strong> },
                { label: "Sanción sugerida",  val: sancionTexto(event.fuzzySystem) },
                { label: "Reincidencias",     val: `${event.recurrenceCount} previas` },
                { label: "Confianza OCR",     val: `${Math.round(event.ocrConfidence * 100)}%` },
              ].map(({ label, val }) => (
                <div key={label} className="info-kv-row">
                  <dt>{label}</dt><dd>{val}</dd>
                </div>
              ))}
            </dl>
          </div>

          {event.reviewStatus === "pendiente" && (
            <button className="review-cta" onClick={() => setReviewOpen(true)}>
              <ShieldAlert size={16} /> Revisar
            </button>
          )}
        </div>
      </div>

      {reviewOpen && <ReviewModal event={event} onClose={() => setReviewOpen(false)} />}
    </div>
  );
}

/* ─── Tab: Visión ────────────────────────────────────────── */

function VisionTab({ event }) {
  const [showTech, setShowTech] = useState(false);
  const cv = event.computerVision;
  const perChar = cv.ocrPerChar ?? [];
  const ocrConf = event.ocrConfidence ?? null;
  const pct = c => Math.round((c ?? 0) * 100);

  // Etapas. Las CNN tienen confianza real (barra). Enderezado/Filtros/Segmentación
  // son CV determinista -> sin barra, solo "✓ Aplicado" (no se inventan %).
  const stages = [
    { label: "Imagen capturada",   src: event.images.frame,         conf: cv.vehicleDetection.confidence },
    { label: "Placa detectada",    src: event.images.plateDetected, conf: cv.plateDetection.confidence },
    { label: "Enderezado",         src: event.images.plateStraight, conf: null, applied: cv.usoEnderezado },
    { label: "Filtros",            src: event.images.plateFiltered, conf: null, applied: cv.usoFiltros },
    { label: "Segmentación",       src: event.images.segmentation,  conf: null, applied: true },
    { label: "Clasificación",      src: null,                       conf: ocrConf },
  ];

  // etapas con imagen real Y que de verdad se aplicaron (las omitidas no se muestran
  // en la grilla, para que concuerde con el badge "Omitido")
  const procImages = stages.filter(s => s.src && s.applied !== false);

  return (
    <div className="tab-panel">
      <div className="card">
        <div className="card-header"><div className="card-header-left"><Eye size={16} /><h2>Visualización del proceso</h2></div></div>
        <div className="card-body">
          <div className="process-images-grid proc-grid-lg">
            {procImages.map((s, i) => (
              <div key={s.label} className="proc-img-card">
                <img src={s.src} alt={s.label} />
                <div className="proc-img-label">
                  <div className="proc-num">{i + 1}</div>{s.label}
                </div>
              </div>
            ))}
            {/* Clasificación (OCR) = paso 4: crops segmentados -> lectura + placa final */}
            {perChar.length > 0 && (
              <div className="proc-img-card proc-ocr-card">
                <div className="proc-ocr-body">
                  <div className="proc-ocr-strip">
                    {perChar.map((c, i) => (
                      <div key={i} className="proc-ocr-char">
                        {c.crop && <img src={c.crop} alt={c.ch} />}
                        <span className="proc-ocr-ch">{c.ch}</span>
                        <span className="proc-ocr-pct">{pct(c.conf)}%</span>
                      </div>
                    ))}
                  </div>
                  <div className="proc-ocr-plate">{fmtPlaca(event.plateValidated ?? cv.ocr)}</div>
                  {ocrConf != null && <div className="proc-ocr-conf">Confianza {pct(ocrConf)}%</div>}
                </div>
                <div className="proc-img-label">
                  <div className="proc-num">{procImages.length + 1}</div>Clasificación
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

    </div>
  );
}

/* ─── FIS definitions hook ───────────────────────────────── */

// Colors + labels are UI concerns — stay in frontend
const SET_COLOR = {
  no_excess: "#16a34a", minor: "#84cc16", moderate: "#d97706", serious: "#ea580c", critical: "#c12028",
  clean: "#16a34a", low: "#84cc16", high: "#ea580c", chronic: "#c12028",
  no_action: "#16a34a", warning: "#84cc16", low_susp: "#ca8a04",
  medium_susp: "#d97706", high_susp: "#ea580c", critical_susp: "#c12028",
};

// Fallback — used if backend unreachable; matches exactly what /api/difuso/definiciones returns
const _FALLBACK_DEFS = {
  limite_velocidad: 20, umbral_temeraria: 50,
  variables_entrada: {
    exceso_velocidad: {
      universo: [0, 30], unidad: "km/h",
      conjuntos: [
        { clave: "no_excess", etiqueta: "Sin exceso", tipo: "trap", parametros: [0, 0, 2, 5] },
        { clave: "minor",     etiqueta: "Leve",       tipo: "tri",  parametros: [2, 8, 14] },
        { clave: "moderate",  etiqueta: "Moderado",   tipo: "tri",  parametros: [8, 14, 20] },
        { clave: "serious",   etiqueta: "Grave",      tipo: "tri",  parametros: [14, 20, 26] },
        { clave: "critical",  etiqueta: "Crítico",    tipo: "trap", parametros: [20, 26, 30, 30] },
      ],
    },
    reincidencia: {
      universo: [0, 10], unidad: "infracciones",
      conjuntos: [
        { clave: "clean",    etiqueta: "Limpio",   tipo: "trap", parametros: [0, 0, 1, 2.5] },
        { clave: "low",      etiqueta: "Bajo",     tipo: "tri",  parametros: [0, 2.5, 5] },
        { clave: "moderate", etiqueta: "Moderado", tipo: "tri",  parametros: [2.5, 5, 7.5] },
        { clave: "high",     etiqueta: "Alto",     tipo: "tri",  parametros: [5, 7.5, 10] },
        { clave: "chronic",  etiqueta: "Crónico",  tipo: "trap", parametros: [7.5, 9, 10, 10] },
      ],
    },
  },
  salida: {
    universo: [0, 100],
    conjuntos: [
      { clave: "no_action",     etiqueta: "Sin acción",    tipo: "trap", parametros: [0, 0, 5, 15] },
      { clave: "warning",       etiqueta: "Advertencia",   tipo: "tri",  parametros: [10, 20, 30] },
      { clave: "low_susp",      etiqueta: "Susp. baja",    tipo: "tri",  parametros: [25, 40, 55] },
      { clave: "medium_susp",   etiqueta: "Susp. media",   tipo: "tri",  parametros: [50, 65, 80] },
      { clave: "high_susp",     etiqueta: "Susp. alta",    tipo: "tri",  parametros: [75, 85, 95] },
      { clave: "critical_susp", etiqueta: "Susp. crítica", tipo: "trap", parametros: [90, 96, 100, 100] },
    ],
  },
};

let _defCache = _FALLBACK_DEFS;  // start with fallback; backend response overrides it

function useFuzzyDefs() {
  const [defs, setDefs] = React.useState(_defCache);

  React.useEffect(() => {
    if (_defCache !== _FALLBACK_DEFS) return;  // already fetched real data
    fetch(`${API}/api/difuso/definiciones`)
      .then(r => r.json())
      .then(d => { _defCache = d; setDefs(d); })
      .catch(() => {});  // fallback stays active on error
  }, []);

  return defs;
}

// Convert backend conjunto to chart-ready set object
function toChartSet(c) {
  return {
    key:    c.clave,
    label:  c.etiqueta,
    type:   c.tipo,
    params: c.parametros,
    color:  SET_COLOR[c.clave] ?? "#64748b",
  };
}

/* ─── Membership evaluation (mirrors Python fuzzy._trimf/_trapmf) */

function _trimf(x, a, b, c) {
  if (x <= a || x >= c) return 0;
  if (x <= b) return b !== a ? (x - a) / (b - a) : 1;
  return c !== b ? (c - x) / (c - b) : 1;
}
function _trapmf(x, a, b, c, d) {
  if (x < a || x > d) return 0;
  if (b <= x && x <= c) return 1;
  if (x < b) return b !== a ? (x - a) / (b - a) : 1;
  return d !== c ? (d - x) / (d - c) : 1;
}
function evalMf(x, set) {
  const p = set.params;
  return set.type === "tri"
    ? _trimf(x, p[0], p[1], p[2])
    : _trapmf(x, p[0], p[1], p[2], p[3]);
}

/* ─── Membership function chart (multi-set SVG, interactive) */

function MembershipChart({ domain, sets, currentVal }) {
  const [dMin, dMax] = domain;
  const range = dMax - dMin || 1;
  const W = 240, H = 68, PAD = 12;
  const drawW = W - PAD * 2;
  const toX = v => PAD + ((Math.max(dMin, Math.min(dMax, v)) - dMin) / range) * drawW;
  const [hov, setHov] = React.useState(null);

  const pathFor = s => {
    if (s.type === "tri") {
      const [a, b, c] = s.params;
      return `M${toX(a)},${H - 5} L${toX(b)},5 L${toX(c)},${H - 5} Z`;
    }
    const [a, b, c, d] = s.params;
    return `M${toX(a)},${H - 5} L${toX(b)},5 L${toX(c)},5 L${toX(d)},${H - 5} Z`;
  };

  const onMouseMove = e => {
    if (!sets.length) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const xRatio = (e.clientX - rect.left) / rect.width;
    const xVal = dMin + ((xRatio * W - PAD) / drawW) * range;
    const clamped = Math.max(dMin, Math.min(dMax, xVal));
    const memberships = sets
      .map(s => ({ ...s, value: evalMf(clamped, s) }))
      .filter(s => s.value > 0.001)
      .sort((a, b) => b.value - a.value);
    setHov({ xVal: clamped, memberships, rightSide: xRatio > 0.55 });
  };

  const xCur = currentVal !== null && currentVal !== undefined ? toX(currentVal) : null;
  const xHov = hov !== null ? toX(hov.xVal) : null;

  return (
    <div className="mem-chart-wrap" onMouseMove={onMouseMove} onMouseLeave={() => setHov(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="mem-chart-svg" style={{ overflow: "visible" }}>
        <line x1={PAD} y1={H - 5} x2={W - PAD} y2={H - 5} stroke="var(--border)" strokeWidth={1} />
        <text x={PAD}     y={H + 5} fontSize="7" fill="var(--muted)" textAnchor="middle">{dMin}</text>
        <text x={W - PAD} y={H + 5} fontSize="7" fill="var(--muted)" textAnchor="middle">{dMax}</text>
        {sets.map(s => (
          <path key={s.key} d={pathFor(s)}
            fill={s.color} fillOpacity={0.15}
            stroke={s.color} strokeWidth={1.5} strokeLinejoin="round" />
        ))}
        {xHov !== null && (
          <line x1={xHov} y1={3} x2={xHov} y2={H - 5}
            stroke="#94a3b8" strokeWidth={1} strokeDasharray="2,2" />
        )}
        {xCur !== null && (
          <>
            <line x1={xCur} y1={3} x2={xCur} y2={H - 5}
              stroke="#f59e0b" strokeWidth={2} strokeDasharray="3,2.5" />
            <circle cx={xCur} cy={H - 5} r={3.5} fill="#f59e0b" />
          </>
        )}
      </svg>

      {hov && hov.memberships.length > 0 && (
        <div className="mem-tooltip" style={hov.rightSide ? { right: 4 } : { left: 4 }}>
          <div className="mem-tooltip-x">{hov.xVal.toFixed(2)}</div>
          {hov.memberships.map(m => (
            <div key={m.key} className="mem-tooltip-row">
              <span className="mem-tooltip-dot" style={{ background: m.color }} />
              <span className="mem-tooltip-label">{m.label}</span>
              <span className="mem-tooltip-pct">{(m.value * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MembershipLegend({ sets, memberships }) {
  return (
    <div className="mem-legend">
      {sets.map(s => {
        const v = memberships?.[s.key] ?? 0;
        const active = v > 0.01;
        return (
          <div key={s.key} className={`mem-legend-item${active ? " active" : ""}`}>
            <span className="mem-legend-dot" style={{ background: s.color }} />
            <span className="mem-legend-name">{s.label}</span>
            {active && <span className="mem-legend-val">{v.toFixed(2)}</span>}
          </div>
        );
      })}
    </div>
  );
}

/* ─── Tab: Sistema difuso ────────────────────────────────── */

function FuzzyTab({ event }) {
  const fz   = event.fuzzySystem;
  const defs = useFuzzyDefs();
  const speed = event.speed;
  const isNormal    = event.type === "normal" || speed <= 20;
  const isTemeraria = fz.esTemeraria || speed >= 50;
  const isFIS       = !isNormal && !isTemeraria;

  // Chart sets from backend definitions (or empty while loading)
  const excesoSets   = defs ? defs.variables_entrada.exceso_velocidad.conjuntos.map(toChartSet) : [];
  const excesoUniv   = defs?.variables_entrada.exceso_velocidad.universo ?? [0, 30];
  const reinciSets   = defs ? defs.variables_entrada.reincidencia.conjuntos.map(toChartSet) : [];
  const severidadSets = defs ? defs.salida.conjuntos.map(toChartSet) : [];
  const limitVel     = defs?.limite_velocidad ?? 20;

  // Best activated set names
  const topExceso = Object.entries(fz.pertenenciaExceso ?? {}).sort(([,a],[,b]) => b - a)[0]?.[0];
  const topReinci = Object.entries(fz.pertenenciaReincidencia ?? {}).sort(([,a],[,b]) => b - a)[0]?.[0];

  // Crisp value as % for bar position
  const crispPct = fz.crispOutput !== null && fz.crispOutput !== undefined
    ? Math.max(0, Math.min(100, fz.crispOutput))
    : null;
  // Suspensión continua (días+horas) derivada del crisp del difuso. null = advertencia.
  const suspTxt = fmtDuracion(crispToHours(fz.crispOutput));

  const riskColors = { bajo: "#16a34a", medio: "#d97706", alto: "#ea580c", critico: "#c12028" };
  const riskColor = riskColors[event.riskLevel] ?? "#64748b";

  // Label helper (from loaded defs or fallback)
  const setLabel = key => {
    const allSets = [...(defs?.variables_entrada.exceso_velocidad.conjuntos ?? []),
                    ...(defs?.variables_entrada.reincidencia.conjuntos ?? []),
                    ...(defs?.salida.conjuntos ?? [])];
    return allSets.find(s => s.clave === key)?.etiqueta ?? key;
  };

  return (
    <div className="tab-panel">
      <div className="card">
        <div className="card-header">
          <div className="card-header-left">
            <Zap size={16} color="var(--uta-red)" />
            <h2>Sistema de Inferencia Difusa — Mamdani</h2>
          </div>
          <span style={{ fontSize: ".75rem", color: "var(--muted)" }}>Implicación mín · Agregación max · Defuzz. centroide</span>
        </div>

        {/* ── Estado 1: Conductor sin infracción ─────────────── */}
        {isNormal && (
          <div className="fuzzy-state-card fuzzy-state-normal">
            <CheckCircle2 size={40} color="#16a34a" />
            <div>
              <h3>Conductor sin infracción de velocidad</h3>
              <p>Velocidad detectada dentro del límite permitido. El sistema difuso no se aplica — no procede sanción.</p>
              <div className="fuzzy-state-kpis">
                <div className="fuzzy-state-kpi">
                  <span className="fsk-value">{speed} km/h</span>
                  <span className="fsk-label">Detectado</span>
                </div>
                <div className="fuzzy-state-kpi">
                  <span className="fsk-value">{limitVel} km/h</span>
                  <span className="fsk-label">Límite campus</span>
                </div>
                <div className="fuzzy-state-kpi">
                  <span className="fsk-value" style={{ color: "#16a34a" }}>Sin suspensión</span>
                  <span className="fsk-label">Sanción</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Estado 2: Conducta temeraria ───────────────────── */}
        {isTemeraria && (
          <div className="fuzzy-state-card fuzzy-state-temeraria">
            <ShieldAlert size={40} color="#c12028" />
            <div>
              <h3>Conducta temeraria detectada</h3>
              <p>
                Velocidad ≥ 50 km/h — excede el ámbito del sistema difuso. Se aplica la compuerta
                determinista (crisp) de conducta temeraria. Sanción inmediata e irrevocable.
              </p>
              <div className="fuzzy-state-kpis">
                <div className="fuzzy-state-kpi danger">
                  <span className="fsk-value">{speed} km/h</span>
                  <span className="fsk-label">Detectado</span>
                </div>
                <div className="fuzzy-state-kpi danger">
                  <span className="fsk-value">≥ 50 km/h</span>
                  <span className="fsk-label">Umbral temerario</span>
                </div>
              </div>
              <div className="temeraria-badge">
                <ShieldAlert size={14} /> REVOCACIÓN DEFINITIVA DEL ACCESO VEHICULAR
              </div>
              <p className="fuzzy-legal-note">
                Art. 191 RLOTTTSV — límite máximo urbano para vehículos livianos.
                La conducta excede el rango difuso y requiere decisión categórica.
              </p>
            </div>
          </div>
        )}

        {/* ── Estado 3: Proceso FIS completo ─────────────────── */}
        {isFIS && (
          <div className="fuzzy-three-col">

            {/* Col 1: Variables de entrada */}
            <div>
              <div className="fuzzy-col-label"><span className="fuzzy-col-num">1</span> Variables de entrada</div>

              {/* Exceso de velocidad */}
              <div className="fuzzy-input-var">
                <div className="fuzzy-var-header">
                  <div className="fuzzy-var-icon speed"><Gauge size={16} /></div>
                  <div>
                    <div className="fuzzy-var-name">Exceso de velocidad</div>
                    <div style={{ fontSize: ".7rem", color: "var(--muted)" }}>Universo [{excesoUniv[0]}, {excesoUniv[1]}] km/h</div>
                  </div>
                </div>
                <MembershipChart domain={excesoUniv} sets={excesoSets} currentVal={fz.speedExcess} />
                <MembershipLegend sets={excesoSets} memberships={fz.pertenenciaExceso} />
                <div className="fuzzy-var-body">
                  <div>
                    <div className="fuzzy-var-value">{fz.speedExcess} km/h</div>
                    <div className="fuzzy-var-range">Exceso sobre límite (20 km/h)</div>
                  </div>
                  {topExceso && (
                    <span className="membership-badge" style={{ background: "#fee2e2", color: "#c12028" }}>
                      {setLabel(topExceso)}
                    </span>
                  )}
                </div>
              </div>

              {/* Reincidencia */}
              <div className="fuzzy-input-var" style={{ marginTop: 12 }}>
                <div className="fuzzy-var-header">
                  <div className="fuzzy-var-icon recur"><UserRound size={16} /></div>
                  <div>
                    <div className="fuzzy-var-name">Reincidencia</div>
                    <div style={{ fontSize: ".7rem", color: "var(--muted)" }}>Universo [0, 10] infracciones</div>
                  </div>
                </div>
                <MembershipChart domain={[0, 10]} sets={reinciSets} currentVal={event.recurrenceCount} />
                <MembershipLegend sets={reinciSets} memberships={fz.pertenenciaReincidencia} />
                <div className="fuzzy-var-body">
                  <div>
                    <div className="fuzzy-var-value">{event.recurrenceCount} casos</div>
                    <div className="fuzzy-var-range">Infracciones previas registradas</div>
                  </div>
                  {topReinci && (
                    <span className="membership-badge" style={{ background: "#fef3c7", color: "#92400e" }}>
                      {setLabel(topReinci)}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Col 2: Reglas activadas */}
            <div>
              <div className="fuzzy-col-label"><span className="fuzzy-col-num">2</span> Reglas activadas</div>
              {fz.activatedRules.length === 0 ? (
                <div style={{ padding: "20px 0", textAlign: "center", color: "var(--muted)", fontSize: ".85rem" }}>
                  Sin reglas activas
                </div>
              ) : (
                <table className="rules-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>SI exceso · reincidencia → severidad</th>
                      <th style={{ minWidth: 80 }}>Activación</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fz.activatedRules.slice(0, 10).map(r => {
                      const act = r.activacion ?? 0;
                      const lvl = act >= 0.6 ? "high" : act >= 0.3 ? "medium" : "low";
                      return (
                        <tr key={r.id}>
                          <td><div className="rule-id">{r.id}</div></td>
                          <td>
                            <div className="rule-desc" style={{ fontSize: ".74rem" }}>
                              <strong>{setLabel(r.exceso_set)}</strong>
                              {" · "}
                              <strong>{setLabel(r.reincidencia_set)}</strong>
                              {" → "}
                              <em>{setLabel(r.severidad_set)}</em>
                            </div>
                          </td>
                          <td>
                            <div style={{ fontWeight: 700, fontSize: ".8rem", marginBottom: 3 }}>{act.toFixed(3)}</div>
                            <div className="rule-activation-bar">
                              <div className={`rule-activation-fill activation-fill-${lvl}`}
                                style={{ width: `${Math.round(act * 100)}%` }} />
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
              <div className="rules-meta">
                <div className="rules-meta-item"><GitBranch size={12} /> <strong>{fz.activatedRules.length}</strong> de 25 reglas activas</div>
                <div className="rules-meta-item"><Zap size={12} /> Defuzz.: <strong>Centroide</strong></div>
              </div>
            </div>

            {/* Col 3: Salida difusa y resultado */}
            <div>
              <div className="fuzzy-col-label"><span className="fuzzy-col-num">3</span> Resultado difuso</div>

              {/* Output membership chart */}
              <div className="fuzzy-output-chart-wrap">
                <div style={{ fontSize: ".72rem", color: "var(--muted)", marginBottom: 4, fontWeight: 600 }}>
                  Función de severidad [0 – 100]
                </div>
                <MembershipChart domain={[0, 100]} sets={severidadSets} currentVal={fz.crispOutput} />
                <MembershipLegend sets={severidadSets} memberships={{}} />
              </div>

              {/* Crisp value */}
              {crispPct !== null && (
                <div className="fuzzy-crisp-wrap">
                  <div className="fuzzy-crisp-label">
                    <span>Valor defuzzificado</span>
                    <strong>{fz.crispOutput?.toFixed(1)}</strong>
                  </div>
                  <div className="fuzzy-crisp-bar">
                    <div className="fuzzy-crisp-fill" style={{ width: `${crispPct}%` }} />
                    <div className="fuzzy-crisp-marker" style={{ left: `${crispPct}%` }} />
                  </div>
                  <div className="fuzzy-crisp-range"><span>0</span><span>100</span></div>
                </div>
              )}

              {/* Risk level */}
              <div className="fuzzy-result-risk" style={{ background: riskColor + "18", borderColor: riskColor + "40" }}>
                <div className="risk-shield" style={{ color: riskColor }}><ShieldAlert size={26} /></div>
                <div>
                  <div className="risk-level-label" style={{ color: riskColor }}>
                    {event.riskLevel?.toUpperCase() ?? "—"}
                  </div>
                  <div className="risk-membership" style={{ fontSize: ".72rem" }}>
                    Nivel de riesgo del sistema difuso
                  </div>
                </div>
              </div>

              {/* Suspensión sugerida (continua: días+horas del crisp difuso) */}
              {suspTxt ? (
                <div className="penalty-card">
                  <ClipboardList size={28} color="var(--uta-red)" />
                  <div>
                    <div className="penalty-days" style={{ fontSize: "1.7rem" }}>{suspTxt}</div>
                    <div className="penalty-unit">de suspensión sugerida</div>
                  </div>
                </div>
              ) : (
                <div className="penalty-card" style={{ border: "1.5px solid #bbf7d0", background: "#f0fdf4" }}>
                  <Check size={28} color="#16a34a" />
                  <div>
                    <div className="penalty-days" style={{ color: "#16a34a", fontSize: "1rem" }}>
                      Advertencia
                    </div>
                    <div className="penalty-unit">sin suspensión</div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Notifications ──────────────────────────────────────── */

function NotificationsView() {
  const { events } = useRealtime();
  const notifs = events
    .filter(e => ["infraccion","grave"].includes(e.type) || e.notificationStatus === "enviado")
    .slice(0, 10)
    .map(e => ({
      id: e.id,
      type: e.type === "normal" ? "felicitacion" : "infraccion",
      recipient: "Ingeniero responsable",
      subject: `Sanción aprobada — Placa ${e.plateValidated}`,
      status: e.notificationStatus,
    }));

  return (
    <div className="view-stack">
      <div><h1 style={{ fontSize: "1.75rem" }}>Notificaciones</h1>
        <p style={{ color: "var(--muted)", fontSize: ".9rem", marginTop: 5 }}>Correos enviados al ingeniero responsable del sistema.</p>
      </div>
      <div className="notif-grid">
        {notifs.map(n => (
          <div key={n.id} className="notif-card">
            <div className="notif-card-header">
              <div className={`notif-type-icon ${n.type}`}>
                {n.type === "felicitacion" ? <BadgeCheck size={18} /> : <ShieldAlert size={18} />}
              </div>
              <div>
                <div className="notif-card-title">{n.subject}</div>
                <div className="notif-card-to">{n.recipient}</div>
              </div>
              <span className={`notif-status ${n.status}`}>{n.status}</span>
            </div>
            <div className="notif-email-preview">
              <div className="notif-email-row"><dt>De:</dt><dd>sistema@uta.edu.ec</dd></div>
              <div className="notif-email-row"><dt>Para:</dt><dd>{n.recipient}</dd></div>
              <div className="notif-email-row"><dt>Asunto:</dt><dd>{n.subject}</dd></div>
              <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--border)" }}>
                {"Resultado del sistema de monitoreo vehicular UTA. Ver detalles en el dashboard."}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Statistics ─────────────────────────────────────────── */

function StatisticsView() {
  return (
    <div className="view-stack">
      <div><h1 style={{ fontSize: "1.75rem" }}>Estadísticas</h1>
        <p style={{ color: "var(--muted)", fontSize: ".9rem", marginTop: 5 }}>Análisis de eventos, velocidades y niveles de riesgo.</p>
      </div>
      <MetricGrid />
      <div className="card">
        <div style={{ display: "grid", placeItems: "center", minHeight: 280, textAlign: "center", gap: 10, padding: 30 }}>
          <Activity size={40} color="var(--muted)" />
          <div>
            <strong style={{ fontSize: "1rem" }}>Gráficas próximamente</strong>
            <p style={{ margin: "6px 0 0", color: "var(--muted)", fontSize: ".9rem" }}>
              La estructura soporta eventos, velocidad, riesgo y notificaciones por hora.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── Settings ───────────────────────────────────────────── */

// Calibrador de líneas ENTRA/SALE sobre el VIDEO EN VIVO: arrastra los 4 puntos y guarda.
// Las líneas son fracciones [0..1] -> independientes de la resolución. Al guardar, la
// visión recrea la zona EN CALIENTE (config_version), sin reiniciar.
function LineCalibrator() {
  const { videoUrl } = useRealtime();
  const wrapRef = useRef(null);
  const videoRef = useRef(null);
  const overlayRef = useRef(null);
  const dragRef = useRef(null);             // {linea, idx} del punto que se arrastra

  const [edit, setEdit] = useState(false);
  const [entra, setEntra] = useState([[0.30, 0.15], [0.20, 0.62]]);
  const [sale, setSale]   = useState([[0.62, 0.28], [0.52, 0.98]]);
  const [dist, setDist]   = useState(5.0);
  const [msg, setMsg]     = useState("");

  // cargar la calibración actual del backend
  const cargar = () => {
    fetch(`${API}/api/camera-config`).then(r => r.json()).then(d => {
      if (Array.isArray(d.linea_entra)) setEntra(d.linea_entra);
      if (Array.isArray(d.linea_sale))  setSale(d.linea_sale);
      if (d.distancia_m) setDist(d.distancia_m);
    }).catch(() => {});
  };
  useEffect(() => { cargar(); }, []);

  // video en vivo -> canvas de fondo (mismo WS binario que el panel)
  useEffect(() => {
    let ws = null, cerrado = false, recon = null;
    const draw = async blob => {
      const c = videoRef.current; if (!c) return;
      try {
        const bmp = await createImageBitmap(blob);
        if (c.width !== bmp.width || c.height !== bmp.height) { c.width = bmp.width; c.height = bmp.height; }
        c.getContext("2d").drawImage(bmp, 0, 0); bmp.close?.();
      } catch { /* frame corrupto */ }
    };
    const open = () => {
      if (cerrado) return;
      ws = new WebSocket(videoUrl); ws.binaryType = "blob";
      ws.onmessage = ({ data }) => { if (data instanceof Blob) draw(data); };
      ws.onclose = () => { if (!cerrado) recon = setTimeout(open, 2000); };
      ws.onerror = () => ws?.close();
    };
    open();
    return () => { cerrado = true; clearTimeout(recon); ws?.close(); };
  }, [videoUrl]);

  // dibujar líneas + handles en el overlay cuando cambian (o al redimensionar)
  useEffect(() => {
    const redibujar = () => {
      const c = overlayRef.current, wrap = wrapRef.current; if (!c || !wrap) return;
      const W = wrap.clientWidth, H = wrap.clientHeight;
      c.width = W; c.height = H;
      const ctx = c.getContext("2d"); ctx.clearRect(0, 0, W, H);
      const P = p => [p[0] * W, p[1] * H];
      const linea = (l, col) => {
        const a = P(l[0]), b = P(l[1]);
        ctx.strokeStyle = col; ctx.lineWidth = 3;
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
        if (edit) for (const pt of [a, b]) {
          ctx.beginPath(); ctx.arc(pt[0], pt[1], 8, 0, Math.PI * 2);
          ctx.fillStyle = "#ff3df0"; ctx.fill();
          ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke();
        }
      };
      // sin etiquetas de texto: el color distingue cada línea (verde=ENTRA, rojo=SALE)
      linea(entra, "#22c55e"); linea(sale, "#ef4444");
    };
    redibujar();
    window.addEventListener("resize", redibujar);
    return () => window.removeEventListener("resize", redibujar);
  }, [entra, sale, edit]);

  const frac = e => {
    const r = overlayRef.current.getBoundingClientRect();
    return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height];
  };
  const onDown = e => {
    if (!edit) return;
    const [fx, fy] = frac(e);
    const W = overlayRef.current.width, H = overlayRef.current.height;
    let best = null, dmin = 22;
    for (const [name, l] of [["entra", entra], ["sale", sale]])
      for (let i = 0; i < 2; i++) {
        const d = Math.hypot((l[i][0] - fx) * W, (l[i][1] - fy) * H);
        if (d < dmin) { dmin = d; best = { linea: name, idx: i }; }
      }
    dragRef.current = best;
  };
  const onMove = e => {
    if (!edit || !dragRef.current) return;
    const [fx, fy] = frac(e);
    const cl = v => Math.max(0, Math.min(1, v));
    const { linea, idx } = dragRef.current;
    const set = linea === "entra" ? setEntra : setSale;
    set(prev => { const n = prev.map(p => [...p]); n[idx] = [cl(fx), cl(fy)]; return n; });
  };
  const onUp = () => { dragRef.current = null; };

  const guardar = () => {
    setMsg("Guardando…");
    fetch(`${API}/api/camera-config`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ linea_entra: entra, linea_sale: sale, distancia_m: Number(dist) }),
    })
      .then(r => r.json().then(d => {
        if (!r.ok) throw new Error(d.detail ?? "Error");
        setMsg("Guardado ✓ — la visión aplicó las líneas en caliente.");
      }))
      .catch(e => setMsg(e.message))
      .finally(() => setTimeout(() => setMsg(""), 5000));
  };

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-header-left"><Eye size={16} /><h2>Calibración de líneas (ENTRA / SALE)</h2></div>
        <button className={`btn btn-md ${edit ? "btn-primary" : "btn-outline"}`}
                onClick={() => setEdit(v => !v)}>
          {edit ? "Calibrando… (clic para terminar)" : "Calibrar líneas"}
        </button>
      </div>
      <div className="card-body" style={{ display: "grid", gap: 12 }}>
        <p style={{ fontSize: ".82rem", color: "var(--muted)", margin: 0 }}>
          Activa <b>Calibrar líneas</b> y arrastra los 4 puntos sobre el video para
          colocar ENTRA (verde) y SALE (roja) sobre dos marcas reales de la vía.
          Pon la <b>distancia real</b> entre ellas y guarda.
        </p>
        <div ref={wrapRef}
             style={{ position: "relative", width: "100%", maxWidth: 760, aspectRatio: "16 / 9",
                      background: "#0b1220", borderRadius: 10, overflow: "hidden",
                      cursor: edit ? "crosshair" : "default" }}
             onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}>
          <canvas ref={videoRef}
                  style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }} />
          <canvas ref={overlayRef}
                  style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} />
        </div>
        <div style={{ display: "flex", gap: 14, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div style={{ display: "grid", gap: 5 }}>
            <label style={{ fontSize: ".82rem", fontWeight: 700 }}>Distancia real entre líneas (m)</label>
            <input className="form-input" type="number" step="0.1" min="0.1" style={{ width: 140 }}
                   value={dist} onChange={e => setDist(e.target.value)} />
          </div>
          <button className="btn btn-primary btn-md" onClick={guardar}>Guardar calibración</button>
          <button className="btn btn-outline btn-md" onClick={cargar}>Descartar</button>
          {msg && <span style={{ fontSize: ".82rem", color: "var(--muted)" }}>{msg}</span>}
        </div>
      </div>
    </div>
  );
}

function SettingsView() {
  return (
    <div className="view-stack">
      <div><h1 style={{ fontSize: "1.75rem" }}>Configuración</h1>
        <p style={{ color: "var(--muted)", fontSize: ".9rem", marginTop: 5 }}>Parámetros del sistema de monitoreo vehicular.</p>
      </div>

      <LineCalibrator />
    </div>
  );
}
