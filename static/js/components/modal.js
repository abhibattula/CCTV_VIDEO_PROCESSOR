/**
 * Generic modal overlay. Closes on Escape or overlay click. Traps focus.
 */
let _overlay = null;

export const modal = {
  open(contentEl) {
    if (_overlay) this.close();

    _overlay = document.createElement('div');
    _overlay.className = 'modal-overlay';
    _overlay.setAttribute('role', 'dialog');
    _overlay.setAttribute('aria-modal', 'true');

    const box = document.createElement('div');
    box.className = 'modal-box';

    const closeBtn = document.createElement('button');
    closeBtn.className = 'modal-close';
    closeBtn.textContent = '✕';
    closeBtn.setAttribute('aria-label', 'Close');
    closeBtn.addEventListener('click', () => modal.close());

    box.appendChild(closeBtn);
    box.appendChild(contentEl);
    _overlay.appendChild(box);
    document.body.appendChild(_overlay);

    // Close on overlay background click
    _overlay.addEventListener('click', (e) => {
      if (e.target === _overlay) modal.close();
    });

    // Close on Escape
    document.addEventListener('keydown', _onKeyDown);

    // Focus first focusable
    const focusable = box.querySelector('button, input, select, textarea, a[href]');
    if (focusable) focusable.focus();
  },

  close() {
    if (_overlay) {
      _overlay.remove();
      _overlay = null;
      document.removeEventListener('keydown', _onKeyDown);
    }
  },
};

function _onKeyDown(e) {
  if (e.key === 'Escape') modal.close();
}
