/**
 * Drag-and-drop chunked uploader.
 * File.slice() never loads file into memory. Sequential chunks. 3× retry. (FR-005)
 */
import { api } from '../api.js';
import { el } from '../api.js';

export function mount(container, onComplete) {
  container.innerHTML = '';

  const zone = el('div', '', { class: 'upload-zone' });
  zone.appendChild(el('p', '📁 Drag & drop video file here, or click to select'));
  zone.appendChild(el('p', 'Supports up to 24+ GB', { style: 'font-size:.8rem;margin-top:4px;' }));

  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = 'video/*,.mkv,.ts,.mts';
  fileInput.style.display = 'none';

  const progressWrap = el('div', '', { class: 'progress-wrap', style: 'margin-top:12px;display:none;' });
  const progressBar = el('div', '', { class: 'progress-bar animated', style: 'width:0%' });
  progressWrap.appendChild(progressBar);

  const statusText = el('div', '', { style: 'font-size:.8rem;color:var(--text-muted);margin-top:4px;' });

  zone.addEventListener('click', () => fileInput.click());
  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) _startUpload(file);
  });
  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) _startUpload(fileInput.files[0]);
  });

  container.appendChild(zone);
  container.appendChild(fileInput);
  container.appendChild(progressWrap);
  container.appendChild(statusText);

  async function _startUpload(file) {
    const CHUNK = 1_048_576; // 1 MB
    const totalChunks = Math.ceil(file.size / CHUNK);

    progressWrap.style.display = 'block';
    progressBar.style.width = '0%';
    statusText.textContent = `Preparing upload of ${(file.size / 1e9).toFixed(2)} GB…`;

    // Check for interrupted upload
    let uploadId = sessionStorage.getItem('uploadId');
    let startChunk = 0;
    if (uploadId) {
      try {
        const st = await api.upload.status(uploadId);
        startChunk = (st.received_chunks || []).length;
        statusText.textContent = `Resuming from chunk ${startChunk}…`;
      } catch {
        uploadId = null;
      }
    }

    if (!uploadId) {
      const init = await api.upload.init(file.name, file.size);
      uploadId = init.upload_id;
      sessionStorage.setItem('uploadId', uploadId);
    }

    const startTime = Date.now();

    for (let i = startChunk; i < totalChunks; i++) {
      const blob = file.slice(i * CHUNK, (i + 1) * CHUNK);

      let success = false;
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          await api.upload.chunk(uploadId, i, blob);
          success = true;
          break;
        } catch {
          await new Promise(r => setTimeout(r, 1000 * Math.pow(2, attempt)));
        }
      }
      if (!success) {
        statusText.textContent = `Upload failed at chunk ${i}. Reload to retry.`;
        return;
      }

      const pct = ((i + 1) / totalChunks * 100).toFixed(0);
      progressBar.style.width = pct + '%';

      const elapsed = (Date.now() - startTime) / 1000;
      const rate = ((i + 1) * CHUNK) / elapsed; // bytes/s
      const remaining = ((totalChunks - i - 1) * CHUNK) / rate;
      statusText.textContent = `Uploading… ${pct}% — ${(rate / 1e6).toFixed(1)} MB/s — ETA ${Math.round(remaining)}s`;
    }

    statusText.textContent = 'Assembling file…';
    const result = await api.upload.finalize(uploadId, totalChunks);
    sessionStorage.removeItem('uploadId');

    statusText.textContent = `Upload complete: ${file.name}`;
    if (onComplete) onComplete(result.source_path);
  }
}
