const CACHE_NAME = 'cctv-shell-v1';

const SHELL_URLS = [
  '/',
  '/jobs/new',
  '/jobs',
  '/reports',
  '/settings',
  '/system',
  '/audit',
  '/static/css/base.css',
  '/static/css/layout.css',
  '/static/css/components.css',
  '/static/js/app.js',
  '/static/js/api.js',
  '/static/js/sse-client.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((c) => c.addAll(SHELL_URLS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // NEVER cache API responses — always live
  if (url.pathname.startsWith('/api/')) return;

  e.respondWith(
    caches.match(e.request).then((cached) => {
      if (cached) return cached;
      return fetch(e.request).catch(() => {
        // Offline fallback: serve shell for navigation requests
        if (e.request.mode === 'navigate') {
          return caches.match('/');
        }
      });
    })
  );
});
