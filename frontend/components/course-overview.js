import {$, notify} from '../shared/dom.js';
import {api, post, coursePath} from '../services/client.js';
import {state} from '../state/store.js';
const active = run => ['queued', 'running'].includes(run?.status);
const statusNames = {queued: '等待生成', running: '正在生成', complete: '已完成', pending: '待生成', failed: '生成失败', cancelled: '已停止', interrupted: '已中断'};
export class CourseOverview {
  constructor() {
    document.addEventListener('overviewchange', event => { if (event.detail === this.courseId) this.refresh(!this.dirty); });
    this.courseId = null; this.ticket = 0; this.dirty = false; this.busy = false;
    $('course-overview-open').onclick = () => this.open();
    $('overview-close').onclick = () => $('overview-dialog').close();
    $('overview-form').onsubmit = event => { event.preventDefault(); this.save(); };
    $('overview-generate').onclick = () => this.generate();
    $('overview-stop').onclick = () => this.stop();
    $('overview-reload').onclick = () => this.reload();
    for (const id of ['overview-name', 'overview-fields', 'overview-content', 'overview-supplement']) $(id).oninput = () => { this.dirty = true; this.editTicket = (this.editTicket || 0) + 1; this.controls(); };
  }
  async load(courseId) {
    this.clear(); this.courseId = courseId; $('course-overview-open').disabled = false;
    return this.refresh(true);
  }
  clear() {
    clearTimeout(this.timer); this.ticket++;
    this.courseId = null; this.value = null; this.dirty = false; this.editTicket = 0;
    $('course-overview-open').textContent = '课程概况 · 加载中'; $('course-overview-open').disabled = true;
    for (const id of ['overview-name', 'overview-fields', 'overview-content', 'overview-supplement']) $(id).value = '';
    $('overview-dialog').close(); this.controls();
  }
  async refresh(replace = false) {
    const id = this.courseId, ticket = ++this.ticket, editTicket = this.editTicket;
    if (!id) return;
    try {
      const value = await api(coursePath(id, 'overview'));
      if (this.courseId !== id || ticket !== this.ticket) return;
      this.value = value;
      if (editTicket === this.editTicket && (replace || !this.dirty && this.editVersion !== value.version)) this.fill();
      this.render();
      clearTimeout(this.timer);
      if (active(value.run)) this.timer = setTimeout(() => this.refresh(!this.dirty), 900);
    } catch (error) {
      if (ticket !== this.ticket) return;
      $('course-overview-open').textContent = '课程概况 · 重试';
      $('overview-status').textContent = error.message;
      // Retry only an active task; errors don't block the course workspace.
      if (active(this.value?.run)) this.timer = setTimeout(() => this.refresh(false), 2500);
    }
  }
  fill() {
    const value = this.value;
    if (!value) return;
    $('overview-name').value = value.course_name;
    $('overview-fields').value = value.fields.join('、');
    $('overview-content').value = value.main_content;
    $('overview-supplement').value = value.supplement;
    this.editVersion = value.version;
    this.dirty = false;
  }
  render() {
    const value = this.value;
    const suffix = active(value.run) ? '生成中' : value.stale ? '建议更新' : value.main_content ? '' : '待生成';
    $('course-overview-open').textContent = '课程概况' + (suffix ? ' · ' + suffix : '');
    const run = value.run;
    $('overview-status').textContent = [run ? `${statusNames[run.status] || run.status}：${run.detail}` : '尚未生成，可编辑或使用模型生成。',
      value.stale ? '资料已变化，建议更新；现有概况继续作为弱背景。' : '',
      value.origin === 'manual' ? '当前为人工编辑版本。' : '',
      value.updated_at ? '上次保存：' + new Date(value.updated_at).toLocaleString() : ''].filter(Boolean).join('\n');
    const coverage = run?.coverage?.total_pages !== undefined ? run.coverage : value.coverage;
    $('overview-coverage').textContent = coverage?.total_pages !== undefined
      ? `资料覆盖：${coverage.read_pages} / ${coverage.total_pages} 页有正文；${coverage.unread_pages?.length || 0} 页未能读取。` + (coverage.user_only ? '依据仅来自用户说明。' : '') : '';
    if (active(run)) $('overview-status').textContent += '\n模型调用：' + (run.calls || 0) + ' 次';
    this.controls();
  }
  controls() {
    for (const id of ['overview-name', 'overview-fields', 'overview-content', 'overview-supplement']) $(id).disabled = this.busy || !this.value;
    const count = [...$('overview-name').value, ...$('overview-content').value, ...this.fields().join('')].length;
    $('overview-counter').textContent = count + ' / 600 字符';
    $('overview-counter').classList.toggle('error-text', count > 600);
    for (const id of ['overview-save', 'overview-generate', 'overview-reload']) $(id).disabled = this.busy || !this.value;
    $('overview-save').disabled ||= !this.dirty || count > 600;
    $('overview-save').textContent = this.busy && this.dirty ? '正在保存…' : '保存修改';
    $('overview-generate').disabled ||= active(this.value?.run);
    $('overview-stop').hidden = !active(this.value?.run);
    $('overview-stop').disabled = this.busy;
  }
  fields() { return $('overview-fields').value.split(/[,，、;；\n]+/).map(s => s.trim()).filter(Boolean); }
  async open() {
    if (!this.courseId) return;
    $('overview-dialog').showModal();
    // Keep unsaved edits if the dialog is reopened.
    await this.refresh(!this.dirty);
  }
  async reload() {
    if (this.dirty && !confirm('重新载入会放弃未保存的概况修改，继续？')) return;
    await this.refresh(true);
  }
  async save() {
    if (!this.value || !this.dirty || this.busy) return !this.dirty;
    const id = this.courseId;
    this.busy = true; this.controls();
    try {
      const value = await api(coursePath(id, 'overview'), {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        course_name: $('overview-name').value.trim(), fields: this.fields(), main_content: $('overview-content').value.trim(),
        supplement: $('overview-supplement').value.trim(), expected_version: this.editVersion
      })});
      if (id !== this.courseId) return false;
      this.value = value; this.fill(); this.render(); notify('课程概况已保存。');
      return true;
    } catch (error) { notify(error.message, true); return false; }
    finally { this.busy = false; this.controls(); }
  }
  async generate() {
    // Persist supplement and manual edits first; failures/conflicts retain the editor contents.
    if (this.dirty && !await this.save()) return;
    const id = this.courseId;
    this.busy = true; this.controls();
    try {
      await post(coursePath(id, 'overview/runs'), {mode: state.agentMode});
      if (id === this.courseId) await this.refresh(false);
    } catch (error) { notify(error.message, true); }
    finally { this.busy = false; this.controls(); }
  }
  async stop() {
    const run = this.value?.run;
    if (!run?.run_id) return;
    try { await post(coursePath(this.courseId, `overview/runs/${run.run_id}/cancel`), {}); await this.refresh(false); }
    catch (error) { notify(error.message, true); }
  }
}
