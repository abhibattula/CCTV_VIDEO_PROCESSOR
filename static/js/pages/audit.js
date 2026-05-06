import { api, el } from '../api.js';
import { toast } from '../components/toast.js';

let _offset = 0;
const PAGE_SIZE = 50;

export async function mount(container) {
  container.innerHTML = '';
  const page = el('div', '', { class: 'page' });
  page.appendChild(el('h1', 'Audit Log', { class: 'page-title' }));

  // Filter bar
  const filterCard = el('div', '', { class: 'card', style: 'margin-bottom:16px;display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;' });

  const levelSel = document.createElement('select');
  levelSel.className = 'form-control'; levelSel.style.width = 'auto';
  for (const v of ['', 'INFO', 'WARN', 'ERROR']) {
    const o = document.createElement('option'); o.value = v; o.textContent = v || 'All Levels';
    levelSel.appendChild(o);
  }

  const actorSel = document.createElement('select');
  actorSel.className = 'form-control'; actorSel.style.width = 'auto';
  for (const v of ['', 'user', 'system']) {
    const o = document.createElement('option'); o.value = v; o.textContent = v || 'All Actors';
    actorSel.appendChild(o);
  }

  const applyBtn = el('button', 'Apply', { class: 'btn btn-primary' });
  const exportBtn = el('button', 'Export CSV', { class: 'btn btn-outline' });

  const addFG = (label, ctrl) => {
    const g = el('div', '', { class: 'form-group', style: 'margin:0;' });
    g.appendChild(el('label', label, { class: 'form-label' }));
    g.appendChild(ctrl);
    return g;
  };

  filterCard.appendChild(addFG('Level', levelSel));
  filterCard.appendChild(addFG('Actor', actorSel));
  filterCard.appendChild(applyBtn);
  filterCard.appendChild(exportBtn);
  page.appendChild(filterCard);

  const tableWrap = el('div', '', { class: 'card table-wrap' });
  const table = el('table');
  const thead = el('thead');
  const hr = el('tr');
  for (const h of ['Time', 'Level', 'Actor', 'Action', 'Detail', 'Job ID']) hr.appendChild(el('th', h));
  thead.appendChild(hr);
  table.appendChild(thead);
  table.appendChild(el('tbody', '', { id: 'audit-tbody' }));
  tableWrap.appendChild(table);

  const pagerRow = el('div', '', { style: 'display:flex;gap:8px;margin-top:12px;align-items:center;', id: 'audit-pager' });
  tableWrap.appendChild(pagerRow);
  page.appendChild(tableWrap);

  container.appendChild(page);

  async function load() {
    try {
      const params = { limit: PAGE_SIZE, offset: _offset };
      if (levelSel.value) params.level = levelSel.value;
      if (actorSel.value) params.actor = actorSel.value;
      const data = await api.audit.list(params);
      _renderRows(data.entries);
      _renderPager(data.total);
    } catch (e) {
      toast.error('Failed to load audit log: ' + (e.detail || e.message));
    }
  }

  applyBtn.addEventListener('click', () => { _offset = 0; load(); });
  exportBtn.addEventListener('click', () => { window.location.href = api.audit.csvUrl(); });

  await load();
}

export function unmount() { _offset = 0; }

function _renderRows(entries) {
  const tbody = document.getElementById('audit-tbody');
  if (!tbody) return;
  tbody.innerHTML = '';
  for (const e of entries) {
    const tr = el('tr');
    // All user data via el() textContent — ISSUE-16
    tr.appendChild(el('td', e.ts ? e.ts.slice(0, 19).replace('T', ' ') : '—'));
    const lvlCell = el('td');
    lvlCell.appendChild(el('span', e.level, { class: `badge badge-${e.level === 'ERROR' ? 'failed' : e.level === 'WARN' ? 'exporting' : 'completed'}` }));
    tr.appendChild(lvlCell);
    tr.appendChild(el('td', e.actor || '—'));
    tr.appendChild(el('td', e.action || '—'));
    tr.appendChild(el('td', e.detail || '—'));
    tr.appendChild(el('td', e.job_id ? e.job_id.slice(0, 8) + '…' : '—'));
    tbody.appendChild(tr);
  }
}

function _renderPager(total) {
  const pager = document.getElementById('audit-pager');
  if (!pager) return;
  pager.innerHTML = '';
  pager.appendChild(el('span', `${_offset + 1}–${Math.min(_offset + PAGE_SIZE, total)} of ${total}`));
  if (_offset > 0) {
    const prev = el('button', '← Prev', { class: 'btn btn-outline btn-sm' });
    prev.addEventListener('click', () => { _offset -= PAGE_SIZE; _render(); });
    pager.appendChild(prev);
  }
  if (_offset + PAGE_SIZE < total) {
    const next = el('button', 'Next →', { class: 'btn btn-outline btn-sm' });
    next.addEventListener('click', async () => {
      _offset += PAGE_SIZE;
      try {
        const params = { limit: PAGE_SIZE, offset: _offset };
        const data = await api.audit.list(params);
        _renderRows(data.entries);
        _renderPager(data.total);
      } catch {}
    });
    pager.appendChild(next);
  }
}
