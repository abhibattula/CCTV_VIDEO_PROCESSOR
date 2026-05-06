import { api, el } from '../api.js';
import * as gauges from '../components/system-gauges.js';
import { updateDiskWarning } from '../components/nav.js';

let _interval = null;

export async function mount(container) {
  container.innerHTML = '';
  const page = el('div', '', { class: 'page' });
  page.appendChild(el('h1', 'System Diagnostics', { class: 'page-title' }));

  const gaugeCard = el('div', '', { class: 'card', style: 'margin-bottom:16px;' });
  gaugeCard.appendChild(el('h2', 'Live Metrics', { class: 'card-title' }));
  const gaugeContainer = el('div', '');
  gaugeCard.appendChild(gaugeContainer);
  page.appendChild(gaugeCard);
  gauges.mount(gaugeContainer);

  const infoCard = el('div', '', { class: 'card' });
  infoCard.appendChild(el('h2', 'System Info', { class: 'card-title' }));
  const infoGrid = el('div', '', { id: 'sys-info', style: 'display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:.875rem;' });
  infoCard.appendChild(infoGrid);
  page.appendChild(infoCard);

  container.appendChild(page);

  async function refresh() {
    try {
      const stats = await api.system.stats();
      gauges.update(stats);
      updateDiskWarning(stats);

      const info = document.getElementById('sys-info');
      if (info) {
        info.innerHTML = '';
        const add = (k, v) => {
          info.appendChild(el('span', k, { style: 'font-weight:600;color:var(--text-muted);' }));
          info.appendChild(el('span', v));
        };
        const uptime = stats.uptime_s || 0;
        const d = Math.floor(uptime / 86400), h = Math.floor((uptime % 86400) / 3600), m = Math.floor((uptime % 3600) / 60);
        add('Uptime', `${d}d ${h}h ${m}m`);
        add('App Version', stats.app_version || '—');
        add('RAM Mode', stats.ram_mode || '—');
        add('RAM Used', `${stats.ram_used_mb} MB / ${stats.ram_total_mb} MB`);
        add('Disk Used', `${stats.disk_used_gb?.toFixed(1)} GB / ${stats.disk_total_gb?.toFixed(1)} GB`);
        add('Temperature', stats.temp_c !== null ? `${stats.temp_c}°C` : 'N/A');
      }
    } catch {}
  }

  await refresh();
  _interval = setInterval(refresh, 10000);
}

export function unmount() {
  clearInterval(_interval);
  _interval = null;
}
