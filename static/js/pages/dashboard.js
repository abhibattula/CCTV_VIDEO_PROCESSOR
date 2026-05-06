import { api, el } from '../api.js';
import { navigate } from '../app.js';
import * as gauges from '../components/system-gauges.js';
import { updateDiskWarning } from '../components/nav.js';

let _interval = null;

export async function mount(container) {
  container.innerHTML = '';
  const page = el('div', '', { class: 'page' });

  const header = el('div', '', { class: 'page-header' });
  header.appendChild(el('h1', 'Dashboard', { class: 'page-title' }));
  const newBtn = el('a', '+ New Analysis Job', { href: '/jobs/new', class: 'btn btn-primary' });
  header.appendChild(newBtn);
  page.appendChild(header);

  // System gauges row
  const gaugeRow = el('div', '', { class: 'card', style: 'margin-bottom:16px;' });
  gaugeRow.appendChild(el('h2', 'System Status', { class: 'card-title' }));
  const gaugeContainer = el('div', '');
  gaugeRow.appendChild(gaugeContainer);
  page.appendChild(gaugeRow);
  gauges.mount(gaugeContainer);

  // Active job card
  const activeCard = el('div', '', { class: 'card', style: 'margin-bottom:16px;', id: 'active-job-card' });
  page.appendChild(activeCard);

  // Recent jobs
  const recentCard = el('div', '', { class: 'card' });
  recentCard.appendChild(el('h2', 'Recent Jobs', { class: 'card-title' }));
  const recentList = el('div', '', { id: 'recent-jobs' });
  recentCard.appendChild(recentList);
  page.appendChild(recentCard);

  container.appendChild(page);

  async function refresh() {
    try {
      const data = await api.dashboard();
      gauges.update(data.system);
      updateDiskWarning(data.system);
      _renderActiveJob(document.getElementById('active-job-card'), data.active_job);
      _renderRecentJobs(document.getElementById('recent-jobs'), data.recent_jobs);
    } catch {}
  }

  await refresh();
  _interval = setInterval(refresh, 10000);
}

export function unmount() {
  clearInterval(_interval);
  _interval = null;
}

function _renderActiveJob(container, job) {
  container.innerHTML = '';
  if (!job) {
    container.appendChild(el('p', 'No active job.', { style: 'color:var(--text-muted);' }));
    return;
  }
  container.appendChild(el('h2', 'Active Job', { class: 'card-title' }));
  container.appendChild(el('p', job.source_name));
  const pw = el('div', '', { class: 'progress-wrap', style: 'margin-top:8px;' });
  const pb = el('div', '', { class: 'progress-bar animated', style: `width:${(job.progress * 100).toFixed(0)}%` });
  pw.appendChild(pb);
  container.appendChild(pw);
  const link = el('a', 'View Details →', { href: `/jobs/${job.id}`, style: 'display:block;margin-top:8px;' });
  container.appendChild(link);
}

function _renderRecentJobs(container, jobs) {
  container.innerHTML = '';
  if (!jobs.length) {
    container.appendChild(el('p', 'No jobs yet.', { style: 'color:var(--text-muted);' }));
    return;
  }
  const table = el('table');
  const thead = el('thead');
  const hr = el('tr');
  for (const h of ['Source', 'Status', 'Created', 'Output']) hr.appendChild(el('th', h));
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el('tbody');
  for (const job of jobs) {
    const tr = el('tr', '', { style: 'cursor:pointer;', onclick: () => navigate(`/jobs/${job.id}`) });
    tr.appendChild(el('td', job.source_name));
    const statusCell = el('td');
    statusCell.appendChild(el('span', job.status, { class: `badge badge-${job.status}` }));
    tr.appendChild(statusCell);
    tr.appendChild(el('td', job.created_at ? job.created_at.slice(0, 16) : '—'));
    tr.appendChild(el('td', job.output_name || '—'));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  container.appendChild(table);
}
