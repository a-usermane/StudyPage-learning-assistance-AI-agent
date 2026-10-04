export async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === 'string' ? detail : response.status === 422
      ? '输入格式或字符长度无效，请检查后重试。' : `请求失败（${response.status}）`);
  }
  return data;
}
export const post = (path, data, options = {}) => api(path, {
  ...options, method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
});
export function coursePath(id, resource = '') {
  return `/api/courses/${encodeURIComponent(id)}${resource ? '/' + resource : ''}`;
}

export function parseSSE(frame) {
  const lines = frame.replaceAll('\r', '').split('\n');
  const type = lines.find(line => line.startsWith('event:'))?.slice(6).trim() || 'message';
  const payload = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
  return payload ? {type, data: JSON.parse(payload)} : null;
}

export async function runAgent(courseId, payload, {signal, onEvent = () => {}} = {}) {
  const response = await fetch(coursePath(courseId, 'agent/runs'), {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload), signal
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : '学习请求失败，请检查配置或输入。');
  }
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = '', result = null, runId = null;
  const cancel = () => {
    if (runId) post(coursePath(courseId, 'agent/runs/' + runId + '/cancel'), {}).catch(() => {});
  };
  signal?.addEventListener('abort', cancel, {once: true});
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value, {stream: !done}).replaceAll('\r', '');
      let index;
      while ((index = buffer.indexOf('\n\n')) >= 0) {
        const event = parseSSE(buffer.slice(0, index)); buffer = buffer.slice(index + 2);
        if (!event) continue;
        if (event.type === 'start') runId = event.data.run_id;
        if (event.type === 'error') throw new Error(event.data.detail);
        if (event.type === 'cancelled') throw new DOMException('生成已停止', 'AbortError');
        if (event.type === 'done') result = event.data;
        onEvent(event);
      }
      if (done) break;
    }
    if (!result) throw new Error('连接中断，回复未完成，请重试。');
    return result;
  } finally {
    signal?.removeEventListener('abort', cancel);
    if (!result) { cancel(); await reader.cancel().catch(() => {}); }
    reader.releaseLock();
  }
}
