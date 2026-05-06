import { api, el } from '../api.js';
import { toast } from '../components/toast.js';

export async function mount(container) {
  container.innerHTML = '';
  const page = el('div', '', { class: 'page' });
  page.appendChild(el('h1', 'Reports', { class: 'page-title' }));

  // Job selector
  const selCard = el('div', '', { class: 'card', style: 'margin-bottom:16px;' });
  selCard.appendChild(el('label', 'Select a completed job:', { class: 'form-label' }));
  const jobSel = document.createElement('select');
  jobSel.className = 'form-control'; jobSel.style.width = 'auto';
  selCard.appendChild(jobSel);
  page.appendChild(selCard);

  const reportArea = el('div', '', { id: 'report-area' });
  page.appendChild(reportArea);

  container.appendChild(page);

  // Load completed jobs
  try {
    const data = await api.jobs.list({ status: 'completed', limit: 100 });
    const empty = document.createElement('option');
    empty.value = ''; empty.textContent = '— Select a job —';
    jobSel.appendChild(empty);
    for (const job of data.jobs) {
      const opt = document.createElement('option');
      opt.value = job.id; opt.textContent = `${job.source_name} (${job.created_at?.slice(0,10)})`;
      jobSel.appendChild(opt);
    }
  } catch (e) {
    toast.error('Failed to load jobs: ' + (e.detail || e.message));
  }

  jobSel.addEventListener('change', async () => {
    const id = jobSel.value;
    if (!id) { reportArea.innerHTML = ''; return; }
    await loadReport(id);
  });

  async function loadReport(jobId) {
    reportArea.innerHTML = '';
    try {
      const analytics = await api.reports.analytics(jobId);

      // Summary stats
      const statCard = el('div', '', { class: 'card', style: 'margin-bottom:16px;' });
      statCard.appendChild(el('h2', 'Summary', { class: 'card-title' }));
      const grid = el('div', '', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:.875rem;' });
      const stats = [
        ['Total Events', analytics.total_events],
        ['Included Events', analytics.included_events],
        ['Activity %', `${analytics.activity_percent}%`],
        ['Peak Hour', analytics.peak_hour !== null ? `${analytics.peak_hour}:00` : 'N/A'],
        ['Longest Event', `${analytics.longest_event_s}s`],
        ['Avg Event', `${analytics.avg_event_s}s`],
      ];
      for (const [k, v] of stats) {
        grid.appendChild(el('strong', k, { style: 'color:var(--text-muted);' }));
        grid.appendChild(el('span', String(v)));
      }
      statCard.appendChild(grid);
      reportArea.appendChild(statCard);

      // Hourly bar chart (SVG)
      if (analytics.hourly_activity.length) {
        const chartCard = el('div', '', { class: 'card', style: 'margin-bottom:16px;' });
        chartCard.appendChild(el('h2', 'Hourly Activity', { class: 'card-title' }));
        chartCard.appendChild(_makeSvgChart(analytics.hourly_activity));
        reportArea.appendChild(chartCard);
      }

      // Export buttons
      const btnCard = el('div', '', { class: 'card' });
      btnCard.appendChild(el('h2', 'Export', { class: 'card-title' }));
      const btnRow = el('div', '', { style: 'display:flex;gap:8px;' });

      const pdfBtn = el('button', '📄 Download PDF', { class: 'btn btn-primary' });
      pdfBtn.addEventListener('click', () => window.open(api.reports.pdfUrl(jobId)));
      btnRow.appendChild(pdfBtn);

      const csvBtn = el('button', '📊 Download CSV', { class: 'btn btn-outline' });
      csvBtn.addEventListener('click', () => { window.location.href = api.reports.csvUrl(jobId); });
      btnRow.appendChild(csvBtn);

      btnCard.appendChild(btnRow);
      reportArea.appendChild(btnCard);

    } catch (e) {
      reportArea.appendChild(el('p', `Error: ${e.detail || e.message}`, { style: 'color:var(--color-danger);' }));
    }
  }
}

export function unmount() {}

function _makeSvgChart(hourlyData) {
  const W = 600, H = 160, PAD = 30;
  const maxCount = Math.max(...hourlyData.map(h => h.event_count), 1);
  const barW = (W - PAD * 2) / 24;

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.style.cssText = 'width:100%;height:auto;';

  for (const row of hourlyData) {
    const x = PAD + row.hour * barW;
    const barH = ((row.event_count / maxCount) * (H - PAD - 20));
    const y = H - PAD - barH;

    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('x', x); rect.setAttribute('y', y);
    rect.setAttribute('width', barW - 2); rect.setAttribute('height', barH);
    rect.setAttribute('fill', '#2563eb'); rect.setAttribute('rx', 2);
    svg.appendChild(rect);

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', x + barW / 2); text.setAttribute('y', H - 10);
    text.setAttribute('text-anchor', 'middle'); text.setAttribute('font-size', '9');
    text.textContent = row.hour;
    svg.appendChild(text);
  }
  return svg;
}
