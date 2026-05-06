/**
 * EventSource wrapper with auto-reconnect and typed event dispatch.
 */
export class SseClient {
  constructor() {
    this._es = null;
    this._handlers = {};
    this._reconnectDelay = 1000;
    this._stopped = false;
  }

  connect(url, handlers = {}) {
    this._handlers = handlers;
    this._stopped = false;
    this._url = url;
    this._open();
  }

  _open() {
    if (this._stopped) return;
    this._es = new EventSource(this._url);

    this._es.onmessage = (e) => {
      this._reconnectDelay = 1000; // reset backoff on success
      try {
        const msg = JSON.parse(e.data);
        const handler = this._handlers[msg.type];
        if (handler) handler(msg);
      } catch {}
    };

    this._es.onerror = () => {
      this._es.close();
      if (!this._stopped) {
        setTimeout(() => this._open(), this._reconnectDelay);
        this._reconnectDelay = Math.min(this._reconnectDelay * 2, 30000);
      }
    };
  }

  disconnect() {
    this._stopped = true;
    if (this._es) { this._es.close(); this._es = null; }
  }

  isConnected() {
    return this._es && this._es.readyState === EventSource.OPEN;
  }
}
