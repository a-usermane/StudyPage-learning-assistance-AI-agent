export function preference(key, fallback) {
  try { const value = localStorage.getItem('study-' + key); return value === null ? fallback : JSON.parse(value); }
  catch { return fallback; }
}
export function remember(key, value) {
  try { localStorage.setItem('study-' + key, JSON.stringify(value)); } catch { /* Private mode still works in memory. */ }
}
export const state = {
  courses: [], course: null, documents: [], document: null, reader: null,
  uploadLimit: 20 * 1024 * 1024, uploadBusy: false, chatBusy: false,
  translation: preference('translation', false), menuOpen: preference('menu-open', true),
  swapped: preference('swapped', false), split: preference('split', 38),
  failedUploads: new Map()
};
