'use strict';
(() => {
  const storageKey = 'hitechdrive-theme';
  const preference = window.matchMedia('(prefers-color-scheme: dark)');
  let stored = null;
  try { stored = window.localStorage.getItem(storageKey); } catch {}
  let explicit = stored === 'light' || stored === 'dark';
  function apply(theme) {
    document.documentElement.dataset.theme = theme;
    const button = document.getElementById('theme-toggle');
    if (button) {
      const dark = theme === 'dark';
      const label = dark ? 'Ativar tema claro' : 'Ativar tema escuro';
      button.setAttribute('aria-pressed', String(dark));
      button.setAttribute('aria-label', label);
      button.title = label;
    }
    window.dispatchEvent(new CustomEvent('hitech:theme', {detail: theme}));
  }
  apply(explicit ? stored : preference.matches ? 'dark' : 'light');
  document.addEventListener('DOMContentLoaded', () => {
    apply(document.documentElement.dataset.theme);
    document.getElementById('theme-toggle').addEventListener('click', () => {
      const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      explicit = true;
      try { window.localStorage.setItem(storageKey, theme); } catch {}
      apply(theme);
    });
  });
  preference.addEventListener('change', event => { if (!explicit) apply(event.matches ? 'dark' : 'light'); });
  window.addEventListener('storage', event => {
    if (event.key !== storageKey) return;
    explicit = event.newValue === 'light' || event.newValue === 'dark';
    apply(explicit ? event.newValue : preference.matches ? 'dark' : 'light');
  });
})();
