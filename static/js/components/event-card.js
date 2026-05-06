/**
 * Event card DOM builder. Uses el() for all user data — never innerHTML (ISSUE-16).
 */
import { el, api } from '../api.js';
import { toast } from './toast.js';
import { modal } from './modal.js';

const TAGS = ['Person', 'Vehicle', 'Animal', 'False Positive', 'Review Required'];

export function build(event, jobId, onToggle) {
  const card = el('div', '', { class: 'card event-card', 'data-event-id': event.id });
  card.style.cssText = 'display:flex;gap:12px;align-items:flex-start;padding:12px;';

  // Thumbnail
  const imgWrap = el('div', '', { style: 'width:160px;flex-shrink:0;' });
  const img = document.createElement('img');
  img.style.cssText = 'width:160px;height:90px;object-fit:cover;border-radius:6px;background:#111;';
  img.alt = `Event ${event.event_index + 1} thumbnail`;
  img.loading = 'lazy';

  // IntersectionObserver for lazy loading
  const observer = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting && event.thumbnail_path) {
      img.src = event.thumbnail_path;
      observer.disconnect();
    }
  }, { rootMargin: '200px' });
  observer.observe(img);

  imgWrap.appendChild(img);
  card.appendChild(imgWrap);

  // Details
  const info = el('div', '', { style: 'flex:1;min-width:0;' });

  const header = el('div', '', { style: 'display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;' });
  header.appendChild(el('strong', `Event ${event.event_index + 1}`));

  // Include/Exclude toggle
  const toggleBtn = el('button', event.included ? 'Exclude' : 'Include',
    { class: `btn btn-sm ${event.included ? 'btn-outline' : 'btn-success'}` });
  toggleBtn.addEventListener('click', async () => {
    try {
      const updated = await api.jobs.updateEvent(jobId, event.id, { included: !event.included });
      event.included = updated.included;
      toggleBtn.textContent = event.included ? 'Exclude' : 'Include';
      toggleBtn.className = `btn btn-sm ${event.included ? 'btn-outline' : 'btn-success'}`;
      if (onToggle) onToggle(event);
    } catch (e) {
      toast.error(`Failed to update event: ${e.detail || e.message}`);
    }
  });
  header.appendChild(toggleBtn);
  info.appendChild(header);

  // Time info
  const timeRow = el('div', '', { style: 'font-size:.8rem;color:var(--text-muted);margin-bottom:8px;' });
  timeRow.appendChild(el('span', `${event.start_clock || event.start_s.toFixed(1) + 's'} → ${event.end_clock || event.end_s.toFixed(1) + 's'}`));
  timeRow.appendChild(el('span', ` · ${event.duration_s.toFixed(1)}s`, { style: 'margin-left:8px;' }));
  if (event.peak_motion_score != null) {
    timeRow.appendChild(el('span', ` · Score: ${(event.peak_motion_score * 100).toFixed(1)}%`, { style: 'margin-left:8px;' }));
  }
  info.appendChild(timeRow);

  // Tag selector
  const tagRow = el('div', '', { style: 'display:flex;gap:8px;align-items:center;' });
  tagRow.appendChild(el('span', 'Tag:', { style: 'font-size:.8rem;' }));
  const tagSel = document.createElement('select');
  tagSel.className = 'form-control';
  tagSel.style.cssText = 'width:auto;padding:2px 6px;font-size:.8rem;';
  const emptyOpt = document.createElement('option');
  emptyOpt.value = '';
  emptyOpt.textContent = '— none —';
  tagSel.appendChild(emptyOpt);
  for (const tag of TAGS) {
    const opt = document.createElement('option');
    opt.value = tag;
    opt.textContent = tag;
    if (event.tag === tag) opt.selected = true;
    tagSel.appendChild(opt);
  }
  tagSel.addEventListener('change', async () => {
    try {
      await api.jobs.updateEvent(jobId, event.id, { tag: tagSel.value || null });
    } catch (e) {
      toast.error(`Tag update failed: ${e.detail || e.message}`);
    }
  });
  tagRow.appendChild(tagSel);
  info.appendChild(tagRow);

  // Play Clip button
  const playBtn = el('button', '▶ Play Clip', { class: 'btn btn-sm btn-primary', style: 'margin-top:8px;' });
  playBtn.addEventListener('click', async () => {
    playBtn.disabled = true;
    playBtn.textContent = 'Loading…';
    try {
      const { preview_url } = await api.jobs.preview(jobId, event.id);
      const content = el('div', '');
      content.appendChild(el('h3', `Event ${event.event_index + 1}`, { class: 'modal-title' }));
      const video = document.createElement('video');
      video.src = preview_url;
      video.controls = true;
      video.autoplay = true;
      video.style.cssText = 'width:100%;max-height:60vh;border-radius:6px;';
      content.appendChild(video);
      modal.open(content);
    } catch (e) {
      toast.error(`Preview failed: ${e.detail || e.message}`);
    } finally {
      playBtn.disabled = false;
      playBtn.textContent = '▶ Play Clip';
    }
  });
  info.appendChild(playBtn);

  card.appendChild(info);
  return card;
}
