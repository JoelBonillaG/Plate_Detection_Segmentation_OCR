import React, { useMemo, useRef, useState } from "react";
import {
  Activity, ArrowLeft, BadgeCheck, Bell, Camera, Car, Check, CheckCircle2,
  ChevronLeft, ChevronRight, CircleAlert, ClipboardList, Clock3, Cpu,
  Database, Eye, FileText, Filter, Gauge, GitBranch, Info, LayoutDashboard,
  Mail, Maximize2, Minimize2, Menu, Search, Settings, ShieldAlert, SlidersHorizontal,
  UserRound, Wifi, WifiOff, X, Zap,
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
      <StatusPill icon={CheckCircle2} label="Sistema" value={systemStatus.system}     tone="green" />
      <StatusPill icon={Camera}       label="Cámara"  value="IP/Celular"              tone="cyan" />
      <StatusPill icon={Database}     label="Backend" value={systemStatus.backend}    tone="blue" />
      <StatusPill icon={Gauge}        label="FPS"     value={`${systemStatus.fps}`}   tone="red" />
      <StatusPill icon={Clock3}       label="Hora"    value={systemStatus.currentTime} tone="slate" />
      <div className="topbar-spacer" />

      {/* WS indicator */}
      <div className="ws-indicator" title={connected ? "WebSocket activo" : "Sin conexión WebSocket"}>
        {connected
          ? <><Wifi size={14} style={{ color: "#16a34a" }} /><span style={{ fontSize: ".72rem", color: "#16a34a", fontWeight: 600 }}>En línea</span></>
          : <><WifiOff size={14} style={{ color: "var(--uta-red)" }} /><span style={{ fontSize: ".72rem", color: "var(--uta-red)", fontWeight: 600 }}>Sin conexión</span></>
        }
      </div>

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
  const { videoUrl } = useRealtime();
  return (
    <div className="view-stack">
      <div className="hero-grid">
        <VideoPanel videoUrl={videoUrl} event={event} />
        <LatestDetection event={event} onOpen={onOpen} />
      </div>
      <MetricGrid />
      <RecentTable onOpen={onOpen} />
    </div>
  );
}

function VideoPanel({ videoUrl, event }) {
  const containerRef = useRef(null);
  const [isFs, setIsFs] = useState(false);

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

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-header-left">
          <div className="live-dot" />
          <span style={{ fontSize: ".875rem", fontWeight: 700 }}>Video en vivo</span>
        </div>
        <span className="stream-tag">MJPEG /api/cameras/main/stream</span>
      </div>
      <div className="video-frame" ref={containerRef}>
        <img
          src={videoUrl}
          alt="Video en vivo"
          onError={e => { e.target.src = event?.images?.frame ?? ""; }}
        />
        <div className="vbox">
          <span className="vbox-label">ID: 18 | Auto</span>
        </div>
        <div className="pbox">Placa</div>
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
          <img src={event.images.frame} alt="Vehículo detectado" />
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
        { icon: Car,          label: "Detectados hoy",   value: todayEvents.length || 128, tone: "blue",  sub: "vehículos" },
        { icon: ShieldAlert,  label: "Infracciones hoy", value: violations.length  || 15,  tone: "red",   sub: "eventos" },
        { icon: Gauge,        label: "Vel. promedio",    value: `${avgSpeed || 43} km/h`,  tone: "amber", sub: "hoy" },
        { icon: ClipboardList,label: "Pendientes",       value: pending.length     || 7,   tone: "rose",  sub: "de revisión" },
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
  const excess = event.speed - event.speedLimit;
  return (
    <div className="event-hero-strip">
      <div className="hero-top-row">
        <div>
          <div className={`hero-event-badge ${event.type}`}>
            <ShieldAlert size={12} /> {TYPE_LABEL[event.type]}
          </div>
          <div className="hero-evt-id">{event.id}</div>
          <div className="hero-subtitle">
            {event.vehicle?.brand} {event.vehicle?.model} · {event.vehicle?.ownerName} · {event.dateTime}
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

function HumanReviewBox({ event }) {
  const [placa, setPlaca]   = useState(event.plateValidated ?? event.plateOcr);
  const [motivo, setMotivo] = useState("");
  const [status, setStatus] = useState("idle"); // idle | loading | ok | error
  const [msg, setMsg]       = useState("");

  // El db_id viene del backend (UUID real); si no hay, usa el id display
  const dbId = event.db_id ?? event.id;

  const call = async (action) => {
    setStatus("loading");
    setMsg("");
    try {
      const res = await fetch(`${API}/api/events/${dbId}/${action}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          placa_corregida: placa !== event.plateOcr ? placa : null,
          motivo: motivo || null,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Error del servidor");
      setStatus("ok");
      if (action === "approve") {
        setMsg(data.email_sent > 0
          ? `Sanción aprobada. Correo enviado a ${event.vehicle?.ownerEmail}.`
          : "Sanción aprobada. Correo en cola (verificar SMTP en .env)."
        );
      } else {
        setMsg("Evento rechazado correctamente.");
      }
    } catch (e) {
      setStatus("error");
      setMsg(e.message);
    }
  };

  if (status === "ok") {
    return (
      <div className="human-review-box">
        <div className="human-review-header" style={{ background: "#16a34a" }}>
          <Check size={16} /> Acción registrada
        </div>
        <div className="human-review-body">
          <p style={{ fontSize: ".875rem", color: "#15803d", fontWeight: 600 }}>{msg}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="human-review-box">
      <div className="human-review-header">
        <ShieldAlert size={16} /> Revisión humana requerida
      </div>
      <div className="human-review-body">
        <div className="form-field">
          <label className="form-label">Placa validada</label>
          <input className="form-input" value={placa} onChange={e => setPlaca(e.target.value.toUpperCase())} />
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
          <button
            className="btn btn-approve btn-md"
            disabled={status === "loading"}
            onClick={() => call("approve")}
          >
            <Check size={15} /> {status === "loading" ? "Enviando…" : "Aprobar y notificar"}
          </button>
          <button
            className="btn btn-reject btn-md"
            disabled={status === "loading"}
            onClick={() => call("reject")}
          >
            <X size={15} /> Rechazar
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─── Tab: Resumen ───────────────────────────────────────── */

function ResumenTab({ event }) {
  const [modalOpen, setModalOpen] = useState(false);
  const over   = event.speed > event.speedLimit;
  const excess = event.speed - event.speedLimit;

  return (
    <div className="tab-panel">
      <div className="resumen-grid">
        <div className="resumen-left">
          {/* Evidencia */}
          <div className="card">
            <div className="card-header">
              <div className="card-header-left"><Eye size={16} /><h2>Evidencia del evento</h2></div>
            </div>
            <div className="evidence-images">
              <div className="main-img-wrap">
                <img src={event.images.frame} alt="Vehículo detectado" />
              </div>
              <button className="plate-img-wrap" onClick={() => setModalOpen(true)}>
                <img src={event.images.plate} alt="Crop de placa" />
                <span className="plate-img-label"><Maximize2 size={13} /> Ampliar placa</span>
              </button>
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
              <div className="card-header"><div className="card-header-left"><Car size={16} /><h2>Vehículo</h2></div></div>
              <dl className="info-list">
                {[
                  { label: "Propietario",   val: event.vehicle?.ownerName },
                  { label: "Correo",        val: event.vehicle?.ownerEmail },
                  { label: "Marca",         val: event.vehicle?.brand },
                  { label: "Modelo",        val: event.vehicle?.model },
                  { label: "Color",         val: event.vehicle?.color },
                  { label: "Reincidencias", val: `${event.recurrenceCount} previas` },
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
                { label: "Sanción sugerida",  val: event.suggestedPenaltyDays > 0 ? `${event.suggestedPenaltyDays} días` : "Sin sanción" },
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
            <HumanReviewBox event={event} />
          )}
        </div>
      </div>

      {modalOpen && (
        <div className="modal-overlay" onClick={() => setModalOpen(false)}>
          <div className="modal-card" onClick={e => e.stopPropagation()}>
            <button className="btn-icon modal-close" onClick={() => setModalOpen(false)}><X size={16} /></button>
            <div className="modal-card-body">
              <img src={event.images.plate} alt="Placa ampliada" />
              <strong>{event.plateValidated}</strong>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Tab: Visión ────────────────────────────────────────── */

function VisionTab({ event }) {
  const [showTech, setShowTech] = useState(false);
  const cv = event.computerVision;

  const steps = [
    { label: "Vehículo detectado", pct: cv.vehicleDetection.confidence },
    { label: "Placa detectada",    pct: cv.plateDetection.confidence },
    { label: "Enderezado",         pct: 0.98 },
    { label: "Filtros aplicados",  pct: 0.93 },
    { label: "Segmentación",       pct: 0.91 },
    { label: "OCR exitoso",        pct: event.ocrConfidence },
  ];

  const procImages = [
    { num: 1, label: "Vehículo detectado", src: event.images.frame },
    { num: 2, label: "Placa detectada",    src: event.images.plate },
    { num: 3, label: "Enderezado",         src: event.images.plate },
    { num: 4, label: "Filtros aplicados",  src: event.images.plate },
    { num: 5, label: "Segmentación",       src: event.images.plate },
    { num: 6, label: "OCR exitoso",        src: event.images.plate },
  ];

  const chars = (event.plateValidated ?? "").replace("-", "").split("");

  return (
    <div className="tab-panel">
      <div className="card">
        <div className="card-header">
          <div className="card-header-left"><Cpu size={16} /><h2>Etapas de procesamiento</h2></div>
          <span style={{ fontSize: ".75rem", color: "var(--muted)" }}>Proceso completado · 0.84 s</span>
        </div>
        <div className="pipeline-steps">
          {steps.map((s, i) => (
            <div key={s.label} className="pipeline-step">
              {i < steps.length - 1 && <ChevronRight className="step-arrow" size={16} />}
              <div className="step-num-icon done">{i + 1}</div>
              <div className="step-name">{s.label}</div>
              <div className="step-conf">{Math.round(s.pct * 100)}%</div>
              <div className="step-bar"><div className="step-bar-fill" style={{ width: `${Math.round(s.pct * 100)}%` }} /></div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-header"><div className="card-header-left"><Eye size={16} /><h2>Visualización del proceso</h2></div></div>
        <div className="card-body" style={{ display: "grid", gridTemplateColumns: "1fr 260px", gap: 16 }}>
          <div className="process-images-grid">
            {procImages.map(({ num, label, src }) => (
              <div key={num} className="proc-img-card">
                <img src={src} alt={label} />
                <div className="proc-img-label">
                  <div className="proc-num">{num}</div>{label}
                </div>
              </div>
            ))}
          </div>

          <div style={{ background: "var(--bg)", borderRadius: 10, border: "1px solid var(--border)", padding: 16, display: "grid", gap: 14 }}>
            <div style={{ fontSize: ".72rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em", color: "var(--muted)" }}>Resultado OCR</div>
            <div className="ocr-plate-display">
              <div className="ocr-plate-text">{event.plateValidated}</div>
              <div className="ocr-check-badge"><Check size={12} /></div>
            </div>
            <div>
              <div className="ocr-conf-row">
                <span className="ocr-conf-label">Confianza OCR</span>
                <span className="ocr-conf-value">{Math.round(event.ocrConfidence * 100)}%</span>
              </div>
              <div className="conf-bar" style={{ marginTop: 6 }}>
                <div className="conf-bar-fill" style={{ width: `${Math.round(event.ocrConfidence * 100)}%` }} />
              </div>
            </div>
            <div className="ocr-stats">
              <div className="ocr-stat"><span className="ocr-stat-val">{chars.length}</span><span className="ocr-stat-lab">Caract.</span></div>
              <div className="ocr-stat"><span className="ocr-stat-val">{event.ocrConfidence.toFixed(2)}</span><span className="ocr-stat-lab">Conf.</span></div>
              <div className="ocr-stat"><span className="ocr-stat-val">0.84s</span><span className="ocr-stat-lab">Tiempo</span></div>
              <div className="ocr-stat"><span className="ocr-stat-val">CNN</span><span className="ocr-stat-lab">Modelo</span></div>
            </div>
            <div>
              <div style={{ fontSize: ".72rem", fontWeight: 700, color: "var(--muted)", marginBottom: 6, textTransform: "uppercase" }}>Por carácter</div>
              <div className="char-grid">
                {chars.map((ch, i) => (
                  <div key={i} className="char-badge">
                    <span className="char-badge-ch">{ch}</span>
                    <span className="char-badge-pct">{Math.round((event.ocrConfidence - i * 0.005) * 100)}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="tech-collapsible">
          <button className="tech-toggle" onClick={() => setShowTech(v => !v)}>
            <span><Info size={14} style={{ marginRight: 6, verticalAlign: "middle" }} />Información técnica</span>
            <ChevronRight size={14} style={{ transform: showTech ? "rotate(90deg)" : "none", transition: "transform .2s" }} />
          </button>
          {showTech && (
            <dl className="tech-details">
              {[
                { label: "Tamaño original",    val: "1920 × 1080 px" },
                { label: "ROI placa",          val: cv.plateDetection.bbox },
                { label: "Ángulo corrección",  val: "-2.35°" },
                { label: "Segmentación",       val: cv.segmentation },
                { label: "Filtros",            val: cv.filters },
                { label: "Modelo OCR",         val: "CRNN + Attention" },
              ].map(({ label, val }) => (
                <div key={label} className="tech-item"><dt>{label}</dt><dd>{val}</dd></div>
              ))}
            </dl>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─── Triangle SVG ───────────────────────────────────────── */

function TriangleSVG({ domain, points, color = "#c12028", currentVal = null }) {
  const [dMin, dMax] = domain;
  const range = dMax - dMin || 1;
  const W = 200, H = 60, PAD = 8;
  const drawW = W - PAD * 2;
  const toX = v => PAD + ((v - dMin) / range) * drawW;
  const [a, b, c] = points;
  const pathD = `M${toX(a)},${H - 4} L${toX(b)},4 L${toX(c)},${H - 4} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="triangle-chart" style={{ overflow: "visible" }}>
      <line x1={PAD} y1={H - 4} x2={W - PAD} y2={H - 4} stroke="#e2e8f0" strokeWidth={1} />
      <path d={pathD} fill={color} fillOpacity={0.18} stroke={color} strokeWidth={2} strokeLinejoin="round" />
      {currentVal !== null && currentVal >= dMin && currentVal <= dMax && (
        <line x1={toX(currentVal)} y1={2} x2={toX(currentVal)} y2={H - 2}
          stroke="#f59e0b" strokeWidth={2} strokeDasharray="3,2" />
      )}
    </svg>
  );
}

/* ─── Tab: Sistema difuso ────────────────────────────────── */

function FuzzyTab({ event }) {
  const fz = event.fuzzySystem;
  const isHigh = ["alto", "critico"].includes(event.riskLevel);
  const defuzzVal = isHigh ? 72 : 22;

  const rules = [
    { id: "R1", desc: "Si exceso es alto Y OCR es alta → riesgo es alto",     activation: 0.82, level: "high" },
    { id: "R2", desc: "Si exceso es moderado Y reincidencia es media → riesgo es alto", activation: 0.65, level: "high" },
    { id: "R3", desc: "Si exceso es alto Y OCR es media → riesgo es alto",    activation: 0.48, level: "high" },
    { id: "R4", desc: "Si exceso es bajo Y OCR es alta → riesgo es bajo",     activation: 0.12, level: "low" },
    { id: "R5", desc: "Si exceso moderado Y reincidencia baja → riesgo medio", activation: 0.08, level: "medium" },
  ];

  return (
    <div className="tab-panel">
      <div className="card">
        <div className="card-header">
          <div className="card-header-left"><Zap size={16} color="var(--uta-red)" /><h2>Evaluación del sistema difuso</h2></div>
          <span style={{ fontSize: ".75rem", color: "var(--muted)" }}>Inferencia Mamdani · mín-max</span>
        </div>
        <div className="fuzzy-three-col">
          {/* Col 1: Entradas */}
          <div>
            <div className="fuzzy-col-label"><span className="fuzzy-col-num">1</span> Entradas</div>
            {[
              { name: "Exceso de velocidad", icon: Gauge,    cls: "speed", color: "#c12028",
                domain: [0,30], pts: [4,10,18], val: fz.speedExcess, disp: `${fz.speedExcess} km/h`,
                range: "0–30 km/h", mem: fz.speedMembership },
              { name: "Confianza OCR",       icon: FileText, cls: "ocr",   color: "#2563eb",
                domain: [0,1],  pts: [0.6,0.85,1.0], val: event.ocrConfidence, disp: event.ocrConfidence.toFixed(2),
                range: "0–1",   mem: fz.ocrMembership },
              { name: "Reincidencia",        icon: UserRound,cls: "recur", color: "#d97706",
                domain: [0,1],  pts: [0.3,0.55,0.8], val: 0.58, disp: `${event.recurrenceCount} casos`,
                range: "0–1",   mem: fz.recurrenceMembership },
            ].map(({ name, icon: Icon, cls, color, domain, pts, val, disp, range, mem }) => (
              <div key={name} className="fuzzy-input-var">
                <div className="fuzzy-var-header">
                  <div className={`fuzzy-var-icon ${cls}`}><Icon size={16} /></div>
                  <div>
                    <div className="fuzzy-var-name">{name}</div>
                    <div style={{ fontSize: ".7rem", color: "var(--muted)" }}>Rango {range}</div>
                  </div>
                </div>
                <TriangleSVG domain={domain} points={pts} color={color} currentVal={val} />
                <div className="fuzzy-var-body">
                  <div>
                    <div className="fuzzy-var-value">{disp}</div>
                    <div className="fuzzy-var-range">Pertenencia</div>
                  </div>
                  <span className={`membership-badge ${mem?.split(" ")[0] ?? ""}`}>{mem?.split(" ")[0]}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Col 2: Reglas */}
          <div>
            <div className="fuzzy-col-label"><span className="fuzzy-col-num">2</span> Reglas activadas</div>
            <table className="rules-table">
              <thead><tr><th>Regla</th><th>Descripción</th><th style={{ minWidth: 90 }}>Activación</th></tr></thead>
              <tbody>
                {rules.map(r => (
                  <tr key={r.id}>
                    <td><div className="rule-id">{r.id}</div></td>
                    <td><div className="rule-desc">{r.desc}</div></td>
                    <td>
                      <div style={{ fontWeight: 700, fontSize: ".82rem", marginBottom: 4 }}>{r.activation.toFixed(2)}</div>
                      <div className="rule-activation-bar">
                        <div className={`rule-activation-fill activation-fill-${r.level === "high" ? "high" : r.level === "medium" ? "medium" : "low"}`}
                          style={{ width: `${Math.round(r.activation * 100)}%` }} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="rules-meta">
              <div className="rules-meta-item"><GitBranch size={12} /> Método: <strong>Mamdani (mín-max)</strong></div>
              <div className="rules-meta-item"><Zap size={12} /> Defuzz.: <strong>Centroide (centroid)</strong></div>
            </div>
          </div>

          {/* Col 3: Resultado */}
          <div>
            <div className="fuzzy-col-label"><span className="fuzzy-col-num">3</span> Resultado final</div>
            <div className={`fuzzy-result-risk${isHigh ? "" : " normal"}`}>
              <div className={`risk-shield${isHigh ? "" : " normal"}`}><ShieldAlert size={26} /></div>
              <div className={`risk-level-label${isHigh ? "" : " normal"}`}>{event.riskLevel?.toUpperCase()}</div>
              <div className="risk-membership">Grado de pertenencia: 0.78</div>
            </div>
            <div className="dist-bar-wrap">
              <div className="dist-bar-label">Distribución del riesgo</div>
              <div className="dist-bar">
                <div className="dist-zone low"  style={{ width: "33%" }} />
                <div className="dist-zone mid"  style={{ width: "34%" }} />
                <div className="dist-zone high" style={{ width: "33%" }} />
                <div className="dist-marker" style={{ left: `${defuzzVal}%` }} />
              </div>
              <div className="dist-labels"><span>Bajo</span><span>Medio</span><span>Alto</span></div>
            </div>
            {event.suggestedPenaltyDays > 0 ? (
              <div className="penalty-card">
                <ClipboardList size={28} color="var(--uta-red)" />
                <div>
                  <div className="penalty-days">{event.suggestedPenaltyDays}</div>
                  <div className="penalty-unit">días de suspensión sugeridos</div>
                </div>
              </div>
            ) : (
              <div className="penalty-card">
                <Check size={28} color="var(--green)" />
                <div>
                  <div className="penalty-days" style={{ color: "var(--green)", fontSize: "1rem" }}>Sin sanción</div>
                  <div className="penalty-unit">dentro de parámetros</div>
                </div>
              </div>
            )}
            <div className="decision-basis">
              <Info size={14} style={{ flexShrink: 0, marginTop: 1 }} />
              <span><strong>Base de decisión:</strong> {fz.activatedRules?.[0] ?? "Evaluación del sistema difuso completada."}</span>
            </div>
          </div>
        </div>
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
      recipient: e.vehicle?.ownerEmail ?? "—",
      subject: e.type === "normal"
        ? "Conducción responsable en campus UTA"
        : `Infracción de tránsito detectada — ${e.plateValidated}`,
      status: e.notificationStatus,
    }));

  return (
    <div className="view-stack">
      <div><h1 style={{ fontSize: "1.75rem" }}>Notificaciones</h1>
        <p style={{ color: "var(--muted)", fontSize: ".9rem", marginTop: 5 }}>Correos enviados o pendientes para propietarios.</p>
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
                {n.type === "felicitacion"
                  ? "Estimado propietario, su vehículo fue detectado cumpliendo las normas de tránsito del campus UTA. ¡Gracias por su conducción responsable!"
                  : "Estimado propietario, se ha registrado una infracción de tránsito en el campus universitario. Por favor comuníquese con la administración."}
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

function SettingsView() {
  return (
    <div className="view-stack">
      <div><h1 style={{ fontSize: "1.75rem" }}>Configuración</h1>
        <p style={{ color: "var(--muted)", fontSize: ".9rem", marginTop: 5 }}>Parámetros del sistema de monitoreo vehicular.</p>
      </div>
      <div className="card">
        <div style={{ display: "grid", gap: 14, maxWidth: 600, padding: 18 }}>
          {[
            { label: "Endpoint de video (MJPEG)", val: "/api/cameras/main/stream" },
            { label: "WebSocket",                 val: "/ws" },
            { label: "Límite de velocidad campus", val: "50 km/h" },
            { label: "Umbral confianza OCR",       val: "0.85" },
          ].map(({ label, val }) => (
            <div key={label} style={{ display: "grid", gap: 5 }}>
              <label style={{ fontSize: ".82rem", fontWeight: 700 }}>{label}</label>
              <input className="form-input" defaultValue={val} />
            </div>
          ))}
          <button className="btn btn-primary btn-md" style={{ width: "fit-content" }}>Guardar parámetros</button>
        </div>
      </div>
    </div>
  );
}
