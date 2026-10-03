import {ReaderBase} from './base.js';
import {api} from '../services/client.js';
import {node} from '../shared/dom.js';

export class TextReader extends ReaderBase {
  async load(document, location = {page_start: 1}) {
    this.document = document;
    this.element.className = 'textViewer';
    this.element.replaceChildren();
    for (let page = 1; page <= document.pages; page++) {
      const article = node('article', 'text-page');
      article.dataset.pageNumber = String(page);
      article.style.minHeight = document.extension === '.pptx' ? '300px' : '200px';
      const label = node('h2', 'page-label', document.extension === '.pptx' ? `幻灯片 ${page}` : document.name);
      const content = node('div', 'page-content', '正在读取…');
      article.append(label, content);
      this.element.append(article);
    }
    this.observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) this.loadPage(entry.target);
    }, {root: this.container, rootMargin: '500px'});
    for (const article of this.element.children) this.observer.observe(article);
    this.scrollListener = () => this.onLocation(this.getVisibleLocation());
    this.container.addEventListener('scroll', this.scrollListener, {passive: true});
    this.scrollToSource(location);
    const article = this.element.querySelector(`[data-page-number="${location.page_start || 1}"]`) || this.element.firstElementChild;
    await this.loadPage(article);
    if (!this.destroyed) {
      this.scrollToSource(location);
      this.onLocation(this.getVisibleLocation());
    }
  }
  async loadPage(article) {
    if (!article || article.dataset.loaded || this.destroyed) return;
    article.dataset.loaded = 'loading';
    try {
      const data = await api(`/api/documents/${this.document.id}/pages/${article.dataset.pageNumber}`, {signal: this.abort.signal});
      if (this.destroyed) return;
      const content = article.querySelector('.page-content');
      content.replaceChildren();
      if (['.txt', '.md', '.pptx'].includes(this.document.extension)) {
        content.append(node('div', 'plain-text', data.text || '此页没有可提取的文字。'));
      } else {
        const code = node('pre', 'code');
        const fragment = document.createDocumentFragment();
        for (const line of data.text.split('\n')) fragment.append(node('span', 'code-line', line || '\u200b'));
        code.append(fragment); content.append(code);
      }
      article.dataset.loaded = 'ready';
    } catch (error) {
      if (this.destroyed) return;
      article.dataset.loaded = 'error';
      const content = article.querySelector('.page-content');
      content.textContent = error.message;
      const retry = node('button', 'quiet', '重试');
      retry.onclick = () => { delete article.dataset.loaded; this.loadPage(article); };
      content.append(retry);
    }
  }
  getVisibleLocation() {
    const bounds = this.container.getBoundingClientRect();
    let page = 1, maxArea = -1;
    for (const article of this.element.children) {
      const rect = article.getBoundingClientRect();
      const area = Math.max(0, Math.min(rect.bottom, bounds.bottom) - Math.max(rect.top, bounds.top));
      if (area > maxArea) { page = Number(article.dataset.pageNumber); maxArea = area; }
    }
    return this.locationFor(page);
  }
  scrollToSource(source) {
    const article = this.element.querySelector(`[data-page-number="${source.page_start || 1}"]`);
    if (!article) return;
    this.container.scrollTop = article.offsetTop + (source.offset || 0) * article.offsetHeight;
    this.loadPage(article);
  }
  setZoom(value) {
    const location = this.getVisibleLocation();
    this.zoom = Math.max(.5, Math.min(2.5, value));
    this.element.style.fontSize = `${14 * this.zoom}px`;
    this.scrollToSource(location);
  }
  async destroy() {
    await super.destroy();
    this.observer?.disconnect();
    this.container.removeEventListener('scroll', this.scrollListener);
    this.element.style.fontSize = '';
  }
}
