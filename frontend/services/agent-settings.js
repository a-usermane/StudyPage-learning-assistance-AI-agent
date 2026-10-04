import {$, node, notify} from '../shared/dom.js';
import {api, post} from './client.js';
import {state, remember} from '../state/store.js';

export async function refreshAgentStatus() {
  state.agentStatus = await api('/api/agent/status');
  const effectiveMode = state.agentMode || state.agentStatus.mode;
  $('agent-mode-label').textContent = effectiveMode === 'demo' ? '演示模式，未连接 AI' : 'AI 模式 · 内容按需发送至 API';
  $('agent-mode-select').value = state.agentMode || '';
  const models = $('agent-key-model');
  const chosen = models.value;
  models.replaceChildren();
  for (const [id, model] of Object.entries(state.agentStatus.models)) {
    const option = node('option', '', id + ' / ' + model.model);
    option.value = id; models.append(option);
  }
  if (state.agentStatus.models[chosen]) models.value = chosen;
  models.dispatchEvent(new Event('change'));
  $('agent-status').textContent = '配置版本：' + state.agentStatus.version + '\n' +
    Object.entries(state.agentStatus.models).map(([id, m]) => id + ' / ' + m.model + ' / ' + (m.configured ? '已配置密钥' : '未配置密钥')).join('\n') + '\n' +
    state.agentStatus.plugins.map(p => p.id + '：' + (p.enabled ? '已启用' : p.error || '已停用')).join('\n');
  return state.agentStatus;
}

export function installAgentSettings() {
  const section = $('settings-page');
  section.querySelector('p').textContent = '在此保存 AI API Key；接口地址和模型名称在 config/models.yaml 中修改。提示词和流程可在项目内自定义。';
  const form = node('form', 'agent-key-form');
  const title = node('h2', '', 'AI API Key');
  const modelLabel = node('label', 'field', '模型配置');
  const models = node('select'); models.id = 'agent-key-model'; modelLabel.append(models);
  const keyLabel = node('label', 'field', 'API Key');
  const key = node('input'); key.id = 'agent-api-key'; key.type = 'password';
  key.autocomplete = 'off'; key.spellcheck = false; key.maxLength = 4096;
  key.placeholder = '输入密钥，保存后不回显'; keyLabel.append(key);
  const hint = node('p', 'agent-key-hint'); hint.id = 'agent-key-hint';
  const save = node('button', '', '保存密钥'); save.type = 'submit';
  const description = node('small', '', '保存到本机项目 .env.local，新请求立即生效。密钥不存入浏览器，保存不会调用模型 API。');
  models.onchange = () => {
    const model = state.agentStatus?.models[models.value];
    hint.textContent = model?.key_source === 'environment' ? '当前使用系统环境变量密钥，需先移除该环境变量才能在此保存。' : model?.configured ? '已配置密钥。输入新密钥可替换现有密钥。' : '尚未配置密钥。';
    save.disabled = !model || model.key_source === 'environment';
  };
  form.onsubmit = async event => {
    event.preventDefault();
    if (!key.value.trim()) { notify('请先输入 API Key。', true); key.focus(); return; }
    save.disabled = true;
    try {
      await post('/api/agent/credentials', {model_id: models.value, api_key: key.value});
      key.value = '';
      await refreshAgentStatus();
      notify('密钥已保存。使用模型前请选择真实 AI，并确认接口地址和模型名称。');
    } catch (error) { notify(error.message, true); }
    finally { models.dispatchEvent(new Event('change')); }
  };
  form.append(title, modelLabel, keyLabel, hint, save, description);
  section.insertBefore(form, $('settings-home'));
  const label = node('label', '', '运行模式 '), select = node('select'); select.id = 'agent-mode-select';
  for (const [value, text] of [['', '跟随本地配置'], ['demo', '演示模式'], ['live', '真实 AI']]) {
    const option = node('option', '', text); option.value = value; select.append(option);
  }
  select.onchange = () => { state.agentMode = select.value || null; remember('agent-mode', state.agentMode); refreshAgentStatus().catch(error => notify(error.message, true)); };
  label.append(select);
  const reload = node('button', 'quiet', '重载本地配置');
  reload.onclick = async () => {
    reload.disabled = true;
    try { await post('/api/agent/config/reload', {}); await refreshAgentStatus(); notify('配置已重载，新请求将使用新配置。'); }
    catch (error) { notify(error.message, true); }
    finally { reload.disabled = false; }
  };
  const diagnose = node('button', 'quiet', '测试模型连接（调用 API）');
  diagnose.onclick = async () => {
    if (!confirm('将调用配置的模型 API 测试普通回答、工具调用和流式输出，可能产生少量费用。继续？')) return;
    diagnose.disabled = true;
    try { const result = await post('/api/agent/diagnose', {}); $('agent-status').textContent = JSON.stringify(result, null, 2); }
    catch (error) { notify(error.message, true); }
    finally { diagnose.disabled = false; }
  };
  const status = node('pre', 'agent-status'); status.id = 'agent-status';
  section.insertBefore(label, $('settings-home')); section.insertBefore(reload, $('settings-home'));
  section.insertBefore(diagnose, $('settings-home')); section.append(status);
}
