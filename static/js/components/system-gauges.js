/**
 * System health gauges: CPU%, RAM%, Disk%, Temp.
 * Canvas sparkline for temperature history.
 */
import { el } from '../api.js';

export function mount(container) {
  container.innerHTML = '';
  container.className = 'system-gauges';

  const style = document.createElement('style');
  style.textContent = `
    .system-gauges { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 16px; }
    .gauge-card { text-align: center; padding: 12px; background: var(--bg-card); border-radius: 8px; border: 1px solid var(--border); }
    .gauge-label { font-size: .75rem; color: var(--text-muted); margin-bottom: 8px; }
    .gauge-value { font-size: 1.25rem; font-weight: 700; }
    #temp-sparkline { width: 100%; height: 60px; margin-top: 8px; }
  `;
  container.appendChild(style);

  const gauges = [
    { id: 'g-cpu',  label: 'CPU' },
    { id: 'g-ram',  label: 'RAM' },
    { id: 'g-disk', label: 'Disk' },
    { id: 'g-temp', label: 'Temp' },
  ];

  for (const g of gauges) {
    const card = el('div', '', { class: 'gauge-card' });
    card.appendChild(el('div', g.label, { class: 'gauge-label' }));
    card.appendChild(el('div', '—', { class: 'gauge-value', id: g.id }));
    container.appendChild(card);
  }

  // Sparkline canvas
  const sparkCard = el('div', '', { class: 'gauge-card', style: 'grid-column: 1/-1;' });
  sparkCard.appendChild(el('div', 'Temperature History (30 readings)', { class: 'gauge-label' }));
  const canvas = document.createElement('canvas');
  canvas.id = 'temp-sparkline';
  sparkCard.appendChild(canvas);
  container.appendChild(sparkCard);
}

export function update(stats) {
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };

  set('g-cpu',  `${stats.cpu_percent ?? '—'}%`);
  set('g-ram',  `${stats.ram_percent ?? '—'}%`);

  const diskPct = stats.disk_total_gb ? (stats.disk_used_gb / stats.disk_total_gb * 100).toFixed(0) : '—';
  set('g-disk', `${diskPct}%`);

  if (stats.temp_c !== null && stats.temp_c !== undefined) {
    const tempEl = document.getElementById('g-temp');
    if (tempEl) {
      tempEl.textContent = `${stats.temp_c}°C`;
      tempEl.style.color = stats.temp_c > 75 ? 'var(--color-danger)' :
                           stats.temp_c > 60 ? 'var(--color-warning)' : 'var(--color-success)';
    }
  } else {
    set('g-temp', 'N/A');
  }

  // Sparkline
  _drawSparkline(stats.temp_c_history || []);
}

function _drawSparkline(history) {
  const canvas = document.getElementById('temp-sparkline');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.offsetWidth || 300;
  const H = 60;
  canvas.width = W;
  canvas.height = H;

  ctx.clearRect(0, 0, W, H);
  if (history.length < 2) return;

  const temps = history.map(([, t]) => t ?? 0);
  const min = Math.min(...temps) - 5;
  const max = Math.max(...temps) + 5;
  const range = max - min || 1;

  ctx.strokeStyle = '#2563eb';
  ctx.lineWidth = 2;
  ctx.beginPath();

  temps.forEach((t, i) => {
    const x = (i / (temps.length - 1)) * W;
    const y = H - ((t - min) / range) * H;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
}
