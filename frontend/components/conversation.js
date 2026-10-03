import {$, node, notify, locationLabel} from '../shared/dom.js';
import {api, post, coursePath} from '../services/client.js';

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
    const button = node('button', 'source-button', source.document_id
      ? `↗ ${source.name} · ${locationLabel(source)}` : `${source.name} · 原资料已删除`);
    button.disabled = !source.document_id;
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
      article.append(node('div', 'role', message.role === 'user' ? '你' : '课程书桌'));
      if (message.role === 'assistant') article.append(node('span', 'demo-badge', '演示模式，未连接 AI'));
      article.append(node('div', 'message-body', message.content));
      const actions = node('div', 'message-actions');
      actions.append(this.sourceButton(message));
      if (message.role === 'assistant') {
        const save = node('button', 'quiet', '保存为笔记');
        save.disabled = !message.document_id;
        save.onclick = async () => {
          save.disabled = true;
          try {
            await post(coursePath(id, 'notes'), {document_id: message.document_id,
              page_start: message.page_start, page_end: message.page_end,
              selected_text: message.selected_text, body: message.content, demo: true});
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
      article.append(this.sourceButton(note));
      if (note.demo) article.append(node('div', 'demo-badge', '包含演示内容，未连接 AI'));
      if (note.selected_text) article.append(node('blockquote', '', note.selected_text));
      article.append(node('div', 'note-body', note.body));
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
  clear() {
    this.courseId = this.documentId = null;
    this.historyVersion++; this.notesVersion++;
  }
}
