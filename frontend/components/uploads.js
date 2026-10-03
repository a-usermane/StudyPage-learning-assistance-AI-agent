import {$, node, notify, categories} from '../shared/dom.js';
import {api, post, coursePath} from '../services/client.js';
import {state} from '../state/store.js';

const textFormats = new Set(['txt', 'md', 'pdf']);
export class UploadDialog {
  constructor(onCompleted, onCoursesChanged) {
    this.onCompleted = onCompleted;
    this.onCoursesChanged = onCoursesChanged;
    this.queue = [];
    $('course-files').onchange = () => { this.addFiles([...$('course-files').files]); $('course-files').value = ''; };
    $('upload-form').onsubmit = event => { event.preventDefault(); this.submit(); };
    $('upload-close').onclick = () => this.cancel();
    $('upload-dialog').addEventListener('cancel', event => { event.preventDefault(); this.cancel(); });
    $('sample-toggle').onclick = () => this.showSamples();
  }
  open(course = null, failures = []) {
    this.course = course;
    this.creating = !course;
    this.queue = failures.map(item => ({...item, status: '失败'}));
    $('upload-title').textContent = this.creating ? '新建课程' : '添加课程资料';
    $('course-name').value = course?.name || '';
    $('course-name').disabled = Boolean(course);
    $('course-name-row').hidden = !this.creating;
    $('upload-status').textContent = '至少一份资料成功后进入课程。单文件上限 ' + Math.round(state.uploadLimit / 1024 / 1024) + ' MB。';
    $('sample-list').hidden = true;
    this.render();
    $('upload-dialog').showModal();
    if (this.creating) $('course-name').focus();
  }
  addFiles(files) {
    for (const file of files) {
      const extension = file.name.split('.').pop().toLowerCase();
      const category = extension === 'pptx' ? 'slides' : textFormats.has(extension) ? 'other' : 'code';
      this.queue.push({file, category, status: '等待上传', error: ''});
    }
    this.render();
  }
  render() {
    const list = $('upload-queue'); list.replaceChildren();
    for (const item of this.queue) {
      const row = node('div', 'upload-row');
      const detail = node('div', 'upload-detail');
      detail.append(node('span', 'upload-filename', item.file.name),
        node('small', item.error ? 'error-text' : 'muted', item.error || item.status));
      const select = node('select');
      select.setAttribute('aria-label', item.file.name + ' 的用途');
      for (const [key, name] of Object.entries(categories)) { const option = node('option', '', name); option.value = key; select.append(option); }
      select.value = item.category;
      select.disabled = state.uploadBusy || item.status === '成功';
      select.onchange = () => { item.category = select.value; };
      const remove = node('button', 'quiet', '×');
      remove.type = 'button'; remove.setAttribute('aria-label', '移除 ' + item.file.name);
      remove.disabled = state.uploadBusy || item.status === '成功';
      remove.onclick = () => { this.queue = this.queue.filter(entry => entry !== item); this.render(); };
      row.append(detail, select, remove); list.append(row);
    }
    const pending = this.queue.some(item => item.status !== '成功');
    $('upload-submit').disabled = state.uploadBusy || !pending;
    $('upload-submit').textContent = state.uploadBusy ? '正在导入…' : '导入并进入课程';
    $('course-files').disabled = $('upload-close').disabled = $('sample-toggle').disabled = state.uploadBusy;
  }
  async submit() {
    if (state.uploadBusy || !this.queue.length) return;
    const name = $('course-name').value.trim();
    if (this.creating && (!name || name.length > 100)) return notify('课程名称不能为空，且最多 100 个字符。', true);
    state.uploadBusy = true;
    this.render();
    let lastDocument = null;
    try {
      if (!this.course) this.course = await post('/api/courses', {name});
      $('course-name').disabled = true;
      for (const item of this.queue) {
        if (item.status === '成功') continue;
        item.status = '处理中'; item.error = ''; this.render();
        try {
          if (item.file.size > state.uploadLimit) throw new Error('文件超过单文件大小上限。');
          const body = new FormData(); body.append('file', item.file, item.file.name); body.append('category', item.category);
          lastDocument = await api(coursePath(this.course.id, 'documents'), {method: 'POST', body});
          item.status = '成功'; this.course.status = 'ready';
        } catch (error) { item.status = '失败'; item.error = error.message; }
        this.render();
      }
      const failures = this.queue.filter(item => item.status === '失败');
      if (lastDocument || this.queue.some(item => item.status === '成功')) {
        state.failedUploads.set(this.course.id, failures);
        $('upload-dialog').close();
        await this.onCoursesChanged();
        await this.onCompleted(this.course, lastDocument?.id, failures);
      } else {
        if (!this.creating) state.failedUploads.set(this.course.id, failures);
        $('upload-status').textContent = '未成功导入资料。请检查失败项并重试，或取消创建。';
      }
    } catch (error) { notify(error.message, true); }
    finally { state.uploadBusy = false; this.render(); }
  }
  async cancel() {
    if (state.uploadBusy) return;
    try {
      if (this.creating && this.course?.status === 'pending') await api(coursePath(this.course.id, 'pending'), {method: 'DELETE'});
      if (!this.creating && this.course) {
        state.failedUploads.set(this.course.id, this.queue.filter(item => item.status === '失败'));
        await this.onCompleted(this.course);
      }
      $('upload-dialog').close(); this.course = null; this.queue = [];
    } catch (error) { notify(error.message, true); }
  }
  async showSamples() {
    const list = $('sample-list');
    if (!list.hidden) { list.hidden = true; return; }
    try {
      const samples = await api('/api/samples'); list.replaceChildren();
      for (const sample of samples) {
        const button = node('button', 'sample-item', '+ ' + sample.name); button.type = 'button';
        button.onclick = async () => {
          button.disabled = true;
          try {
            const response = await fetch(sample.url); if (!response.ok) throw new Error('样例读取失败。');
            this.addFiles([new File([await response.blob()], sample.name)]);
          } catch (error) { notify(error.message, true); }
          finally { button.disabled = false; }
        };
        list.append(button);
      }
      list.hidden = false;
    } catch (error) { notify(error.message, true); }
  }
}
