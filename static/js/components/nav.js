/**
 * Persistent sidebar navigation.
 * Renders once; checks disk_warn on every mount for all-pages banner (C3 fix).
 */
import { api, el } from '../api.js';

const NAV_ITEMS = [
  { href: '/',          label: 'Dashboard',     icon: '⊞' },
  { href: '/jobs/new',  label: 'New Job',        icon: '+' },
  { href: '/jobs',      label: 'Job Queue',      icon: '≡' },
  { href: '/reports',   label: 'Reports',        icon: '📊' },
  { href: '/settings',  label: 'Settings',       icon: '⚙' },
  { href: '/system',    label: 'System',         icon: '💻' },
  { href: '/audit',     label: 'Audit Log',      icon: '📋' },
];

let _diskBanner = null;

export function mount(container) {
  container.innerHTML = '';

  // Logo
  const logo = el('div', '', { class: 'sidebar-logo' });
  logo.appendChild(el('span', '📹'));
  logo.appendChild(el('span', 'CCTV Analyst'));
  container.appendChild(logo);

  // Nav links
  const nav = el('nav', '', { class: 'sidebar-nav' });
  for (const item of NAV_ITEMS) {
    const a = el('a', '', { href: item.href, class: 'nav-link' });
    a.appendChild(el('span', item.icon, { 'aria-hidden': 'true' }));
    a.appendChild(el('span', item.label));
    nav.appendChild(a);
  }
  container.appendChild(nav);

  // Check disk warning (C3 fix — checked on every mount, shown on all pages)
  _checkDiskWarning();
}

export function unmount() {}

export function updateDiskWarning(stats) {
  if (stats && stats.disk_warn) {
    _showDiskBanner(stats.disk_used_gb, stats.disk_total_gb);
  } else if (_diskBanner) {
    _diskBanner.remove();
    _diskBanner = null;
  }
}

async function _checkDiskWarning() {
  try {
    const stats = await api.system.stats();
    if (stats.disk_warn) {
      _showDiskBanner(stats.disk_used_gb, stats.disk_total_gb);
    }
  } catch {}
}

function _showDiskBanner(used, total) {
  if (_diskBanner) _diskBanner.remove();
  _diskBanner = el(
    'div',
    `⚠ Disk space low: ${used.toFixed(1)} GB / ${total.toFixed(1)} GB used`,
    { class: 'disk-warning-banner' },
  );
  const app = document.getElementById('app');
  if (app && app.parentNode) {
    app.parentNode.insertBefore(_diskBanner, app);
  }
}
