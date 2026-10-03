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
