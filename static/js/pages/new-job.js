import { api, el } from '../api.js';
import { navigate } from '../app.js';
import { toast } from '../components/toast.js';
import { modal } from '../components/modal.js';
import { mount as mountUpload } from '../components/upload-widget.js';

let _sourcePath = '';

export async function mount(container) {
  container.innerHTML = '';
  const page = el('div', '', { class: 'page' });
  page.appendChild(el('h1', 'New Analysis Job', { class: 'page-title' }));

  // Source tabs
  const tabs = el('div', '', { style: 'display:flex;gap:4px;margin-bottom:16px;' });
  const tabPath = el('button', 'File Path', { class: 'btn btn-primary' });
  const tabUpload = el('button', 'Upload File', { class: 'btn btn-outline' });
  tabs.appendChild(tabPath);
  tabs.appendChild(tabUpload);
  page.appendChild(tabs);

  const pathPanel = el('div', '', { class: 'card', style: 'margin-bottom:16px;' });
  const pathInput = el('input', '', {
    class: 'form-control', type: 'text', placeholder: '/media/usb0/video.mp4', id: 'source-path'
  });
  pathPanel.appendChild(el('label', 'Video file path', { class: 'form-label' }));
  pathPanel.appendChild(pathInput);
  const browseBtn = el('button', 'Browse…', { class: 'btn btn-outline', style: 'margin-top:8px;' });
  browseBtn.addEventListener('click', () => _openFileBrowser(pathInput));
  pathPanel.appendChild(browseBtn);

  const uploadPanel = el('div', '', { class: 'card', style: 'margin-bottom:16px;display:none;' });
  mountUpload(uploadPanel, (path) => { _sourcePath = path; pathInput.value = path; });

  tabPath.addEventListener('click', () => {
    pathPanel.style.display = ''; uploadPanel.style.display = 'none';
    tabPath.className = 'btn btn-primary'; tabUpload.className = 'btn btn-outline';
  });
  tabUpload.addEventListener('click', () => {
    pathPanel.style.display = 'none'; uploadPanel.style.display = '';
    tabUpload.className = 'btn btn-primary'; tabPath.className = 'btn btn-outline';
  });

  page.appendChild(pathPanel);
  page.appendChild(uploadPanel);

  // Detection settings
  const detCard = el('div', '', { class: 'card', style: 'margin-bottom:16px;' });
  detCard.appendChild(el('h2', 'Detection Settings', { class: 'card-title' }));

  // Sensitivity
  const sensWrap = el('div', '', { class: 'form-group' });
  sensWrap.appendChild(el('label', 'Sensitivity', { class: 'form-label' }));
  const sensRow = el('div', '', { style: 'display:flex;gap:8px;' });
  const sensOpts = ['low', 'medium', 'high'];
  let selSens = 'medium';
  const sensBtns = sensOpts.map(s => {
    const b = el('button', s.charAt(0).toUpperCase() + s.slice(1),
      { class: `btn ${s === selSens ? 'btn-primary' : 'btn-outline'}` });
    b.addEventListener('click', () => {
      selSens = s;
      sensBtns.forEach((bb, i) => bb.className = `btn ${sensOpts[i] === s ? 'btn-primary' : 'btn-outline'}`);
    });
    return b;
  });
  sensBtns.forEach(b => sensRow.appendChild(b));
  sensWrap.appendChild(sensRow);
  detCard.appendChild(sensWrap);

  const makeNum = (label, id, val, min, max) => {
    const g = el('div', '', { class: 'form-group' });
    g.appendChild(el('label', label, { class: 'form-label', for: id }));
    const inp = el('input', '', { class: 'form-control', type: 'number', id, value: val, min, max, style: 'width:100px;' });
    g.appendChild(inp);
    return g;
  };
  detCard.appendChild(makeNum('Padding (seconds)', 'padding', 3, 0, 30));
  detCard.appendChild(makeNum('Min Gap (seconds)', 'mingap', 5, 1, 60));
  detCard.appendChild(makeNum('Min Event (seconds)', 'minevent', 3, 1, 30));
  page.appendChild(detCard);

  // Output settings
  const outCard = el('div', '', { class: 'card', style: 'margin-bottom:16px;' });
  outCard.appendChild(el('h2', 'Output Settings', { class: 'card-title' }));

  const qualGroup = el('div', '', { class: 'form-group' });
  qualGroup.appendChild(el('label', 'Output Quality', { class: 'form-label' }));
  const qualSel = document.createElement('select');
  qualSel.className = 'form-control';
  qualSel.style.width = 'auto';
  for (const [val, label] of [['original', 'Original Quality (stream copy)'], ['compressed_720p', '720p Compressed'], ['small_480p', '480p Small']]) {
    const opt = document.createElement('option');
    opt.value = val; opt.textContent = label;
    qualSel.appendChild(opt);
  }
  qualGroup.appendChild(qualSel);
  outCard.appendChild(qualGroup);
  page.appendChild(outCard);

  // Warnings area
  const warningsEl = el('div', '', { id: 'warnings', style: 'margin-bottom:16px;' });
  page.appendChild(warningsEl);

  // FIX-D: Workflow info box — explains the 2-step process before the user submits
  const flowInfo = el('div', '', {
    style: 'background:var(--bg-input);border:1px solid var(--border);border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:.875rem;',
  });
  const flowTitle = el('strong', 'How it works:');
  flowInfo.appendChild(flowTitle);
  const steps = el('ol', '', { style: 'margin:6px 0 0 16px;line-height:1.9;' });
  steps.appendChild(el('li', 'Detection runs automatically — the Pi analyses the video for motion (takes a few minutes)'));
  steps.appendChild(el('li', 'Review events on the timeline — exclude false positives (shadows, wind, etc.)'));
  steps.appendChild(el('li', 'Click Export Selected Clips — generates your highlight video'));
  flowInfo.appendChild(steps);
  page.appendChild(flowInfo);

  // Submit
  const submitBtn = el('button', 'Start Analysis →', { class: 'btn btn-primary btn-lg' });
  submitBtn.addEventListener('click', async () => {
    const src = pathInput.value.trim() || _sourcePath;
    if (!src) { toast.error('Please specify a video source.'); return; }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Submitting…';

    try {
      const result = await api.jobs.create({
        source_path: src,
        settings: {
          sensitivity: selSens,
          padding_s: parseInt(document.getElementById('padding').value) || 3,
          min_gap_s: parseInt(document.getElementById('mingap').value) || 5,
          min_event_s: parseInt(document.getElementById('minevent').value) || 3,
          output_quality: qualSel.value,
        },
      });

      if (result.warnings && result.warnings.length) {
        warningsEl.innerHTML = '';
        for (const w of result.warnings) {
          const d = el('div', `⚠ ${w.message}`,
            { style: 'background:#fef3c7;border:1px solid #d97706;border-radius:6px;padding:8px 12px;margin-bottom:8px;font-size:.875rem;' });
          warningsEl.appendChild(d);
        }
      }

      toast.success('Job submitted!');
      await navigate(`/jobs/${result.job_id}`);
    } catch (e) {
      toast.error(e.detail || e.message);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Start Analysis';
    }
  });
  page.appendChild(submitBtn);

  container.appendChild(page);
}

export function unmount() {}

async function _openFileBrowser(pathInput) {
  let currentPath = '/media';

  const wrap = el('div', '');
  const title = el('h3', 'Browse Files', { class: 'modal-title' });
  wrap.appendChild(title);

  const pathDisplay = el('div', currentPath, { style: 'font-size:.8rem;color:var(--text-muted);margin-bottom:8px;' });
  wrap.appendChild(pathDisplay);

  const listEl = el('div', '', { style: 'max-height:50vh;overflow-y:auto;' });
  wrap.appendChild(listEl);

  async function load(path) {
    currentPath = path;
    pathDisplay.textContent = path;
    listEl.innerHTML = '';
    try {
      const data = await api.browse(path);
      if (data.parent !== path) {
        const back = el('div', '⬆ ..', { style: 'padding:8px;cursor:pointer;color:var(--color-primary);' });
        back.addEventListener('click', () => load(data.parent));
        listEl.appendChild(back);
      }
      for (const entry of data.entries) {
        const row = el('div', (entry.is_dir ? '📁 ' : '🎬 ') + entry.name,
          { style: 'padding:8px;cursor:pointer;border-bottom:1px solid var(--border);' });
        row.addEventListener('click', () => {
          if (entry.is_dir) { load(path.endsWith('/') ? path + entry.name : path + '/' + entry.name); }
          else if (entry.is_video) {
            pathInput.value = path.endsWith('/') ? path + entry.name : path + '/' + entry.name;
            modal.close();
          }
        });
        listEl.appendChild(row);
      }
    } catch (e) {
      listEl.appendChild(el('p', `Error: ${e.detail || e.message}`, { style: 'color:var(--color-danger);' }));
    }
  }

  await load(currentPath);
  modal.open(wrap);
}
