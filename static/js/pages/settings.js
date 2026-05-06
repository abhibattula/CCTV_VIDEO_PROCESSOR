import { api, el } from '../api.js';
import { toast } from '../components/toast.js';

let _original = null;
let _dirty = false;

export async function mount(container) {
  container.innerHTML = '';
  const page = el('div', '', { class: 'page' });
  page.appendChild(el('h1', 'Settings', { class: 'page-title' }));

  const dirtyBanner = el('div', '⚠ Unsaved changes', {
    style: 'display:none;background:#fef3c7;border:1px solid #d97706;border-radius:6px;padding:8px 12px;margin-bottom:12px;color:#92400e;font-weight:500;',
    id: 'dirty-banner'
  });
  page.appendChild(dirtyBanner);

  let settings;
  try { settings = await api.settings.get(); }
  catch { settings = {}; }
  _original = JSON.parse(JSON.stringify(settings));

  const card = el('div', '', { class: 'card' });

  function addField(label, key, type = 'text', attrs = {}) {
    const g = el('div', '', { class: 'form-group' });
    g.appendChild(el('label', label, { class: 'form-label' }));
    const inp = el('input', '', { class: 'form-control', type, id: `s-${key}`, ...attrs });
    inp.value = settings[key] ?? '';
    inp.addEventListener('input', () => _markDirty());
    g.appendChild(inp);
    return g;
  }

  function addSelect(label, key, options) {
    const g = el('div', '', { class: 'form-group' });
    g.appendChild(el('label', label, { class: 'form-label' }));
    const sel = document.createElement('select');
    sel.className = 'form-control'; sel.style.width = 'auto'; sel.id = `s-${key}`;
    for (const [v, t] of options) {
      const o = document.createElement('option'); o.value = v; o.textContent = t;
      if (settings[key] === v) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener('change', () => _markDirty());
    g.appendChild(sel);
    return g;
  }

  card.appendChild(addField('Default Output Directory', 'default_output_dir'));
  card.appendChild(addSelect('Default Sensitivity', 'default_sensitivity', [['low','Low'],['medium','Medium'],['high','High']]));
  card.appendChild(addField('Default Padding (s)', 'default_padding_s', 'number', { min: 0, max: 30 }));
  card.appendChild(addField('Min Gap (s)', 'default_min_gap_s', 'number', { min: 1, max: 60 }));
  card.appendChild(addField('Min Event (s)', 'default_min_event_s', 'number', { min: 1, max: 30 }));
  card.appendChild(addField('Thermal Limit (°C)', 'thermal_limit_c', 'number', { min: 60, max: 90 }));
  card.appendChild(addField('Disk Warn (%)', 'disk_warn_percent', 'number', { min: 50, max: 95 }));

  // Dark mode toggle
  const dmGroup = el('div', '', { class: 'form-group toggle-wrap' });
  const dmToggle = el('label', '', { class: 'toggle' });
  const dmInput = document.createElement('input');
  dmInput.type = 'checkbox';
  dmInput.checked = document.documentElement.getAttribute('data-theme') === 'dark';
  dmInput.addEventListener('change', () => {
    const dark = dmInput.checked;
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : '');
    localStorage.setItem('darkMode', dark ? 'dark' : 'light');
    _markDirty();
  });
  const dmSlider = el('span', '', { class: 'toggle-slider' });
  dmToggle.appendChild(dmInput); dmToggle.appendChild(dmSlider);
  dmGroup.appendChild(dmToggle);
  dmGroup.appendChild(el('span', 'Dark Mode'));
  card.appendChild(dmGroup);

  page.appendChild(card);

  const saveBtn = el('button', 'Save Settings', { class: 'btn btn-primary', style: 'margin-top:16px;' });
  saveBtn.addEventListener('click', async () => {
    const body = {
      default_output_dir: document.getElementById('s-default_output_dir')?.value,
      default_sensitivity: document.getElementById('s-default_sensitivity')?.value,
      default_padding_s: parseInt(document.getElementById('s-default_padding_s')?.value),
      default_min_gap_s: parseInt(document.getElementById('s-default_min_gap_s')?.value),
      default_min_event_s: parseInt(document.getElementById('s-default_min_event_s')?.value),
      thermal_limit_c: parseInt(document.getElementById('s-thermal_limit_c')?.value),
      disk_warn_percent: parseInt(document.getElementById('s-disk_warn_percent')?.value),
    };
    try {
      await api.settings.put(body);
      _original = body;
      _clearDirty();
      toast.success('Settings saved!');
    } catch (e) {
      toast.error(e.detail || e.message);
    }
  });
  page.appendChild(saveBtn);

  container.appendChild(page);
}

export function unmount() { _dirty = false; }

function _markDirty() {
  _dirty = true;
  const b = document.getElementById('dirty-banner');
  if (b) b.style.display = '';
}

function _clearDirty() {
  _dirty = false;
  const b = document.getElementById('dirty-banner');
  if (b) b.style.display = 'none';
}
