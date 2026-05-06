import { api, el } from '../api.js';
import { navigate } from '../app.js';
import { toast } from '../components/toast.js';
import { modal } from '../components/modal.js';
import { SseClient } from '../sse-client.js';
import * as timeline from '../components/timeline-strip.js';
import { build as buildCard } from '../components/event-card.js';

let _sse = null;
let _events = [];
let _job = null;
let _logLines = [];
const MAX_LOG_DOM = 200;

export async function mount(container, params) {
  const jobId = params.id;
  container.innerHTML = '';
  const page = el('div', '', { class: 'page' });

  // Header
  const header = el('div', '', { class: 'page-header' });
  const titleEl = el('h1', 'Loading…', { class: 'page-title' });
  header.appendChild(titleEl);
  const statusEl = el('span', '', { class: 'badge' });
  header.appendChild(statusEl);
  page.appendChild(header);

  // Summary bar (sticky)
  const summaryBar = el('div', '', {
    style: 'background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:12px 16px;margin-bottom:16px;display:flex;gap:24px;flex-wrap:wrap;align-items:center;',
    id: 'summary-bar'
  });
  page.appendChild(summaryBar);

  // Progress bar (detection phase)
  const progressWrap = el('div', '', { class: 'progress-wrap', style: 'margin-bottom:16px;display:none;', id: 'det-progress' });
  progressWrap.appendChild(el('div', '', { class: 'progress-bar animated', style: 'width:0%', id: 'det-bar' }));
  page.appendChild(progressWrap);

  // Timeline canvas
  const canvasWrap = el('div', '', { class: 'card', style: 'margin-bottom:16px;' });
  canvasWrap.appendChild(el('h2', 'Timeline', { class: 'card-title' }));
  const canvas = document.createElement('canvas');
  canvas.style.cssText = 'width:100%;display:block;';
  canvasWrap.appendChild(canvas);
  page.appendChild(canvasWrap);

  // Action buttons
  const actionRow = el('div', '', { style: 'display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;' });
  const exportBtn = el('button', 'Export Selected Clips', { class: 'btn btn-success', id: 'export-btn' });
  const includeAllBtn = el('button', 'Include All', { class: 'btn btn-outline' });
  const excludeAllBtn = el('button', 'Exclude All', { class: 'btn btn-outline' });
  actionRow.appendChild(exportBtn);
  actionRow.appendChild(includeAllBtn);
  actionRow.appendChild(excludeAllBtn);
  page.appendChild(actionRow);

  // Export progress
  const exportProgress = el('div', '', { style: 'display:none;', id: 'export-progress' });
  exportProgress.appendChild(el('div', '', { class: 'progress-wrap' }));
  page.appendChild(exportProgress);

  // Export result card
  const exportResult = el('div', '', { class: 'card', style: 'display:none;margin-bottom:16px;', id: 'export-result' });
  page.appendChild(exportResult);

  // Event cards grid
  const cardsGrid = el('div', '', { id: 'event-cards', style: 'display:grid;grid-template-columns:repeat(auto-fill,minmax(400px,1fr));gap:12px;' });
  page.appendChild(cardsGrid);

  // SSE log panel (collapsible)
  const logPanel = el('details', '', { class: 'card', style: 'margin-top:16px;' });
  logPanel.appendChild(el('summary', 'Live Log', { style: 'cursor:pointer;font-weight:600;padding:4px 0;' }));
  const logEl = el('pre', '', { id: 'job-log', style: 'max-height:300px;overflow-y:auto;font-size:.75rem;font-family:var(--font-mono);white-space:pre-wrap;margin-top:8px;' });
  logPanel.appendChild(logEl);
  page.appendChild(logPanel);

  container.appendChild(page);

  // Load job data
  let jobData;
  try {
    jobData = await api.jobs.get(jobId);
  } catch (e) {
    container.textContent = `Failed to load job: ${e.detail || e.message}`;
    return;
  }

  _job = jobData.job;
  _events = jobData.events;

  titleEl.textContent = _job.source_name;
  statusEl.textContent = _job.status;
  statusEl.className = `badge badge-${_job.status}`;

  _updateSummary(summaryBar, jobData);
  _renderCards(cardsGrid, _events, jobId, summaryBar, jobData);

  // Mount timeline
  if (_events.length > 0 && _job.duration_s) {
    timeline.mount(canvas, _events, _job.duration_s, (idx) => {
      const card = document.querySelector(`[data-event-id="${_events[idx]?.id}"]`);
      if (card) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  }

  // Show detection progress if running
  if (['detecting', 'running'].includes(_job.status)) {
    document.getElementById('det-progress').style.display = '';
    document.getElementById('det-bar').style.width = `${(_job.progress * 100).toFixed(0)}%`;
  }

  // Export button handler
  exportBtn.addEventListener('click', async () => {
    const includedCount = _events.filter(e => e.included).length;
    if (includedCount === 0) {
      toast.warn('No events selected — include at least one event to export.');
      return;
    }
    exportBtn.disabled = true;
    exportBtn.textContent = 'Exporting…';
    document.getElementById('export-progress').style.display = '';

    try {
      await api.jobs.export(jobId);
      toast.success('Export started. Watch the log panel for progress.');
    } catch (e) {
      toast.error(e.detail || e.message);
      exportBtn.disabled = false;
      exportBtn.textContent = 'Export Selected Clips';
    }
  });

  // Bulk action buttons
  includeAllBtn.addEventListener('click', async () => {
    for (const ev of _events) {
      if (!ev.included) {
        try { await api.jobs.updateEvent(jobId, ev.id, { included: true }); ev.included = true; } catch {}
      }
    }
    _updateSummary(summaryBar, { ...jobData, events: _events });
    timeline.updateEvents(_events);
    _renderCards(cardsGrid, _events, jobId, summaryBar, jobData);
  });

  excludeAllBtn.addEventListener('click', async () => {
    for (const ev of _events) {
      if (ev.included) {
        try { await api.jobs.updateEvent(jobId, ev.id, { included: false }); ev.included = false; } catch {}
      }
    }
    _updateSummary(summaryBar, { ...jobData, events: _events });
    timeline.updateEvents(_events);
    _renderCards(cardsGrid, _events, jobId, summaryBar, jobData);
  });

  // SSE
  if (['queued', 'running', 'detecting', 'exporting'].includes(_job.status)) {
    _connectSse(jobId, logEl, summaryBar, jobData, cardsGrid, canvas);
  }
}

export function unmount() {
  if (_sse) { _sse.disconnect(); _sse = null; }
  timeline.unmount();
  _events = [];
  _job = null;
  _logLines = [];
}

function _connectSse(jobId, logEl, summaryBar, jobData, cardsGrid, canvas) {
  _sse = new SseClient();
  _sse.connect(`/api/jobs/${jobId}/stream`, {
    log: (msg) => {
      _logLines.push(msg.line);
      if (_logLines.length > MAX_LOG_DOM) _logLines.shift();
      logEl.textContent = _logLines.join('\n');
      logEl.scrollTop = logEl.scrollHeight;
    },
    progress: (msg) => {
      const bar = document.getElementById('det-bar');
      if (bar) bar.style.width = `${(msg.value * 100).toFixed(0)}%`;
    },
    done: async (msg) => {
      _sse.disconnect();
      try {
        const fresh = await api.jobs.get(jobId);
        _events = fresh.events;
        _updateSummary(summaryBar, fresh);
        _renderCards(cardsGrid, _events, jobId, summaryBar, jobData);
        if (_events.length && _job.duration_s) timeline.updateEvents(_events);

        // Show export result if completed
        if (msg.status === 'completed' && fresh.job.output_name) {
          _showExportResult(fresh.job, jobId);
        }
      } catch {}
    },
  });
}

function _updateSummary(bar, jobData) {
  const events = jobData.events || _events;
  const included = events.filter(e => e.included);
  const totalS = included.reduce((s, e) => s + (e.duration_s || 0), 0);
  const job = jobData.job || _job;
  const srcDur = job.duration_s || 1;
  const pct = (totalS / srcDur * 100).toFixed(1);

  // Estimated size (A2 fix)
  let estSize;
  const settings = job.settings || {};
  if (settings.output_quality === 'original') {
    estSize = (totalS / srcDur) * (job.file_size || 0);
  } else {
    const bitrate = settings.output_quality === 'compressed_720p' ? 2_000_000 : 800_000;
    estSize = totalS * bitrate / 8;
  }

  bar.innerHTML = '';
  const addStat = (label, val) => {
    const span = el('span', '', { style: 'font-size:.875rem;' });
    span.appendChild(el('strong', label + ': '));
    span.appendChild(el('span', val));
    bar.appendChild(span);
  };
  addStat('Events', `${included.length} included / ${events.length - included.length} excluded`);
  addStat('Activity', `${totalS.toFixed(0)}s (${pct}%)`);
  addStat('Est. Output', `${(estSize / 1e6).toFixed(0)} MB`);

  // Update export button disabled state (FR-055)
  const exportBtn = document.getElementById('export-btn');
  if (exportBtn) {
    exportBtn.disabled = included.length === 0;
    if (included.length === 0) exportBtn.title = 'No events selected';
  }
}

function _renderCards(container, events, jobId, summaryBar, jobData) {
  container.innerHTML = '';
  for (const ev of events) {
    const card = buildCard(ev, jobId, (updated) => {
      _updateSummary(summaryBar, { ...jobData, events });
      timeline.updateEvents(events);
    });
    container.appendChild(card);
  }
}

function _showExportResult(job, jobId) {
  const resultEl = document.getElementById('export-result');
  if (!resultEl) return;
  resultEl.style.display = '';
  resultEl.innerHTML = '';
  resultEl.appendChild(el('h2', 'Export Complete!', { class: 'card-title', style: 'color:var(--color-success);' }));
  resultEl.appendChild(el('p', `File: ${job.output_name}`));
  if (job.output_size) {
    resultEl.appendChild(el('p', `Size: ${(job.output_size / 1e6).toFixed(1)} MB`));
  }
  const btnRow = el('div', '', { style: 'display:flex;gap:8px;margin-top:12px;' });

  const previewBtn = el('button', '▶ Preview Output', { class: 'btn btn-primary' });
  previewBtn.addEventListener('click', () => {
    const content = el('div', '');
    content.appendChild(el('h3', 'Output Preview', { class: 'modal-title' }));
    const video = document.createElement('video');
    video.src = `/api/jobs/${jobId}/output`;
    video.controls = true;
    video.style.cssText = 'width:100%;max-height:60vh;';
    content.appendChild(video);
    modal.open(content);
  });
  btnRow.appendChild(previewBtn);

  const downloadLink = el('a', 'Download', {
    href: `/api/jobs/${jobId}/output`, class: 'btn btn-outline', download: job.output_name
  });
  btnRow.appendChild(downloadLink);
  resultEl.appendChild(btnRow);
}
