// Adapters own selection capture; actions consume immutable, reader-independent sources.
export function sourceReference(value) {
  if (!value.kind) return {kind: 'document', id: value.document_id, page_start: value.page_start, page_end: value.page_end};
  const ref = {kind: value.kind, id: value.id};
  if (ref.kind === 'document') Object.assign(ref, {page_start: value.page_start, page_end: value.page_end});
  else Object.assign(ref, {start: value.start, end: value.end, text_field: value.text_field});
  return ref;
}
export function operationPayload(value) {
  if (!value.kind) {
    const {rect, ...legacy} = value;
    return legacy;
  }
  return {source: sourceReference(value), selected_text: value.selected_text};
}
export function sourceKey(value) {
  return JSON.stringify([value.course_id, sourceReference(value), value.selected_text]);
}
export function registerTextBody(element, kind, id, courseId, field = 'body') {
  Object.assign(element.dataset, {textSource: kind, sourceId: id, courseId, textField: field});
  return element;
}
const bodyRoot = node => (node?.nodeType === 1 ? node : node?.parentElement)?.closest('[data-text-source]');
export class TextSourceRegistry {
  constructor() { this.adapters = []; }
  register(adapter) { this.adapters.push(adapter); return () => { this.adapters = this.adapters.filter(a => a !== adapter); }; }
  capture(courseId) {
    const selection = window.getSelection();
    if (!selection?.rangeCount || selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    for (const adapter of this.adapters) {
      if (!adapter.accepts(range)) continue;
      const source = adapter.capture(selection, range, courseId);
      return source ? Object.freeze({...source, course_id: courseId, rect: Object.freeze({...source.rect})}) : null;
    }
    return null;
  }
}
export function bodyAdapter(kind) {
  return {
    accepts: range => bodyRoot(range.startContainer)?.dataset.textSource === kind,
    capture(selection, range, courseId) {
      const root = bodyRoot(range.startContainer);
      if (root !== bodyRoot(range.endContainer) || root.dataset.courseId !== courseId) return null;
      // Count Unicode code points, matching Python, including emoji before the selection.
      const prefix = range.cloneRange(); prefix.selectNodeContents(root); prefix.setEnd(range.startContainer, range.startOffset);
      const start = [...prefix.toString()].length, text = range.toString();
      if (!text.trim()) return null;
      const rect = range.getBoundingClientRect();
      return {kind, id: root.dataset.sourceId, text_field: root.dataset.textField,
        start, end: start + [...text].length, selected_text: text,
        name: kind === 'message' ? '对话消息' : '笔记',
        rect: {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom}};
    }
  };
}
export function readerAdapter(getReader) {
  return {
    accepts: range => {
      const reader = getReader();
      return reader?.element.contains(range.startContainer) && reader.element.contains(range.endContainer);
    },
    capture() {
      const source = getReader()?.getSelectionContext();
      return source ? {...source, kind: 'document', id: source.document_id, name: getReader().document.name} : null;
    }
  };
}
