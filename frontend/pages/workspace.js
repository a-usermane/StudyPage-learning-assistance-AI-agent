import {$, node, notify, categories, locationLabel} from '../shared/dom.js';
import {api, post, coursePath, runAgent} from '../services/client.js';
import {state, preference, remember} from '../state/store.js';
import {createReader} from '../readers/index.js';
import {Conversation} from '../components/conversation.js';
import {SelectionTools} from '../components/selection.js';
import {AutoGrowInput} from '../components/input.js';

export class Workspace {
  constructor(onCoursesChanged) {
    this.onCoursesChanged = onCoursesChanged;
    this.version = this.documentVersion = 0;
    this.conversation = new Conversation(source => this.goSource(source));
    this.selection = new SelectionTools(this.conversation, (...args) => this.send(...args));
    this.composerInput = new AutoGrowInput($('question'), {min: 26});
    this.stopButton = node('button', 'quiet', '停止'); this.stopButton.type = 'button'; this.stopButton.hidden = true;
    this.stopButton.onclick = () => this.chatAbort?.abort();
    document.querySelector('.composer-footer').append(this.stopButton);
    document.addEventListener('composerchange', () => this.composerInput.resize());
    $('document-select').onchange = () => this.loadDocument($('document-select').value).catch(error => notify(error.message, true));
    $('translation-toggle').checked = state.translation;
    $('translation-toggle').onchange = () => { state.translation = $('translation-toggle').checked; remember('translation', state.translation); this.selection.clear(); };
    $('zoom-in').onclick = () => this.zoom((state.reader?.zoom || 1) + .25);
    $('zoom-out').onclick = () => this.zoom((state.reader?.zoom || 1) - .25);
    $('fit-width').onclick = () => this.zoom(1);
    $('summary').onclick = () => this.send('summary');
    $('chat-form').onsubmit = event => { event.preventDefault(); this.send('ask', $('question').value.trim()); };
    $('question').onkeydown = event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); $('chat-form').requestSubmit(); } };
    $('delete-document').onclick = () => this.deleteDocument();
  }
  async load(courseId, preferredDocument) {
    this.chatAbort?.abort();
    const ticket = ++this.version;
    this.documentVersion++;
    this.selection.clear();
    await this.releaseReader();
    if (ticket !== this.version) return;
    this.conversation.clear();
    state.document = null; state.course = null; state.documents = [];
    this.controls();
    const [course, documents] = await Promise.all([api(coursePath(courseId)), api(coursePath(courseId, 'documents'))]);
    if (ticket !== this.version) return;
    state.course = course; state.documents = documents;
    $('course-heading').textContent = course.name;
    this.fileOptions(); this.failures();
    const remembered = preferredDocument || preference('file-' + courseId, null);
    const chosen = documents.find(doc => doc.id === remembered) || documents[0];
    await Promise.all([this.conversation.load(courseId, chosen?.id), chosen ? this.loadDocument(chosen.id) : this.emptyReader()]);
  }
  fileOptions() {
    const select = $('document-select'); select.replaceChildren();
    for (const [key, name] of Object.entries(categories)) {
      const docs = state.documents.filter(doc => doc.category === key);
      if (!docs.length) continue;
      const group = node('optgroup'); group.label = name;
      for (const doc of docs) { const option = node('option', '', doc.name); option.value = doc.id; group.append(option); }
      select.append(group);
    }
    if (!state.documents.length) { const option = node('option', '', '尚无资料'); option.value = ''; select.append(option); }
  }
  failures() {
    const failures = state.failedUploads.get(state.course?.id) || [];
    $('failed-uploads').hidden = !failures.length;
    $('failed-count').textContent = `${failures.length} 份资料导入失败，成功资料已保留。`;
    $('failed-detail').textContent = failures.map(item => `${item.file.name}：${item.error}`).join('\n');
  }
  async releaseReader() {
    const reader = state.reader;
    state.reader = null;
    if (reader) {
      if (reader.ready) remember('position-' + reader.document?.id, reader.getVisibleLocation());
      await reader.destroy();
    }
  }
  async loadDocument(id, source) {
    const ticket = ++this.documentVersion;
    const document = state.documents.find(doc => doc.id === id);
    if (!document) return;
    this.selection.clear();
    await this.releaseReader();
    if (ticket !== this.documentVersion) return;
    state.document = document;
    remember('file-' + document.course_id, id);
    $('document-select').value = id;
    $('document-name').textContent = document.name;
    $('document-warning').textContent = document.warning;
    $('document-warning').hidden = !document.warning;
    $('viewer').className = 'textViewer';
    $('viewer').replaceChildren(node('div', 'empty-state', '正在打开资料…'));
    this.controls();
    const reader = createReader(document, $('reader-surface'), $('viewer'), location => {
      if (state.reader === reader) {
        remember('position-' + id, location);
        $('location-status').textContent = `${locationLabel(location)} / ${document.pages} 页`;
        $('context-label').textContent = `${state.course.name} / ${document.name} / ${locationLabel(location)}`;
      }
    });
    state.reader = reader;
    try {
      await reader.load(document, source || preference('position-' + id, {page_start: 1}));
      if (ticket !== this.documentVersion || state.reader !== reader) return;
      reader.ready = true;
      this.controls(); this.zoomLabel();
      await this.conversation.setDocument(id);
    } catch (error) {
      if (ticket !== this.documentVersion || reader.destroyed) return;
      $('viewer').replaceChildren(node('p', 'empty-state', '打开失败：' + error.message));
      notify(error.message, true);
    }
  }
  emptyReader() {
    $('document-name').textContent = '尚无资料';
    $('document-warning').hidden = true;
    $('location-status').textContent = '';
    $('viewer').className = 'textViewer';
    $('viewer').replaceChildren(node('p', 'empty-state', '这门课程还没有资料。通过“文件 → 在此项目中添加资料”继续。'));
    this.controls();
  }
  controls() {
    const ready = Boolean(state.document && state.reader?.ready && !state.reader.destroyed);
    for (const id of ['zoom-in', 'zoom-out', 'fit-width', 'summary', 'delete-document', 'translation-toggle']) $(id).disabled = !ready;
    const canChat = Boolean(state.course && (!state.document || ready));
    $('question').disabled = !canChat;
    $('send').disabled = !canChat || state.chatBusy;
    this.stopButton.hidden = !state.chatBusy;
    $('send').textContent = state.chatBusy ? '处理中…' : '发送';
    if (!ready) $('context-label').textContent = state.course ? '当前课程全部资料' : '先选择课程';
    document.dispatchEvent(new Event('workspacechange'));
  }
  zoom(value) {
    this.selection.clear();
    state.reader?.setZoom(value);
    this.zoomLabel();
  }
  zoomLabel() { $('zoom-label').textContent = state.reader?.zoom === 1 ? '适合宽度' : Math.round((state.reader?.zoom || 1) * 100) + '%'; }
  async goSource(source) {
    if (!source.document_id) return;
    this.selection.clear();
    $('workspace').dataset.mobilePane = 'reader';
    if (state.document?.id === source.document_id) state.reader?.scrollToSource(source);
    else await this.loadDocument(source.document_id, source);
  }
  async send(action, question = '', selection = null) {
    if (!state.course || (state.document && !state.reader?.ready) || state.chatBusy) return;
    if (action === 'ask' && !question.trim()) return notify('请输入问题。', true);
    const courseId = state.course.id;
    const location = selection || (state.document ? {...state.reader.getVisibleLocation(), document_id: state.document.id, selected_text: ''} : {document_id: null, page_start: 1});
    const source = {document_id: location.document_id, page_start: location.page_start, page_end: location.page_end, selected_text: location.selected_text || ''};
    const input = $('question').value;
    this.chatAbort = new AbortController(); const controller = this.chatAbort;
    const article = node('article', 'message assistant');
    const progress = node('div', 'muted', '正在生成…'), body = node('div', 'message-body', '');
    article.append(node('div', 'role', question || (action === 'summary' ? '总结当前页' : '课程问题')), progress, body);
    $('messages').append(article);
    state.chatBusy = true; this.controls(); this.conversation.tab('chat');
    try {
      const result = await runAgent(courseId, {...source, action, question, persist: true, mode: state.agentMode}, {
        signal: controller.signal, onEvent: event => {
          if (state.course?.id !== courseId || controller.signal.aborted) return;
          if (event.type === 'delta') body.textContent += event.data.text;
          if (event.type === 'tool') progress.textContent = '正在调用：' + event.data.name;
          if (event.type === 'start') progress.textContent = event.data.mode === 'demo' ? '演示模式，未连接 AI' : '正在生成…';
          $('messages').scrollTop = $('messages').scrollHeight;
        }
      });
      if (state.course?.id === courseId) {
        await this.conversation.refreshHistory();
        if ($('question').value === input) this.composerInput.setValue('');
      }
    } catch (error) {
      if (error.name === 'AbortError') { progress.textContent = '生成已停止，未保存未完成回复。'; }
      else {
        progress.textContent = error.message; notify(error.message, true);
        const retry = node('button', 'quiet', '重试');
        retry.onclick = () => { article.remove(); this.send(action, question, location); };
        article.append(retry);
      }
    }
    finally { if (this.chatAbort === controller) { state.chatBusy = false; this.controls(); } }
  }
  async deleteDocument() {
    const doc = state.document;
    if (!doc || !confirm(`删除“${doc.name}”？聊天和笔记会保留，来源将标记为“原资料已删除”。`)) return;
    const ticket = this.version;
    try {
      this.selection.clear();
      await this.releaseReader();
      await api(`/api/documents/${doc.id}`, {method: 'DELETE'});
      if (ticket === this.version && state.course?.id === doc.course_id) await this.load(doc.course_id);
      await this.onCoursesChanged();
      notify('资料已删除，聊天与笔记已保留。');
    } catch (error) { notify(error.message, true); if (ticket === this.version && state.course?.id === doc.course_id) await this.loadDocument(doc.id); }
  }
  async leave() {
    this.chatAbort?.abort();
    const ticket = ++this.version; this.documentVersion++;
    this.selection.clear(); this.conversation.clear();
    await this.releaseReader();
    if (ticket !== this.version) return;
    state.course = state.document = null; state.documents = [];
  }
}
