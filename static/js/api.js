/**
 * Centralized API wrapper. All DOM building uses el() — textContent only, never innerHTML.
 * XSS prevention: ISSUE-16.
 */

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

/** Safe DOM builder — uses textContent, never innerHTML (ISSUE-16). */
export function el(tag, text, attrs = {}) {
  const e = document.createElement(tag);
  if (text !== undefined && text !== null) e.textContent = String(text);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e[k] = v;
    else e.setAttribute(k, v);
  }
  return e;
}

async function apiFetch(path, options = {}) {
  const defaults = { headers: { 'Content-Type': 'application/json' } };
  if (options.body && typeof options.body !== 'string') {
    options.body = JSON.stringify(options.body);
  }
  const res = await fetch(path, { ...defaults, ...options });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  jobs: {
    list: (params = {}) => {
      const q = new URLSearchParams(params).toString();
      return apiFetch(`/api/jobs${q ? '?' + q : ''}`);
    },
    get: (id) => apiFetch(`/api/jobs/${id}`),
    create: (body) => apiFetch('/api/jobs', { method: 'POST', body }),
    cancel: (id) => apiFetch(`/api/jobs/${id}/cancel`, { method: 'POST' }),
    delete: (id, deleteOutput = false) =>
      apiFetch(`/api/jobs/${id}?delete_output=${deleteOutput}`, { method: 'DELETE' }),
    retry: (id) => apiFetch(`/api/jobs/${id}/retry`, { method: 'POST' }),
    updateEvent: (jobId, eid, body) =>
      apiFetch(`/api/jobs/${jobId}/events/${eid}`, { method: 'PUT', body }),
    preview: (jobId, eid) =>
      apiFetch(`/api/jobs/${jobId}/events/${eid}/preview`, { method: 'POST' }),
    export: (id) => apiFetch(`/api/jobs/${id}/export`, { method: 'POST' }),
    exports: (id) => apiFetch(`/api/jobs/${id}/exports`),
    zoneFrame: (id) => `/api/jobs/${id}/zone-frame`,
  },
  browse: (path) => apiFetch(`/api/browse?path=${encodeURIComponent(path)}`),
  upload: {
    init: (filename, totalSize) =>
      apiFetch('/api/upload/init', { method: 'POST', body: { filename, total_size: totalSize } }),
    chunk: async (uploadId, index, blob) => {
      const form = new FormData();
      form.append('upload_id', uploadId);
      form.append('chunk_index', index);
      form.append('chunk_data', blob, 'chunk');
      const res = await fetch('/api/upload/chunk', { method: 'POST', body: form });
      if (!res.ok) throw new ApiError(res.status, 'Chunk upload failed');
      return res.json();
    },
    finalize: (uploadId, expectedChunks) =>
      apiFetch('/api/upload/finalize', { method: 'POST', body: { upload_id: uploadId, expected_chunks: expectedChunks } }),
    status: (uploadId) => apiFetch(`/api/upload/status/${uploadId}`),
  },
  system: { stats: () => apiFetch('/api/system/stats') },
  dashboard: () => apiFetch('/api/dashboard'),
  settings: {
    get: () => apiFetch('/api/settings'),
    put: (body) => apiFetch('/api/settings', { method: 'PUT', body }),
  },
  reports: {
    analytics: (id) => apiFetch(`/api/reports/${id}/analytics`),
    pdfUrl: (id) => `/api/reports/${id}/pdf`,
    csvUrl: (id) => `/api/reports/${id}/csv`,
  },
  audit: {
    list: (params = {}) => {
      const q = new URLSearchParams(params).toString();
      return apiFetch(`/api/audit${q ? '?' + q : ''}`);
    },
    csvUrl: () => '/api/audit/export.csv',
  },
};
