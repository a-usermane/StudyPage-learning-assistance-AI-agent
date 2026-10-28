import {$, node, notify, locationLabel} from '../shared/dom.js';
import {api, post, coursePath} from '../services/client.js';
import {registerTextBody} from '../services/text-sources.js';

export class Conversation {
  constructor(onSource) {
    this.onSource = onSource;
    this.courseId = null;
    this.historyVersion = this.notesVersion = 0;
    $('tab-chat').onclick = () => this.tab('chat');
    $('tab-notes').onclick = () => this.tab('notes');
    $('notes-current').onchange = () => this.refreshNotes();
  }
  tab(name) {
    for (const tab of ['chat', 'notes']) {
      $(`tab-${tab}`).classList.toggle('active', tab === name);
      $(`tab-${tab}`).setAttribute('aria-selected', String(tab === name));
      $(`${tab}-panel`).hidden = tab !== name;
    }
  }
  sourceButton(source) {
    source = source.source || source;
    const generic = source.kind === 'message' || source.kind === 'note';
    const button = node('button', 'source-button', generic ? '↗ ' + (source.name || (source.kind === 'message' ? '对话消息' : '笔记'))
      : source.document_id ? `↗ ${source.name} · ${locationLabel(source)}` : `${source.name || '来源快照'} · 原资料已删除`);
    if (source.document_id && source.line_start) button.textContent = '↗ ' + source.name + ' · 第 ' + source.line_start + '–' + source.line_end + ' 行';
    button.disabled = !generic && !source.document_id;
    button.onclick = () => this.onSource(source).catch(error => notify(error.message, true));
    return button;
  }
  async load(courseId, documentId = null) {
    this.courseId = courseId;
    this.documentId = documentId;
    $('messages').replaceChildren(node('p', 'empty-state', '正在读取课程记录…'));
    await Promise.all([this.refreshHistory(), this.refreshNotes()]);
  }
  async setDocument(documentId) {
    this.documentId = documentId;
    if ($('notes-current').checked) await this.refreshNotes();
  }
  async refreshHistory() {
    const id = this.courseId, version = ++this.historyVersion;
    if (!id) return;
    const messages = await api(coursePath(id, 'messages'));
    if (this.courseId !== id || version !== this.historyVersion) return;
    const container = $('messages'); container.replaceChildren();
    if (!messages.length) {
      container.append(node('div', 'chat-intro', '从一个问题开始'),
        node('p', 'empty-state', '阅读资料后选中文字提问，或在下方输入问题。切换文件时，这门课程的对话会保留。'));
    }
    for (const message of messages) {
      const article = node('article', 'message ' + message.role);
      article.dataset.messageId = message.id;
      article.append(node('div', 'role', message.role === 'user' ? '你' : '课程书桌'));
      if (message.role === 'assistant' && message.mode === 'demo') article.append(node('span', 'demo-badge', '演示模式，未连接 AI'));
      article.append(registerTextBody(node('div', 'message-body', message.content), 'message', message.id, id, 'content'));
      const actions = node('div', 'message-actions');
      const citations = message.citations?.length ? message.citations : (message.source || message.document_id || message.name !== '课程问答' ? [message] : []);
      for (const citation of citations) actions.append(this.sourceButton(citation));
      if (message.role === 'assistant') {
        const save = node('button', 'quiet', '保存为笔记');
        save.disabled = false;
        save.onclick = async () => {
          if ([...message.content].length > 10000) return notify('回复超过笔记长度上限，请选择需要保留的片段保存。', true);
          save.disabled = true;
          try {
            await post(coursePath(id, 'notes'), {source: {kind: 'message', id: message.id, start: 0, end: 0, text_field: 'content'},
              selected_text: '', body: message.content, demo: message.mode === 'demo'});
            if (this.courseId === id) await this.refreshNotes();
            notify('已保存为笔记。');
          } catch (error) { notify(error.message, true); }
          finally { save.disabled = false; }
        };
        actions.append(save);
      }
      article.append(actions); container.append(article);
    }
    container.scrollTop = container.scrollHeight;
  }
  async refreshNotes() {
    const id = this.courseId, version = ++this.notesVersion;
    if (!id) return;
    const filter = $('notes-current').checked && this.documentId ? '?document_id=' + this.documentId : '';
    const notes = await api(coursePath(id, 'notes') + filter);
    if (this.courseId !== id || version !== this.notesVersion) return;
    $('note-count').textContent = String(notes.length);
    const container = $('notes-list'); container.replaceChildren();
    if (!notes.length) container.append(node('p', 'empty-state', '还没有笔记。可以保存所选原文、自己的理解，或一条演示回复。'));
    for (const note of notes) {
      const article = node('article', 'note');
      article.dataset.noteId = note.id;
      article.append(this.sourceButton(note));
      for (const citation of note.source?.citations || []) article.append(this.sourceButton(citation));
      if (note.demo) article.append(node('div', 'demo-badge', '包含演示内容，未连接 AI'));
      if (note.selected_text) article.append(registerTextBody(node('blockquote', '', note.selected_text), 'note', note.id, id, 'selected_text'));
      article.append(registerTextBody(node('div', 'note-body', note.body), 'note', note.id, id, 'body'));
      const footer = node('div', 'note-footer');
      footer.append(node('span', '', new Date(note.created_at).toLocaleString()));
      const remove = node('button', 'quiet danger', '删除');
      remove.onclick = async () => {
        if (!confirm('删除这条笔记？')) return;
        try { await api(`/api/notes/${note.id}`, {method: 'DELETE'}); if (this.courseId === id) await this.refreshNotes(); }
        catch (error) { notify(error.message, true); }
      };
      footer.append(remove); article.append(footer); container.append(article);
    }
  }
  async navigateSource(source) {
    const isMessage = source.kind === 'message';
    this.tab(isMessage ? 'chat' : 'notes');
    if (isMessage) await this.refreshHistory();
    else { $('notes-current').checked = false; await this.refreshNotes(); }
    const id = isMessage ? 'messageId' : 'noteId';
    const root = isMessage ? $('messages') : $('notes-list');
    const target = [...root.querySelectorAll(isMessage ? '[data-message-id]' : '[data-note-id]')].find(el => el.dataset[id] === source.id);
    if (!target) return notify('原消息或笔记已不存在，选区文字快照仍保留在记录中。', true);
    target.scrollIntoView({block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
    target.classList.add('source-highlight');
    setTimeout(() => target.classList.remove('source-highlight'), 1800);
  }
  clear() {
    this.courseId = this.documentId = null;
    this.historyVersion++; this.notesVersion++;
  }
}
