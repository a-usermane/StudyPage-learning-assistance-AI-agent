export const $ = id => document.getElementById(id);
export function node(tag, className = '', text = '') {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = text;
  return element;
}
let toastTimer;
export function notify(message, error = false) {
  const toast = $('toast');
  toast.textContent = message;
  toast.classList.toggle('error', error);
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, error ? 7000 : 4000);
}
export function positionFloating(element, rect) {
  element.hidden = false;
  const width = element.offsetWidth, height = element.offsetHeight;
  element.style.left = Math.max(8, Math.min(rect.left, innerWidth - width - 8)) + 'px';
  const top = rect.bottom + 8 + height <= innerHeight - 8 ? rect.bottom + 8 : rect.top - height - 8;
  element.style.top = Math.max(8, Math.min(top, innerHeight - height - 8)) + 'px';
}
export const categories = {slides: '课件', exercises: '练习', assignments: '作业', code: '代码', other: '其他'};
export function locationLabel(source) {
  return source.page_end && source.page_end !== source.page_start
    ? `第 ${source.page_start}–${source.page_end} 页` : `第 ${source.page_start} 页`;
}
