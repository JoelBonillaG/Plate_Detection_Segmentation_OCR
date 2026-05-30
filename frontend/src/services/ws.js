/**
 * WebSocket service — singleton connection to FastAPI /ws
 *
 * Protocol (JSON messages):
 *
 *  Backend → Frontend:
 *    { type: "event",  data: EventPayload }   — new vehicle detection
 *    { type: "status", data: StatusPayload }  — fps / camera state
 *    { type: "pong" }                         — keepalive reply
 *
 *  Frontend → Backend:
 *    { type: "ping" }                         — keepalive
 */

const WS_URL = import.meta.env.VITE_WS_URL ?? `ws://${window.location.hostname}:8000/ws`;
const PING_INTERVAL_MS  = 25_000;
const RECONNECT_BASE_MS = 2_000;
const RECONNECT_MAX_MS  = 30_000;

class WsService {
  #ws = null;
  #subscribers = new Map();   // topic → Set<callback>
  #pingTimer = null;
  #reconnectTimer = null;
  #reconnectDelay = RECONNECT_BASE_MS;
  #manualClose = false;

  connect() {
    if (this.#ws && this.#ws.readyState <= WebSocket.OPEN) return;
    this.#manualClose = false;
    this.#open();
  }

  disconnect() {
    this.#manualClose = true;
    clearTimeout(this.#reconnectTimer);
    clearInterval(this.#pingTimer);
    this.#ws?.close();
    this.#ws = null;
  }

  /**
   * Subscribe to a message type.
   * @param {string} type   — "event" | "status" | "connection"
   * @param {Function} cb   — callback(data)
   * @returns {Function}    — unsubscribe function
   */
  on(type, cb) {
    if (!this.#subscribers.has(type)) this.#subscribers.set(type, new Set());
    this.#subscribers.get(type).add(cb);
    return () => this.#subscribers.get(type)?.delete(cb);
  }

  get connected() {
    return this.#ws?.readyState === WebSocket.OPEN;
  }

  // ── private ─────────────────────────────────────────────

  #open() {
    try {
      this.#ws = new WebSocket(WS_URL);
    } catch {
      this.#scheduleReconnect();
      return;
    }

    this.#ws.onopen = () => {
      this.#reconnectDelay = RECONNECT_BASE_MS;
      this.#emit("connection", { connected: true });
      this.#startPing();
    };

    this.#ws.onmessage = ({ data }) => {
      try {
        const msg = JSON.parse(data);
        if (msg.type !== "pong") this.#emit(msg.type, msg.data ?? null);
      } catch { /* ignore malformed */ }
    };

    this.#ws.onclose = () => {
      clearInterval(this.#pingTimer);
      this.#emit("connection", { connected: false });
      if (!this.#manualClose) this.#scheduleReconnect();
    };

    this.#ws.onerror = () => this.#ws?.close();
  }

  #startPing() {
    clearInterval(this.#pingTimer);
    this.#pingTimer = setInterval(() => {
      if (this.#ws?.readyState === WebSocket.OPEN) {
        this.#ws.send(JSON.stringify({ type: "ping" }));
      }
    }, PING_INTERVAL_MS);
  }

  #scheduleReconnect() {
    clearTimeout(this.#reconnectTimer);
    this.#reconnectTimer = setTimeout(() => {
      this.#reconnectDelay = Math.min(this.#reconnectDelay * 1.5, RECONNECT_MAX_MS);
      this.#open();
    }, this.#reconnectDelay);
  }

  #emit(type, data) {
    this.#subscribers.get(type)?.forEach(cb => {
      try { cb(data); } catch { /* keep other subscribers alive */ }
    });
  }
}

export const wsService = new WsService();
