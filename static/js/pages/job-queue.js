import { api, el } from '../api.js';
import { navigate } from '../app.js';
import { toast } from '../components/toast.js';
import { modal } from '../components/modal.js';

let _interval = null;

export async function mount(container, params) {
  container.innerHTML = '';
  const page = el('div', '', { class: 'page' });

  const header = el('div', '', { class: 'page-header' });
  header.appendChild(el('h1', 'Job Queue', { class: 'page-title' }));
  header.appendChild(el('a', '+ New Job', { href: '/jobs/new', class: 'btn btn-primary' }));
  page.appendChild(header);

  const tableWrap = el('div', '', { class: 'card table-wrap' });
  const table = el('table');
  const thead = el('thead');
  const hr = el('tr');
  for (const h of ['Source', 'Status', 'Created', 'Progress', 'Events', 'Actions']) {
    hr.appendChild(el('th', h));
  }
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el('tbody', '', { id: 'jobs-tbody' });
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  page.appendChild(tableWrap);

  container.appendChild(page);

  async function refresh() {
    try {
      const data = await api.jobs.list({ limit: 100 });
      _renderRows(data.jobs);
    } catch {}
  }

  await refresh();
  _interval = setInterval(refresh, 5000);
}

export function unmount() {
  clearInterval(_interval);
  _interval = null;
}

function _renderRows(jobs) {
  const tbody = document.getElementById('jobs-tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  for (const job of jobs) {
    const tr = el('tr', '', { style: 'cursor:pointer;' });
    tr.addEventListener('click', (e) => {
      if (e.target.closest('button')) return;
      navigate(`/jobs/${job.id}`);
    });

    tr.appendChild(el('td', job.source_name));

    const statusCell = el('td');
    statusCell.appendChild(el('span', job.status, { class: `badge badge-${job.status}` }));
    tr.appendChild(statusCell);

    tr.appendChild(el('td', job.created_at ? job.created_at.slice(0, 16) : '—'));

    const progCell = el('td');
    if (['detecting', 'exporting', 'running'].includes(job.status)) {
      const pw = el('div', '', { class: 'progress-wrap', style: 'width:100px;' });
      const pb = el('div', '', { class: 'progress-bar', style: `width:${((job.progress || 0) * 100).toFixed(0)}%` });
      pw.appendChild(pb);
      progCell.appendChild(pw);
    } else {
      progCell.appendChild(el('span', job.status === 'completed' ? '100%' : '—'));
    }
    tr.appendChild(progCell);

    tr.appendChild(el('td', job.event_count != null ? String(job.event_count) : '—'));

    const actCell = el('td');
    actCell.style.cssText = 'display:flex;gap:4px;flex-wrap:wrap;';

    if (['queued', 'running', 'detecting', 'exporting'].includes(job.status)) {
      const cancelBtn = el('button', 'Cancel', { class: 'btn btn-sm btn-outline' });
      cancelBtn.addEventListener('click', async () => {
        try { await api.jobs.cancel(job.id); toast.success('Job cancelled.'); }
        catch (e) { toast.error(e.detail || e.message); }
      });
      actCell.appendChild(cancelBtn);
    }

    if (job.status === 'failed') {
      const retryBtn = el('button', 'Retry', { class: 'btn btn-sm btn-primary' });
      retryBtn.addEventListener('click', async () => {
        try { await api.jobs.retry(job.id); toast.success('Job re-queued.'); }
        catch (e) { toast.error(e.detail || e.message); }
      });
      actCell.appendChild(retryBtn);
    }

    if (['completed', 'failed', 'cancelled'].includes(job.status)) {
      const delBtn = el('button', 'Delete', { class: 'btn btn-sm btn-danger' });
      delBtn.addEventListener('click', () => {
        const conf = el('div', '');
        conf.appendChild(el('h3', 'Delete Job?', { class: 'modal-title' }));
        conf.appendChild(el('p', `Delete job for "${job.source_name}"?`));
        const row = el('div', '', { style: 'display:flex;gap:8px;margin-top:16px;' });
        const ok = el('button', 'Delete', { class: 'btn btn-danger' });
        const cancel = el('button', 'Cancel', { class: 'btn btn-outline' });
        ok.addEventListener('click', async () => {
          modal.close();
          try { await api.jobs.delete(job.id); toast.success('Job deleted.'); }
          catch (e) { toast.error(e.detail || e.message); }
        });
        cancel.addEventListener('click', () => modal.close());
        row.appendChild(ok); row.appendChild(cancel);
        conf.appendChild(row);
        modal.open(conf);
      });
      actCell.appendChild(delBtn);
    }

    tr.appendChild(actCell);
    tbody.appendChild(tr);
  }
}
