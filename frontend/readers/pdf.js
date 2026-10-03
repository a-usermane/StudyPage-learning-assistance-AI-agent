import {ReaderBase} from './base.js';
import {notify} from '../shared/dom.js';

export class PDFReader extends ReaderBase {
  async load(document, location = {page_start: 1}) {
    this.document = document;
    // The bundled viewer reads globalThis.pdfjsLib during module evaluation.
    const pdfjs = await import('/static/vendor/pdfjs/build/pdf.mjs');
    const components = await import('/static/vendor/pdfjs/web/pdf_viewer.mjs');
    if (this.destroyed) return;
    this.components = components;
    pdfjs.GlobalWorkerOptions.workerSrc = '/static/vendor/pdfjs/build/pdf.worker.mjs';
    this.element.className = 'pdfViewer';
    this.element.replaceChildren();
    this.events = new components.EventBus();
    this.links = new components.PDFLinkService({eventBus: this.events});
    this.pdfViewer = new components.PDFViewer({
      container: this.container, viewer: this.element, eventBus: this.events, linkService: this.links,
      textLayerMode: 1, annotationMode: 0, annotationEditorMode: -1,
      maxCanvasPixels: 8 * 1024 * 1024, maxCanvasDim: 8192,
      enableDetailCanvas: false, enableAutoLinking: false, abortSignal: this.abort.signal
    });
    this.links.setViewer(this.pdfViewer);
    this.events.on('pagechanging', () => { if (!this.destroyed) this.onLocation(this.getVisibleLocation()); });
    this.events.on('pagerendered', event => {
      if (event.error && !this.destroyed) notify('页面渲染失败：' + event.error.message, true);
    });
    const initialized = new Promise(resolve => {
      this.events.on('pagesinit', () => {
        this.pdfViewer.scrollMode = components.ScrollMode.VERTICAL;
        this.pdfViewer.currentScaleValue = 'page-width';
        this.scrollToSource(location);
        resolve();
      });
      this.abort.signal.addEventListener('abort', resolve, {once: true});
    });
    this.task = pdfjs.getDocument({url: `/api/documents/${document.id}/original`,
      cMapUrl: '/static/vendor/pdfjs/cmaps/', cMapPacked: true,
      standardFontDataUrl: '/static/vendor/pdfjs/standard_fonts/',
      wasmUrl: '/static/vendor/pdfjs/wasm/', iccUrl: '/static/vendor/pdfjs/iccs/', isEvalSupported: false});
    const pdf = await this.task.promise;
    if (this.destroyed) return;
    this.links.setDocument(pdf);
    this.pdfViewer.setDocument(pdf);
    await initialized;
    if (this.destroyed) return;
    this.scrollListener = () => this.onLocation(this.getVisibleLocation());
    this.container.addEventListener('scroll', this.scrollListener, {passive: true});
    this.resize = new ResizeObserver(() => {
      clearTimeout(this.resizeTimer);
      this.resizeTimer = setTimeout(() => this.resizeToWidth(), 150);
    });
    this.resize.observe(this.container);
    this.onLocation(this.getVisibleLocation());
  }
  getVisibleLocation() {
    return this.locationFor(this.pdfViewer?.currentPageNumber || 1);
  }
  scrollToSource(source) {
    if (!this.pdfViewer?.pdfDocument) return;
    const page = Math.max(1, Math.min(this.document.pages, source.page_start || 1));
    this.pdfViewer.scrollPageIntoView({pageNumber: page});
    const element = this.element.querySelector(`[data-page-number="${page}"]`);
    if (element && source.offset) this.container.scrollTop = element.offsetTop + element.offsetHeight * source.offset;
  }
  resizeToWidth() {
    if (this.destroyed || !this.pdfViewer?.pdfDocument) return;
    const location = this.getVisibleLocation();
    this.pdfViewer.currentScaleValue = 'page-width';
    if (this.zoom !== 1) this.pdfViewer.currentScale = this.pdfViewer.currentScale * this.zoom;
    this.scrollToSource(location);
  }
  setZoom(value) {
    this.zoom = Math.max(.5, Math.min(2.5, value));
    this.resizeToWidth();
  }
  async destroy() {
    await super.destroy();
    clearTimeout(this.resizeTimer);
    this.resize?.disconnect();
    this.container.removeEventListener('scroll', this.scrollListener);
    this.pdfViewer?.setDocument(null);
    this.links?.setDocument(null);
    await this.task?.destroy().catch(() => {});
  }
}
