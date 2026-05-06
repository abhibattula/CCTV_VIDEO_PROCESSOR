/**
 * Client-side ES module router.
 * Renders nav once; swaps only <main id="app"> on navigation.
 */
import { api } from './api.js';

const ROUTES = {
  '/':           () => import('./pages/dashboard.js'),
  '/jobs/new':   () => import('./pages/new-job.js'),
  '/jobs':       () => import('./pages/job-queue.js'),
  '/jobs/:id':   () => import('./pages/job-detail.js'),
  '/reports':    () => import('./pages/reports.js'),
  '/settings':   () => import('./pages/settings.js'),
  '/system':     () => import('./pages/system.js'),
  '/audit':      () => import('./pages/audit.js'),
};

let _currentPage = null;

function matchRoute(pathname) {
  for (const [pattern, loader] of Object.entries(ROUTES)) {
    if (!pattern.includes(':')) {
      if (pathname === pattern || pathname === pattern + '/') return { loader, params: {} };
    } else {
      const parts = pattern.split('/');
      const pathParts = pathname.split('/');
      if (parts.length !== pathParts.length) continue;
      const params = {};
      let match = true;
      for (let i = 0; i < parts.length; i++) {
        if (parts[i].startsWith(':')) {
          params[parts[i].slice(1)] = pathParts[i];
        } else if (parts[i] !== pathParts[i]) {
          match = false; break;
        }
      }
      if (match) return { loader, params };
    }
  }
  return null;
}

export async function navigate(path) {
  history.pushState({}, '', path);
  await _render(path);
}

async function _render(pathname) {
  const matched = matchRoute(pathname);
  const app = document.getElementById('app');
  if (!app) return;

  if (_currentPage && typeof _currentPage.unmount === 'function') {
    _currentPage.unmount();
    _currentPage = null;
  }

  app.innerHTML = '';

  if (!matched) {
    app.textContent = '404 — Page not found';
    return;
  }

  try {
    const module = await matched.loader();
    _currentPage = module;
    await module.mount(app, matched.params);
  } catch (e) {
    app.textContent = `Failed to load page: ${e.message}`;
  }
}

// Update nav active state
function _updateNav(pathname) {
  document.querySelectorAll('.nav-link').forEach(link => {
    const href = link.getAttribute('href');
    link.classList.toggle('active', pathname === href || (href !== '/' && pathname.startsWith(href)));
  });
}

window.addEventListener('popstate', () => {
  _render(location.pathname);
  _updateNav(location.pathname);
});

document.addEventListener('click', (e) => {
  const link = e.target.closest('a[href]');
  if (!link) return;
  const href = link.getAttribute('href');
  if (!href || href.startsWith('http') || href.startsWith('#') || href.startsWith('mailto')) return;
  e.preventDefault();
  navigate(href);
  _updateNav(href);
});

// Dark mode
const saved = localStorage.getItem('darkMode');
if (saved === 'dark' || (saved === null && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
  document.documentElement.setAttribute('data-theme', 'dark');
}

// Service Worker registration (ISSUE-01, PWA)
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/static/sw.js').catch(() => {});
}

// Boot
document.addEventListener('DOMContentLoaded', () => {
  // Mount nav
  import('./components/nav.js').then(m => {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) m.mount(sidebar);
  });
  _render(location.pathname);
  _updateNav(location.pathname);
});
