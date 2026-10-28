import {$, node, notify} from '../shared/dom.js';
import {api, post} from './client.js';

const definitions = [
  ['base', '通用系统提示词', '适用于所有功能：回答语言、来源规范和通用规则。'],
  ['ask', '课程问答', '主对话的学习问答与资料检索规则。'],
  ['translate', '翻译', '划词翻译及翻译追问的语言、术语与格式规则。'],
  ['explain', '简短解释', '默认两句话内介绍概念、变量和公式的含义。'],
  ['explain_detail', '详细解释', '解释窗口的详细解释按钮使用：细致讲解、必要步骤和小例子。'],
  ['course_overview', '课程概况', '归纳课程领域和主要内容，为划词消歧提供背景；独立于当前页总结。'],
  ['summary', '总结', '当前页或幻灯片的总结规则。'],
];
let editors = [], loading = false, saving = false;

export async function refreshPromptSettings(discard = false) {
  if (loading || saving) return;
  loading = true;
  $('prompt-refresh').disabled = true;
  try {
    const result = await api('/api/agent/prompts');
    for (const editor of editors) {
      if (editor.dirty && !discard) continue;
      if (!(editor.id in result.prompts)) { editor.loaded = false; editor.state.textContent = '本地配置未启用此功能'; continue; }
      editor.input.value = result.prompts[editor.id];
      editor.saved = editor.input.value;
      editor.version = result.version;
      editor.loaded = true; editor.dirty = false;
      editor.update();
    }
    $('prompt-load-status').textContent = '已加载当前提示词。每项修改后分别保存；保存不会调用模型 API。';
  } catch (error) {
    $('prompt-load-status').textContent = '提示词加载失败，请点击重新载入重试。';
    notify(error.message, true);
  } finally {
    loading = false; $('prompt-refresh').disabled = false;
  }
}

export function installPromptSettings(section) {
  const group = node('section', 'prompt-settings'); group.id = 'prompt-settings';
  const heading = node('h2', '', '提示词管理');
  const description = node('p', '', '修改各功能发送给 AI 的规则。保存到本地提示词文件，新请求立即生效，正在生成的回答使用原版本。学习功能与通用提示词组合；课程概况使用独立提示词，不进入课程聊天。');
  const refresh = node('button', 'quiet', '重新载入提示词'); refresh.type = 'button'; refresh.id = 'prompt-refresh';
  refresh.onclick = () => {
    if (editors.some(e => e.dirty) && !confirm('重新载入将放弃尚未保存的提示词修改。继续？')) return;
    refreshPromptSettings(true);
  };
  const status = node('p', 'prompt-load-status', '正在加载提示词…'); status.id = 'prompt-load-status';
  status.setAttribute('role', 'status');
  group.append(heading, description, refresh, status);
  editors = definitions.map(([id, title, help]) => {
    const form = node('form', 'prompt-editor');
    const label = node('label', 'prompt-label', title); label.htmlFor = 'prompt-' + id;
    const hint = node('p', 'prompt-help', help); hint.id = 'prompt-help-' + id;
    const input = node('textarea'); input.id = 'prompt-' + id;
    input.rows = id === 'base' ? 7 : 5; input.maxLength = 20000; input.spellcheck = false;
    input.setAttribute('aria-describedby', hint.id); input.disabled = true;
    const footer = node('div', 'prompt-editor-footer');
    const state = node('span', 'prompt-save-state', '尚未加载'); state.setAttribute('role', 'status');
    const save = node('button', '', '保存' + title); save.type = 'submit'; save.disabled = true;
    save.id = 'prompt-save-' + id;
    const editor = {id, input, save, state, loaded: false, dirty: false, saved: '', version: ''};
    editor.update = () => {
      input.disabled = !editor.loaded || saving;
      save.disabled = !editor.loaded || !editor.dirty || !input.value.trim() || saving;
      state.textContent = !editor.loaded ? '尚未加载' : editor.dirty ? '有未保存的修改 · ' + input.value.length + ' 字符' : '已保存 · ' + input.value.length + ' 字符';
    };
    input.oninput = () => { editor.dirty = input.value !== editor.saved; editor.update(); };
    form.onsubmit = async event => {
      event.preventDefault();
      if (!editor.loaded || saving || !editor.dirty) return;
      if (!input.value.trim()) { notify('提示词不能为空。', true); return; }
      saving = true; const version = editor.version;
      editors.forEach(e => e.update()); refresh.disabled = true;
      state.textContent = '正在保存…';
      try {
        const result = await post('/api/agent/prompts', {prompt_id: id, content: input.value, expected_version: version});
        editor.saved = input.value; editor.dirty = false;
        // Other local drafts based on the same revision remain editable.
        for (const other of editors.filter(e => e.version === version)) {
          if (!other.dirty) {
            other.input.value = other.saved = result.prompts[other.id];
          }
          if (other.saved === result.prompts[other.id]) other.version = result.version;
        }
        $('agent-status').textContent = '配置版本：' + result.version + '\n提示词已保存，新请求将使用更新内容。';
        notify(title + '已保存，新请求立即生效。');
      } catch (error) { notify(error.message, true); }
      finally { saving = false; refresh.disabled = false; editors.forEach(e => e.update()); }
    };
    footer.append(state, save); form.append(label, hint, input, footer); group.append(form);
    return editor;
  });
  section.append(group);
  refreshPromptSettings();
}
