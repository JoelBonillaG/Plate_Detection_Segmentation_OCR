import {
  Activity,
  Bell,
  Camera,
  Car,
  CheckCircle2,
  Clock3,
  Database,
  Eye,
  Gauge,
  LayoutDashboard,
  ListFilter,
  Mail,
  Menu,
  Search,
  Settings,
  ShieldAlert,
  SlidersHorizontal,
  UserRound,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { events, notifications, stats, systemStatus } from "./data/mockData";

const navItems = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "events", label: "Eventos", icon: Car },
  { id: "notifications", label: "Notificaciones", icon: Bell },
  { id: "statistics", label: "Estadisticas", icon: Activity },
  { id: "settings", label: "Configuracion", icon: Settings },
];

const typeLabels = {
  normal: "Normal",
  advertencia: "Advertencia",
  infraccion: "Infraccion",
  grave: "Grave",
};

const reviewLabels = {
  automatica: "Automatica",
  pendiente: "Pendiente",
  aprobado: "Aprobado",
  rechazado: "Rechazado",
};

function App() {
  const [activeView, setActiveView] = useState("dashboard");
  const [selectedEventId, setSelectedEventId] = useState(events[0].id);
  const [query, setQuery] = useState("");
  const selectedEvent = events.find((event) => event.id === selectedEventId) ?? events[0];

  const filteredEvents = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return events;
    return events.filter((event) =>
      [event.plateOcr, event.plateValidated, event.type, event.reviewStatus, event.id]
        .join(" ")
        .toLowerCase()
        .includes(normalized)
    );
  }, [query]);

  return (
    <div className="app-shell">
      <Sidebar activeView={activeView} setActiveView={setActiveView} />
      <main className="main-area">
        <Topbar />
        {activeView === "dashboard" && (
          <Dashboard selectedEvent={selectedEvent} setSelectedEventId={setSelectedEventId} />
        )}
        {activeView === "events" && (
          <EventsView
            filteredEvents={filteredEvents}
            query={query}
            setQuery={setQuery}
            selectedEvent={selectedEvent}
            setSelectedEventId={setSelectedEventId}
          />
        )}
        {activeView === "notifications" && <NotificationsView />}
        {activeView === "statistics" && <StatisticsView />}
        {activeView === "settings" && <SettingsView />}
      </main>
    </div>
  );
}

function Sidebar({ activeView, setActiveView }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">
          <Car size={26} />
        </div>
        <div>
          <strong>Monitoreo vehicular</strong>
          <span>Universidad</span>
        </div>
      </div>
      <button className="icon-button menu-button" type="button" aria-label="Abrir menu">
        <Menu size={22} />
      </button>
      <nav className="nav-list" aria-label="Principal">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <button
              className={activeView === item.id ? "nav-item active" : "nav-item"}
              key={item.id}
              type="button"
              onClick={() => setActiveView(item.id)}
            >
              <Icon size={20} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>
      <div className="sidebar-footer">
        <div className="seal">U</div>
        <strong>Campus inteligente</strong>
        <span>Monitoreo y fiscalizacion vial</span>
        <small>2026</small>
      </div>
    </aside>
  );
}

function Topbar() {
  return (
    <header className="topbar">
      <StatusPill icon={CheckCircle2} label={systemStatus.system} value="Funcionando" tone="green" />
      <StatusPill icon={Camera} label={systemStatus.camera} value="IP/celular" tone="cyan" />
      <StatusPill icon={Database} label={systemStatus.backend} value="/ws listo" tone="blue" />
      <StatusPill icon={Gauge} label="FPS" value={systemStatus.fps} tone="red" />
      <StatusPill icon={Clock3} label="Hora actual" value={systemStatus.currentTime} tone="neutral" />
      <div className="admin-chip">
        <UserRound size={28} />
        <div>
          <strong>Administrador</strong>
          <span>admin@uni.edu</span>
        </div>
      </div>
    </header>
  );
}

function StatusPill({ icon: Icon, label, value, tone }) {
  return (
    <div className={`status-pill ${tone}`}>
      <Icon size={20} />
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function Dashboard({ selectedEvent, setSelectedEventId }) {
  return (
    <section className="view-stack">
      <div className="hero-grid">
        <VideoPanel selectedEvent={selectedEvent} />
        <LatestDetection event={selectedEvent} />
      </div>
      <MetricGrid />
      <RecentHistory setSelectedEventId={setSelectedEventId} />
      <EventDetail event={selectedEvent} compact />
    </section>
  );
}

function VideoPanel({ selectedEvent }) {
  return (
    <article className="panel video-panel">
      <div className="panel-title">
        <span className="live-dot" />
        <h2>Video en vivo</h2>
        <span className="stream-label">MJPEG /video_feed</span>
      </div>
      <div className="video-frame">
        <img src={selectedEvent.images.frame} alt="Frame de vehiculo detectado" />
        <div className="vehicle-box">
          <span>ID: 18 | Auto</span>
        </div>
        <div className="plate-box">Placa</div>
      </div>
    </article>
  );
}

function LatestDetection({ event }) {
  return (
    <article className="panel latest-panel">
      <div className="panel-title">
        <Car size={21} />
        <h2>Ultima deteccion</h2>
      </div>
      <div className="latest-content">
        <img src={event.images.plate} alt="Crop de placa detectada" />
        <dl className="definition-list">
          <div>
            <dt>Placa OCR</dt>
            <dd>{event.plateOcr}</dd>
          </div>
          <div>
            <dt>Velocidad</dt>
            <dd className={event.speed > event.speedLimit ? "danger-text" : "success-text"}>{event.speed} km/h</dd>
          </div>
          <div>
            <dt>Limite</dt>
            <dd>{event.speedLimit} km/h</dd>
          </div>
          <div>
            <dt>Estado</dt>
            <dd>{typeLabels[event.type]}</dd>
          </div>
        </dl>
      </div>
      <div className={`speed-callout ${event.type}`}>
        <Gauge size={42} />
        <div>
          <strong>{event.speed} km/h</strong>
          <span>{event.speed > event.speedLimit ? "Exceso de velocidad" : "Dentro del limite"}</span>
        </div>
      </div>
    </article>
  );
}

function MetricGrid() {
  return (
    <div className="metric-grid">
      <MetricCard icon={Car} label="Vehiculos detectados" value={stats.detectedToday} accent="blue" />
      <MetricCard icon={ShieldAlert} label="Infracciones detectadas" value={stats.violationsToday} accent="red" />
      <MetricCard icon={Gauge} label="Velocidad promedio" value={`${stats.averageSpeed} km/h`} accent="amber" />
      <MetricCard icon={ListFilter} label="Pendientes de revision" value={stats.pendingReview} accent="rose" />
    </div>
  );
}

function MetricCard({ icon: Icon, label, value, accent }) {
  return (
    <article className={`metric-card ${accent}`}>
      <Icon size={34} />
      <div>
        <strong>{value}</strong>
        <span>{label}</span>
        <small>Hoy</small>
      </div>
    </article>
  );
}

function RecentHistory({ setSelectedEventId }) {
  return (
    <article className="panel">
      <div className="panel-title space-between">
        <div className="title-row">
          <Clock3 size={20} />
          <h2>Historial reciente</h2>
        </div>
        <button className="ghost-button" type="button">
          Ver todos
        </button>
      </div>
      <EventTable rows={events.slice(0, 5)} setSelectedEventId={setSelectedEventId} />
    </article>
  );
}

function EventsView({ filteredEvents, query, setQuery, selectedEvent, setSelectedEventId }) {
  return (
    <section className="view-stack">
      <div className="view-heading">
        <div>
          <span className="eyebrow">Gestion operativa</span>
          <h1>Eventos detectados</h1>
          <p>Consulta, filtra y revisa cada deteccion antes de aprobar una infraccion.</p>
        </div>
        <button className="primary-button" type="button">
          <SlidersHorizontal size={18} />
          Filtros avanzados
        </button>
      </div>
      <div className="filter-bar">
        <Search size={18} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Buscar por placa, estado o ID"
        />
      </div>
      <article className="panel">
        <EventTable rows={filteredEvents} setSelectedEventId={setSelectedEventId} />
      </article>
      <EventDetail event={selectedEvent} />
    </section>
  );
}

function EventTable({ rows, setSelectedEventId }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Hora</th>
            <th>Placa</th>
            <th>Velocidad</th>
            <th>Limite</th>
            <th>Evento</th>
            <th>Revision</th>
            <th>Acciones</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((event) => (
            <tr key={event.id}>
              <td>{event.dateTime.split(" ")[1]}</td>
              <td>{event.plateValidated}</td>
              <td className={event.speed > event.speedLimit ? "danger-text" : "success-text"}>{event.speed} km/h</td>
              <td>{event.speedLimit} km/h</td>
              <td>
                <span className={`badge ${event.type}`}>{typeLabels[event.type]}</span>
              </td>
              <td>{reviewLabels[event.reviewStatus]}</td>
              <td>
                <button className="icon-button" type="button" onClick={() => setSelectedEventId(event.id)} aria-label="Ver detalle">
                  <Eye size={18} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EventDetail({ event, compact = false }) {
  return (
    <article className={compact ? "detail-area compact" : "detail-area"}>
      <div className="detail-header">
        <div>
          <span className="eyebrow">Detalle del evento</span>
          <h2>{event.id} · {event.plateValidated}</h2>
        </div>
        <span className={`badge ${event.type}`}>{typeLabels[event.type]}</span>
      </div>
      <div className="detail-grid">
        <section className="detail-card summary-card">
          <h3>Resumen</h3>
          <dl className="definition-list">
            <div><dt>Placa OCR</dt><dd>{event.plateOcr}</dd></div>
            <div><dt>Placa validada</dt><dd>{event.plateValidated}</dd></div>
            <div><dt>Velocidad</dt><dd>{event.speed} km/h</dd></div>
            <div><dt>Limite</dt><dd>{event.speedLimit} km/h</dd></div>
            <div><dt>Riesgo</dt><dd>{event.riskLevel}</dd></div>
            <div><dt>Fecha</dt><dd>{event.dateTime}</dd></div>
          </dl>
        </section>
        <section className="detail-card evidence-card">
          <h3>Evidencia</h3>
          <div className="evidence-grid">
            <img src={event.images.frame} alt="Frame completo del vehiculo" />
            <img src={event.images.plate} alt="Crop de placa" />
          </div>
        </section>
        <ComputerVisionSection data={event.computerVision} confidence={event.ocrConfidence} />
        <FuzzySection data={event.fuzzySystem} />
        <HumanValidation event={event} />
        <AuditSection rows={event.audit} />
      </div>
    </article>
  );
}

function ComputerVisionSection({ data, confidence }) {
  const steps = [
    ["Vehiculo detectado", `${data.vehicleDetection.confidence * 100}% · ${data.vehicleDetection.bbox}`],
    ["Placa detectada", `${data.plateDetection.confidence * 100}% · ${data.plateDetection.bbox}`],
    ["Enderezado", data.rectification],
    ["Filtros", data.filters],
    ["Segmentacion", data.segmentation],
    ["OCR", `${data.ocr} · confianza ${(confidence * 100).toFixed(0)}%`],
  ];

  return (
    <section className="detail-card analysis-card">
      <h3>Vision por computadora</h3>
      <div className="timeline">
        {steps.map(([label, value], index) => (
          <div className="timeline-item" key={label}>
            <span>{index + 1}</span>
            <div>
              <strong>{label}</strong>
              <p>{value}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function FuzzySection({ data }) {
  return (
    <section className="detail-card analysis-card">
      <h3>Sistema difuso</h3>
      <div className="fuzzy-grid">
        <MiniMetric label="Exceso" value={`${data.speedExcess} km/h`} />
        <MiniMetric label="Velocidad" value={data.speedMembership} />
        <MiniMetric label="Reincidencia" value={data.recurrenceMembership} />
        <MiniMetric label="OCR" value={data.ocrMembership} />
        <MiniMetric label="Riesgo" value={data.risk} />
        <MiniMetric label="Sancion sugerida" value={data.suggestedPenalty} />
      </div>
      <div className="rules-list">
        {data.activatedRules.map((rule) => (
          <p key={rule}>{rule}</p>
        ))}
      </div>
    </section>
  );
}

function MiniMetric({ label, value }) {
  return (
    <div className="mini-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function HumanValidation({ event }) {
  return (
    <section className="detail-card validation-card">
      <h3>Validacion humana</h3>
      <div className="form-grid">
        <label>
          Placa validada
          <input defaultValue={event.plateValidated} />
        </label>
        <label>
          Motivo de correccion
          <textarea placeholder="Registrar motivo si se modifica la placa o el estado" />
        </label>
      </div>
      <div className="actions-row">
        <button className="primary-button" type="button">Aprobar sancion</button>
        <button className="secondary-button" type="button">Rechazar</button>
      </div>
    </section>
  );
}

function AuditSection({ rows }) {
  return (
    <section className="detail-card audit-card">
      <h3>Auditoria</h3>
      {rows.length === 0 ? (
        <p className="muted">Sin cambios manuales registrados.</p>
      ) : (
        rows.map((row) => (
          <div className="audit-entry" key={`${row.field}-${row.dateTime}`}>
            <strong>{row.user}</strong>
            <span>{`${row.field}: ${row.previousValue} -> ${row.newValue}`}</span>
            <small>{row.reason} · {row.dateTime}</small>
          </div>
        ))
      )}
    </section>
  );
}

function NotificationsView() {
  return (
    <section className="view-stack">
      <div className="view-heading">
        <div>
          <span className="eyebrow">Mensajeria</span>
          <h1>Notificaciones</h1>
          <p>Felicitaciones automaticas para eventos normales e infracciones luego de aprobacion.</p>
        </div>
      </div>
      <div className="notification-grid">
        {notifications.map((notification) => (
          <article className="notification-card" key={notification.id}>
            <Mail size={24} />
            <div>
              <strong>{notification.subject}</strong>
              <span>{notification.recipient}</span>
              <small>{notification.type} · {notification.status}</small>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function StatisticsView() {
  return (
    <section className="view-stack">
      <div className="view-heading">
        <div>
          <span className="eyebrow">Analitica</span>
          <h1>Estadisticas</h1>
          <p>Base lista para graficas por horario, reincidencias y nivel de riesgo.</p>
        </div>
      </div>
      <MetricGrid />
      <article className="panel empty-state">
        <Activity size={42} />
        <strong>Graficas proximas</strong>
        <span>La estructura ya separa eventos, riesgo, velocidad y notificaciones.</span>
      </article>
    </section>
  );
}

function SettingsView() {
  return (
    <section className="view-stack">
      <div className="view-heading">
        <div>
          <span className="eyebrow">Parametros</span>
          <h1>Configuracion</h1>
          <p>Limites de velocidad, camara, umbrales OCR y reglas difusas.</p>
        </div>
      </div>
      <article className="panel settings-panel">
        <label>
          Endpoint de video
          <input defaultValue="/video_feed" />
        </label>
        <label>
          WebSocket
          <input defaultValue="/ws" />
        </label>
        <label>
          Limite campus
          <input defaultValue="50 km/h" />
        </label>
        <button className="primary-button" type="button">
          Guardar parametros
        </button>
      </article>
    </section>
  );
}

export default App;
