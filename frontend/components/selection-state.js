// One selected source owns all four tabs. No DOM or transport dependency.
export const selectionActions = ['translate', 'explain', 'ask', 'note'];
export class SelectionSession {
  constructor(source, courseId) {
    this.source = source; this.courseId = courseId; this.action = 'translate';
    this.sessionId = globalThis.crypto?.randomUUID?.() || ('selection-' + Date.now() + '-' + Math.random().toString(16).slice(2));
    this.tabs = Object.fromEntries(selectionActions.map(action => [action, {
      result: null, status: 'idle', error: '', draft: '', expanded: false, question: ''
    }]));
    this.noteReplyAction = null; this.includeReply = true; this.saving = false;
  }
  get current() { return this.tabs[this.action]; }
  switch(action) {
    if (!selectionActions.includes(action)) throw new Error('无效的弹窗状态');
    this.action = action;
  }
  complete(action, result, question = '') {
    Object.assign(this.tabs[action], {result, question, status: 'ready', error: ''});
    this.noteReplyAction = action;
  }
  reply() {
    if (this.action === 'note') return this.includeReply ? this.tabs[this.noteReplyAction]?.result : null;
    return this.current.result;
  }
  notePayload() {
    const result = this.reply(), draft = this.tabs.note.draft.trim();
    const body = [result?.content, draft].filter(Boolean).join('\n\n我的笔记：\n');
    const {rect, ...source} = this.source;
    return {...source, body, demo: Boolean(result && (result.mode === 'demo' || result.content?.startsWith('演示')))};
  }
}
