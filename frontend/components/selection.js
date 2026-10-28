import {$, notify, positionFloating} from '../shared/dom.js';
import {post, coursePath, runAgent} from '../services/client.js';
import {state} from '../state/store.js';
import {SelectionSession} from './selection-state.js';
import {SelectionPopup} from './selection-popup.js';
import {TextSourceRegistry, bodyAdapter, readerAdapter, operationPayload, sourceKey} from '../services/text-sources.js';

// Captures sources and coordinates transport. The view and session own presentation/state.
export class SelectionTools {
  constructor(conversation, sendMessage) {
    this.conversation = conversation; this.sendMessage = sendMessage;
    this.sources = new TextSourceRegistry();
    this.sources.register(readerAdapter(() => state.reader));
    this.sources.register(bodyAdapter('message'));
    this.sources.register(bodyAdapter('note'));
    this.view = new SelectionPopup({
      switch: action => this.open(action), close: () => this.clear(),
      expand: () => this.expand(), collapse: () => this.collapse(),
      draft: value => { if (this.popup) this.popup.current.draft = value; },
      includeReply: include => { if (this.popup) { this.popup.includeReply = include; this.render(); } },
      submit: () => this.submit(), retry: () => this.request(), stop: () => this.stop(),
      detail: () => this.explainDetail(),
      copy: () => this.copy(), save: () => this.save(), transfer: () => this.transfer(),
      sourceButton: source => conversation.sourceButton(source)
    });
    document.addEventListener('pointerup', event => {
      if (!event.target.closest('#selection-popup, #selection-toolbar, input, textarea, button, select, .menu')) setTimeout(() => this.capture(), 0);
    });
    document.addEventListener('keyup', event => { if (event.shiftKey || (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') setTimeout(() => this.capture(), 0); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') this.clear(); });
    document.addEventListener('pointerdown', event => {
      if (!$('viewer').contains(event.target) && !$('selection-toolbar').contains(event.target) && !$('selection-popup').contains(event.target)
          && !event.target.closest('[data-text-source], .menu')
          && !(this.selection?.kind !== 'document' && event.target.closest('#document-select, .reader-toolbar'))) this.clear();
    });
    document.addEventListener('layoutstart', () => this.clear());
    window.addEventListener('resize', () => this.clear());
    $('reader-surface').addEventListener('scroll', () => this.clearDocument(), {passive: true});
    $('selection-toolbar').onpointerdown = event => event.preventDefault();
    for (const button of document.querySelectorAll('[data-selection-action]')) button.onclick = () => this.open(button.dataset.selectionAction);
  }
  cancelRequest() {
    this.abort?.abort();
    if (this.popup) for (const tab of Object.values(this.popup.tabs)) {
      if (tab.status === 'loading') tab.status = tab.result ? 'ready' : 'idle';
      tab.progress = '';
    }
  }
  stop() {
    if (!this.popup) return;
    this.cancelRequest();
    this.popup.current.status = 'error'; this.popup.current.error = '生成已停止，可重试。';
    this.render();
  }
  clear() {
    this.cancelRequest(); this.popup = this.selection = null;
    $('selection-toolbar').hidden = true; this.view.hide();
  }
  clearDocument() { if (!this.selection?.kind || this.selection.kind === 'document') this.clear(); }
  capture() {
    if (!state.course) return;
    const source = this.sources.capture(state.course.id);
    if (!source) { this.clear(); return; }
    if ([...source.selected_text].length > 5000) { this.clear(); return notify('一次最多选择 5000 个字符，请缩小选区。', true); }
    if (this.popup && sourceKey(source) === sourceKey(this.popup.source)) return;
    this.clear(); this.selection = source;
    if (state.translation) this.open('translate');
    else positionFloating($('selection-toolbar'), source.rect);
  }
  open(action) {
    if (!this.popup && this.selection) this.popup = new SelectionSession(this.selection, this.selection.course_id || state.course.id);
    if (!this.popup || this.popup.saving) return;
    this.cancelRequest(); this.popup.switch(action);
    $('selection-toolbar').hidden = true;
    this.render();
    if (['translate', 'explain'].includes(action) && !this.popup.current.result) this.request();
  }
  render() { if (this.popup) this.view.render(this.popup); }
  expand() {
    if (!this.popup) return;
    this.popup.current.expanded = true; this.render(); this.view.input.focus(this.popup.action === 'note');
  }
  collapse() {
    if (!this.popup) return;
    this.popup.current.expanded = false; this.render(); $('popup-input-entry').focus();
  }
  submit() {
    if (!this.popup || this.popup.saving) return;
    if (this.popup.action === 'note') return this.save();
    const question = this.popup.current.draft.trim();
    if (!question) return notify('请输入问题。', true);
    this.request(question);
  }
  explainDetail() {
    if (!this.popup || this.popup.action !== 'explain' || this.popup.saving || this.popup.current.status === 'loading') return;
    this.popup.current.detailed = true;
    // Generate immediately, independently of an unsent input draft.
    this.request(this.popup.current.question || '');
  }
  async request(question = this.popup?.current.draft.trim() || '') {
    const popup = this.popup;
    if (!popup || popup.action === 'note' || popup.saving) return;
    const action = popup.action;
    if (action === 'ask' && !question) return notify('请输入问题。', true);
    this.cancelRequest(); this.abort = new AbortController();
    const controller = this.abort, tab = popup.current;
    tab.status = 'loading'; tab.error = ''; tab.progress = ''; this.render();
    const source = operationPayload(popup.source);
    try {
      const requestAction = action === 'explain' && tab.detailed ? 'explain_detail' : action;
      const result = await runAgent(popup.courseId, {...source, action: requestAction, question,
        session_id: popup.sessionId, persist: false, mode: state.agentMode}, {signal: controller.signal,
        onEvent: event => {
          if (this.popup !== popup || controller.signal.aborted || popup.action !== action) return;
          if (event.type === 'start') tab.mode = event.data.mode;
          if (event.type === 'delta') { tab.progress += event.data.text; this.render(); }
        }});
      if (this.popup !== popup || controller.signal.aborted || popup.action !== action) return;
      popup.complete(action, result, question);
    } catch (error) {
      if (!controller.signal.aborted && this.popup === popup) { tab.status = 'error'; tab.error = error.message; }
    } finally { if (this.popup === popup && !controller.signal.aborted) this.render(); }
  }
  async copy() {
    if (!this.popup) return;
    const text = this.popup.action === 'note' ? this.popup.notePayload().body : this.popup.current.result?.content;
    if (!text) return;
    try { await navigator.clipboard.writeText(text); notify('已复制内容。'); }
    catch { notify('浏览器未允许复制，请手动选择回复文字复制。', true); }
  }
  async transfer() {
    const popup = this.popup;
    if (!popup?.current.result) return;
    try {
      await post(coursePath(popup.courseId, 'agent/runs/' + popup.current.result.run_id + '/transfer'), {});
      this.clear(); this.conversation.tab('chat');
      await this.conversation.refreshHistory();
      notify('已转入主对话，没有重复生成。');
    } catch (error) { notify(error.message, true); }
  }
  async save() {
    const popup = this.popup;
    if (!popup || popup.saving || popup.current.status === 'loading') return;
    const payload = popup.notePayload(); popup.saving = true; this.render();
    try {
      await post(coursePath(popup.courseId, 'notes'), payload);
      if (state.course?.id === popup.courseId) await this.conversation.refreshNotes();
      if (this.popup === popup) this.clear();
      notify('笔记已保存在本机。');
    } catch (error) { notify(error.message, true); }
    finally { popup.saving = false; if (this.popup === popup) this.render(); }
  }
}
