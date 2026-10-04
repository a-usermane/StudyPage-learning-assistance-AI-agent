import {$, positionFloating} from '../shared/dom.js';
import {FoldedInput} from './input.js';
const titles = {translate: '翻译', explain: '解释', ask: '提问', note: '笔记'};
const prompts = {translate: '对这段翻译提问…', explain: '继续询问这段内容…', ask: '输入你的问题…', note: '补充自己的理解…'};
export class SelectionPopup {
  constructor(handlers) {
    this.handlers = handlers;
    this.input = new FoldedInput({entry: $('popup-input-entry'), editor: $('popup-editor'),
      question: $('popup-question'), note: $('note-body'), collapse: $('popup-collapse'),
      onExpand: () => handlers.expand(), onCollapse: () => handlers.collapse()});
    const tabs = [...document.querySelectorAll('[data-popup-action]')];
    for (const [index, button] of tabs.entries()) {
      button.onclick = () => handlers.switch(button.dataset.popupAction);
      button.onkeydown = event => {
        const delta = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
        if (!delta && !['Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + delta + tabs.length) % tabs.length;
        tabs[next].focus(); handlers.switch(tabs[next].dataset.popupAction);
      };
    }
    $('popup-question').oninput = event => handlers.draft(event.target.value);
    $('note-body').oninput = event => handlers.draft(event.target.value);
    $('popup-form').onsubmit = event => { event.preventDefault(); handlers.submit(); };
    for (const id of ['popup-question', 'note-body']) $(id).onkeydown = event => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); handlers.submit(); }
    };
    $('popup-include-reply').onchange = event => handlers.includeReply(event.target.checked);
    $('popup-retry').onclick = () => handlers.retry();
    $('popup-close').onclick = () => handlers.close();
    $('popup-copy').onclick = () => handlers.copy();
    $('popup-save').onclick = () => handlers.save();
    $('popup-transfer').onclick = () => handlers.transfer();
    $('popup-original').ontoggle = () => this.reposition();
    this.resize = new ResizeObserver(() => this.reposition());
    this.resize.observe($('selection-popup'));
  }
  hide() { this.switchAnimation?.cancel(); $('selection-popup').hidden = true; this.session = null; this.previousAction = null; $('popup-original').open = false; }
  reposition() {
    if (this.session && !$('selection-popup').hidden) positionFloating($('selection-popup'), this.session.source.rect);
  }
  render(session) {
    const changedAction = this.session === session && this.previousAction && this.previousAction !== session.action;
    this.session = session;
    const {action, current, source} = session;
    const isNote = action === 'note', result = session.reply();
    const busy = current.status === 'loading' || session.saving;
    document.querySelector('.popup-tabs').style.setProperty('--active-tab', String(['translate', 'explain', 'ask', 'note'].indexOf(action)));
    for (const button of document.querySelectorAll('[data-popup-action]')) {
      const active = button.dataset.popupAction === action;
      button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1;
      button.classList.toggle('active', active); button.disabled = session.saving;
    }
    $('popup-title').textContent = titles[action];
    $('popup-panel').setAttribute('aria-labelledby', 'popup-tab-' + action);
    $('popup-quote').textContent = source.selected_text;
    $('popup-quote-summary').textContent = '原文 · ' + source.selected_text.replace(/\s+/g, ' ').slice(0, 44);
    const displayContent = content => content?.replace(/^演示模式，未连接 AI\s*/, '') || '';
    $('popup-answer').textContent = current.status === 'loading' ? '正在读取本地演示内容…'
      : current.error || (isNote ? [displayContent(result?.content), session.tabs.note.draft].filter(Boolean).join('\n\n我的笔记：\n')
        || '将所选原文保存下来，也可以补充自己的理解。'
      : displayContent(current.result?.content) || '点击下方输入框，提出关于这段内容的问题。');
    $('popup-answer').classList.toggle('is-hint', !result && !current.error);
    $('popup-answer').setAttribute('aria-busy', String(current.status === 'loading'));
    $('popup-demo').hidden = !result && current.status !== 'loading';
    $('popup-retry').hidden = current.status !== 'error';
    $('popup-source').replaceChildren(this.handlers.sourceButton(result?.citation || {...source, name: this.handlers.fileName()}));
    $('popup-attach').hidden = !isNote || !session.noteReplyAction;
    $('popup-include-reply').checked = session.includeReply;
    $('popup-attach-label').textContent = '附带已有' + (titles[session.noteReplyAction] || '') + '回复（演示内容）';
    $('popup-question-snapshot').hidden = action !== 'ask' || !current.result;
    $('popup-question-snapshot').textContent = '问题：' + current.question;
    this.input.render({expanded: current.expanded, isNote, value: current.draft, placeholder: prompts[action], busy});
    $('popup-include-reply').disabled = session.saving;
    $('popup-submit').textContent = isNote ? '保存笔记' : '查看演示回复';
    $('popup-submit').disabled = busy;
    $('popup-save').disabled = busy; $('popup-save').textContent = session.saving ? '保存中…' : '保存笔记';
    $('popup-transfer').hidden = isNote; $('popup-transfer').disabled = !current.result || busy;
    $('popup-copy').disabled = !(result?.content || isNote && session.tabs.note.draft.trim()) || busy;
    positionFloating($('selection-popup'), source.rect);
    if (current.expanded) (isNote ? this.input.growNote : this.input.growQuestion).resize();
    if (changedAction) {
      this.switchAnimation?.cancel();
      if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
        this.switchAnimation = $('popup-result-content').animate([
          {opacity: .4, transform: 'translateY(4px)'}, {opacity: 1, transform: 'translateY(0)'}
        ], {duration: 160, easing: 'ease-out'});
      }
    }
    this.previousAction = action;
  }
}
