// Source capture is shared by PDF and text readers and never uses the last visible page.
export class ReaderBase {
  constructor(container, viewer, onLocation) {
    this.container = container;
    this.element = viewer;
    this.onLocation = onLocation;
    this.abort = new AbortController();
    this.destroyed = false;
    this.zoom = 1;
  }
  getSelectionContext() {
    const selection = window.getSelection();
    if (!selection?.rangeCount || selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    if (!this.element.contains(range.startContainer) || !this.element.contains(range.endContainer)) return null;
    const pageFor = target => (target.nodeType === Node.ELEMENT_NODE ? target : target.parentElement)?.closest('[data-page-number]');
    const start = pageFor(range.startContainer), end = pageFor(range.endContainer);
    if (!start || !end) return null;
    const text = selection.toString().replaceAll('\u200b', '').trim();
    if (!text) return null;
    const rectangles = [...range.getClientRects()];
    const bounds = this.container.getBoundingClientRect();
    const rect = rectangles.find(r => r.height > 0 && r.bottom > bounds.top && r.top < bounds.bottom) || range.getBoundingClientRect();
    if (rect.bottom <= bounds.top || rect.top >= bounds.bottom) return null;
    return {document_id: this.document.id,
      page_start: Math.min(Number(start.dataset.pageNumber), Number(end.dataset.pageNumber)),
      page_end: Math.max(Number(start.dataset.pageNumber), Number(end.dataset.pageNumber)), selected_text: text,
      rect: {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom}};
  }
  locationFor(page) {
    const element = this.element.querySelector(`[data-page-number="${page}"]`);
    const relative = element ? (this.container.scrollTop - element.offsetTop) / element.offsetHeight : 0;
    return {page_start: page, page_end: page, offset: Math.max(0, Math.min(.99, relative))};
  }
  async destroy() {
    this.destroyed = true;
    this.abort.abort();
  }
}
