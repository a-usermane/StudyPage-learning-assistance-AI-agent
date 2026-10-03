import {$, notify, positionFloating} from '../shared/dom.js';
import {post, coursePath} from '../services/client.js';
import {state} from '../state/store.js';

export class SelectionTools {
  constructor(conversation, sendMessage) {
    this.conversation = conversation;
    this.sendMessage = sendMessage;
    document.addEventListener('pointerup', event => {
      if ($('viewer').contains(event.target)) setTimeout(() => this.capture(), 0);
    });
    document.addEventListener('keyup', event => { if (event.shiftKey && event.key.startsWith('Arrow')) this.capture(); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') this.clear(); });
    document.addEventListener('pointerdown', event => {
      if (!$('viewer').contains(event.target) && !$('selection-toolbar').contains(event.target) && !$('selection-popup').contains(event.target)
          && !event.target.closest('.menu')) this.clear();
    });
    $('reader-surface').addEventListener('scroll', () => this.clear(), {passive: true});
    $('selection-toolbar').onpointerdown = event => event.preventDefault();
    for (const button of document.querySelectorAll('[data-selection-action]')) {
      button.onclick = () => this.open(button.dataset.selectionAction);
    }
    $('popup-close').onclick = () => this.clear();
    $('popup-form').onsubmit = event => {
      event.preventDefault();
      if (!this.popup) return;
      this.popup.question = $('popup-question').value.trim();
      if (!this.popup.question) return notify('请输入问题。', true);
      this.request();
    };
    $('popup-save').onclick = () => this.save();
    $('popup-transfer').onclick = async () => {
      const popup = this.popup;
      if (!popup?.result) return;
      this.clear();
      await this.sendMessage(popup.action, popup.question, popup.source);
    };
  }
  clear() {
    this.abort?.abort();
    this.popup = this.selection = null;
    $('selection-toolbar').hidden = $('selection-popup').hidden = true;
  }
  capture() {
    if (!state.reader || !state.course) return;
    const source = state.reader.getSelectionContext();
    if (!source) { this.clear(); return; }
    if (source.selected_text.length > 5000) return notify('一次最多选择 5000 个字符，请缩小选区。', true);
    this.clear();
    this.selection = source;
    if (state.translation) this.open('translate');
    else positionFloating($('selection-toolbar'), source.rect);
  }
  open(action) {
    const source = this.popup?.source || this.selection;
    if (!source) return;
    this.abort?.abort();
    this.popup = {source, action, courseId: state.course.id, result: null, question: ''};
    $('selection-toolbar').hidden = true;
    $('popup-title').textContent = {translate: '划词翻译', explain: '术语解释', ask: '局部提问', note: '保存笔记'}[action];
    $('popup-quote').textContent = source.selected_text;
    $('popup-form').hidden = action !== 'ask';
    $('popup-question').value = '';
    $('popup-answer').textContent = '';
    $('popup-source').replaceChildren();
    $('note-body').value = '';
    $('popup-transfer').disabled = true;
    $('popup-save').disabled = false;
    positionFloating($('selection-popup'), source.rect);
    if (action === 'translate' || action === 'explain') this.request();
    if (action === 'ask') $('popup-question').focus();
    if (action === 'note') $('note-body').focus();
  }
  async request() {
    const popup = this.popup;
    if (!popup) return;
    this.abort?.abort();
    this.abort = new AbortController();
    const controller = this.abort;
    const {rect, ...source} = popup.source;
    $('popup-answer').textContent = '正在读取本地演示内容…';
    $('popup-save').disabled = $('popup-transfer').disabled = true;
    try {
      const result = await post('/api/demo', {course_id: popup.courseId, ...source,
        action: popup.action, question: popup.question}, {signal: controller.signal});
      if (this.popup !== popup || controller.signal.aborted) return;
      popup.result = result;
      $('popup-answer').textContent = result.content;
      $('popup-source').replaceChildren(this.conversation.sourceButton(result.citation));
      $('popup-transfer').disabled = false;
      positionFloating($('selection-popup'), popup.source.rect);
    } catch (error) {
      if (!controller.signal.aborted && this.popup === popup) $('popup-answer').textContent = error.message;
    } finally {
      if (this.popup === popup && !controller.signal.aborted) $('popup-save').disabled = false;
    }
  }
  async save() {
    const popup = this.popup;
    if (!popup) return;
    const {rect, ...source} = popup.source;
    const body = [popup.result?.content, $('note-body').value.trim()].filter(Boolean).join('\n\n我的笔记：\n');
    $('popup-save').disabled = true;
    try {
      await post(coursePath(popup.courseId, 'notes'), {...source, body, demo: Boolean(popup.result)});
      if (state.course?.id === popup.courseId) await this.conversation.refreshNotes();
      if (this.popup === popup) this.clear();
      notify('笔记已保存在本机。');
    } catch (error) { notify(error.message, true); }
    finally { $('popup-save').disabled = false; }
  }
}
