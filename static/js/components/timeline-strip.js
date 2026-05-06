/**
 * Canvas-based timeline renderer. Responsive: 80px on touch, 48px on mouse (ISSUE-15).
 * Colors: --color-success for included, --color-muted for excluded.
 * Touch pan via swipe (4-hour windows on mobile).
 */

let _events = [];
let _sourceDuration = 0;
let _selectedIndex = -1;
let _onSelect = null;
let _canvas = null;
let _ctx = null;
let _isTouch = false;
let _viewStart = 0;  // seconds
let _viewWindow = 0; // seconds visible
let _touchStartX = 0;

const TICK_CONFIG = [
  { maxDuration: 43200, interval: 3600, fmt: h => `${h}h` },     // <12h: every 1h
  { maxDuration: 86400, interval: 10800, fmt: h => `${h}h` },    // <24h: every 3h
  { maxDuration: Infinity, interval: 21600, fmt: h => `${h}h` }, // 24h+: every 6h
];

export function mount(canvas, events, durationS, onSelect) {
  _canvas = canvas;
  _events = events;
  _sourceDuration = durationS;
  _onSelect = onSelect;
  _ctx = canvas.getContext('2d');

  _isTouch = window.matchMedia('(pointer: coarse)').matches;
  canvas.height = _isTouch ? 80 : 48;
  canvas.style.height = canvas.height + 'px';
  _viewWindow = _isTouch ? Math.min(durationS, 4 * 3600) : durationS;
  _viewStart = 0;

  // HiDPI support
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = canvas.height * dpr;
  _ctx.scale(dpr, dpr);
  canvas.style.width = rect.width + 'px';

  // Events
  canvas.addEventListener('click', _onClick);
  canvas.addEventListener('touchstart', _onTouchStart, { passive: true });
  canvas.addEventListener('touchend', _onTouchEnd, { passive: true });
  window.addEventListener('resize', _onResize);

  _draw();
}

export function updateEvents(events) {
  _events = events;
  _draw();
}

export function setSelected(index) {
  _selectedIndex = index;
  _draw();
}

export function unmount() {
  if (_canvas) {
    _canvas.removeEventListener('click', _onClick);
    _canvas.removeEventListener('touchstart', _onTouchStart);
    _canvas.removeEventListener('touchend', _onTouchEnd);
  }
  window.removeEventListener('resize', _onResize);
}

function _draw() {
  if (!_canvas || !_ctx) return;
  requestAnimationFrame(_render);
}

function _render() {
  if (!_canvas || !_ctx) return;
  const W = _canvas.offsetWidth;
  const H = _canvas.offsetHeight;
  _ctx.clearRect(0, 0, W, H);

  const style = getComputedStyle(document.documentElement);
  const colorSuccess = style.getPropertyValue('--color-success').trim() || '#16a34a';
  const colorMuted = style.getPropertyValue('--color-muted').trim() || '#6b7280';
  const colorSelected = '#f59e0b';
  const colorBg = style.getPropertyValue('--border').trim() || '#e2e8f0';

  const trackH = H - 16; // leave room for timestamp axis
  const viewEnd = _viewStart + _viewWindow;
  const totalW = W;

  // Background track
  _ctx.fillStyle = colorBg;
  _ctx.fillRect(0, 0, W, trackH);

  // Events
  for (let i = 0; i < _events.length; i++) {
    const ev = _events[i];
    const s = ev.start_s, e = ev.end_s;
    if (e < _viewStart || s > viewEnd) continue;

    const x1 = Math.max(0, ((s - _viewStart) / _viewWindow) * totalW);
    const x2 = Math.min(totalW, ((e - _viewStart) / _viewWindow) * totalW);
    const w = Math.max(_isTouch ? 12 : 4, x2 - x1);

    _ctx.fillStyle = i === _selectedIndex ? colorSelected :
                     ev.included ? colorSuccess : colorMuted;
    _ctx.fillRect(x1, 0, w, trackH);
  }

  // Timestamp axis
  _ctx.fillStyle = colorMuted;
  _ctx.font = '10px sans-serif';
  const cfg = TICK_CONFIG.find(c => _sourceDuration <= c.maxDuration) || TICK_CONFIG[2];
  for (let t = 0; t <= _sourceDuration; t += cfg.interval) {
    if (t < _viewStart || t > viewEnd) continue;
    const x = ((t - _viewStart) / _viewWindow) * totalW;
    const label = cfg.fmt(Math.round(t / 3600));
    _ctx.fillText(label, Math.max(0, x - 8), H - 2);
  }
}

function _onClick(e) {
  if (!_onSelect) return;
  const rect = _canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const t = _viewStart + (x / rect.width) * _viewWindow;
  _selectAt(t);
}

function _selectAt(t) {
  let best = -1, bestDist = Infinity;
  for (let i = 0; i < _events.length; i++) {
    const ev = _events[i];
    if (t >= ev.start_s && t <= ev.end_s) { best = i; break; }
    const dist = Math.min(Math.abs(t - ev.start_s), Math.abs(t - ev.end_s));
    if (dist < bestDist) { bestDist = dist; best = i; }
  }
  if (best >= 0) {
    _selectedIndex = best;
    _draw();
    _canvas.dispatchEvent(new CustomEvent('event-selected', { detail: { index: best }, bubbles: true }));
    if (_onSelect) _onSelect(best);
  }
}

function _onTouchStart(e) {
  _touchStartX = e.touches[0].clientX;
}

function _onTouchEnd(e) {
  const dx = e.changedTouches[0].clientX - _touchStartX;
  const threshold = 30; // px
  if (Math.abs(dx) < threshold) {
    // Tap — select event
    const rect = _canvas.getBoundingClientRect();
    const x = e.changedTouches[0].clientX - rect.left;
    const t = _viewStart + (x / rect.width) * _viewWindow;
    _selectAt(t);
    return;
  }
  // Swipe — pan view by 4h window
  const dir = dx < 0 ? 1 : -1;
  _viewStart = Math.max(0, Math.min(_sourceDuration - _viewWindow, _viewStart + dir * _viewWindow));
  _draw();
}

function _onResize() {
  if (!_canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = _canvas.getBoundingClientRect();
  _canvas.width = rect.width * dpr;
  _canvas.style.width = rect.width + 'px';
  if (_ctx) _ctx.scale(dpr, dpr);
  _draw();
}
