/**
 * Toast notification stack. Auto-dismisses after 5s.
 */
let _container = null;

function _ensureContainer() {
  if (!_container) {
    _container = document.createElement('div');
    _container.id = 'toast-container';
    document.body.appendChild(_container);
  }
  return _container;
}

function _show(message, type) {
  const c = _ensureContainer();
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  c.appendChild(toast);
  setTimeout(() => { toast.remove(); }, 5000);
}

export const toast = {
  success: (msg) => _show(msg, 'success'),
  error:   (msg) => _show(msg, 'error'),
  warn:    (msg) => _show(msg, 'warn'),
};
