/* global window, document */
/* Blocking, same-origin bootstrap: apply appearance before the first paint.
   Only the non-sensitive theme preference is stored. Never touches session data. */
(() => {
  if (window.nexusTheme) return;
  const key = 'nexus-theme';
  const media = typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  const listeners = new Set();
  const read = () => {
    try {
      const value = window.localStorage.getItem(key);
      return value === 'light' || value === 'dark' ? value : 'system';
    } catch { return 'system'; }
  };
  let preference = read();
  let snapshot = '';
  const apply = () => {
    const theme = preference === 'system' ? (media?.matches ? 'dark' : 'light') : preference;
    document.documentElement.dataset.theme = theme;
    // A safe canvas while the render-blocking stylesheet/app is still loading.
    document.documentElement.style.colorScheme = theme;
    document.documentElement.style.backgroundColor = theme === 'dark' ? '#151C27' : '#FAF8F3';
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#151C27' : '#FAF8F3');
    const next = preference + ':' + theme;
    if (next === snapshot) return;
    snapshot = next;
    for (const listener of listeners) listener();
  };
  window.nexusTheme = {
    getSnapshot: () => snapshot,
    subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener); },
    setPreference: value => {
      if (!['light', 'dark', 'system'].includes(value)) return;
      preference = value;
      try {
        if (value === 'system') window.localStorage.removeItem(key);
        else window.localStorage.setItem(key, value);
      } catch { /* Appearance still works in this tab when storage is unavailable. */ }
      apply();
    },
  };
  if (media?.addEventListener) media.addEventListener('change', () => { if (preference === 'system') apply(); });
  else media?.addListener(() => { if (preference === 'system') apply(); });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) { preference = read(); apply(); }
  });
  apply();
})();
