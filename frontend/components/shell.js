import {$, node, notify} from '../shared/dom.js';
import {state, remember} from '../state/store.js';
import {installNavigationIcons} from '../shared/icons.js';

export class Shell {
  constructor(commands) {
    this.commands = commands;
    installNavigationIcons();
    $('home-button').onclick = $('settings-home').onclick = () => { location.hash = '#/'; };
    $('settings-button').onclick = () => { location.hash = '#/settings'; };
    $('plugins-button').onclick = () => this.help('插件自定义', '插件功能暂未实现。后续可在这里管理课程学习插件。');
    $('menu-button').onclick = () => this.toggleMenu();
    $('menu-close').onclick = $('drawer-backdrop').onclick = () => this.toggleMenu(false);
    $('menu-new').onclick = $('home-new').onclick = () => commands.newCourse();
    $('existing-courses').onclick = () => { $('home-course-list').hidden = false; this.toggleMenu(true); };
    $('help-close').onclick = () => $('help-dialog').close();
    for (const button of document.querySelectorAll('[data-command]')) button.onclick = async () => {
      for (const menu of document.querySelectorAll('.menu')) menu.open = false;
      try {
        const command = button.dataset.command;
        if (command === 'new') commands.newCourse();
        if (command === 'add') commands.addFiles();
        if (command === 'menu') this.toggleMenu();
        if (command === 'swap') { state.swapped = !state.swapped; remember('swapped', state.swapped); this.layout(); }
        if (command === 'fit') commands.fit();
        if (command === 'clear') { $('question').value = ''; document.dispatchEvent(new Event('composerchange')); }
        if (command === 'copy') {
          const selection = commands.getSelection();
          if (selection) { await navigator.clipboard.writeText(selection); notify('已复制所选文字。'); }
        }
        if (command === 'help') this.help('使用说明', '新建课程并导入资料；按用途切换文件。连续滚动阅读，选中文字后解释、提问或保存笔记。开启“划词翻译”后直接弹出翻译框。每门课程共享聊天记录，点击来源可返回对应页。');
        if (command === 'demo') this.help('演示模式，未连接 AI', '内置词典仅展示已知术语的通用翻译和释义。未知内容不会生成假翻译，提问只展示问题和原文。当前页内容预览不是 AI 总结。资料、笔记和对话保存在本机，无需外部服务。');
      } catch (error) { notify(error.message, true); }
    };
    document.addEventListener('pointerdown', event => {
      for (const menu of document.querySelectorAll('.menu')) if (!menu.contains(event.target)) menu.open = false;
    });
    document.addEventListener('selectionchange', () => this.updateCommands());
    document.addEventListener('workspacechange', () => this.updateCommands());
    document.addEventListener('pointerdown', event => {
      if (event.target.closest('[data-command="copy"]')) event.preventDefault();
    });
    for (const button of document.querySelectorAll('[data-pane]')) button.onclick = () => { $('workspace').dataset.mobilePane = button.dataset.pane; };
    this.setupSplitter();
    this.toggleMenu(state.menuOpen, false);
    this.layout();
  }
  help(title, content) {
    $('help-title').textContent = title;
    $('help-body').replaceChildren(node('p', '', content));
    $('help-dialog').showModal();
  }
  toggleMenu(open = !state.menuOpen, animate = true) {
    const frame = $('content-frame'), slot = $('course-menu-slot');
    clearTimeout(this.menuTimer);
    const ticket = this.menuTicket = (this.menuTicket || 0) + 1;
    const motion = animate && !matchMedia('(prefers-reduced-motion: reduce)').matches;
    const duration = motion ? 230 : 0;
    if (motion) document.dispatchEvent(new CustomEvent('layoutstart', {detail: {duration}}));
    state.menuOpen = open; remember('menu-open', open);
    if (!open && $('course-menu').contains(document.activeElement)) $('menu-button').focus();
    $('course-menu').hidden = false;
    $('course-menu').inert = !open;
    $('course-menu').setAttribute('aria-hidden', String(!open));
    slot.style.transitionDuration = motion ? '' : '0ms';
    if (open) $('drawer-backdrop').hidden = false;
    frame.classList.toggle('menu-collapsed', !open);
    $('menu-button').setAttribute('aria-expanded', String(open));
    $('menu-button').setAttribute('aria-label', open ? '收起课程菜单' : '展开课程菜单');
    $('menu-button').classList.toggle('active', open);
    const finish = () => {
      if (ticket !== this.menuTicket) return;
      $('course-menu').hidden = !open; $('drawer-backdrop').hidden = !open;
      document.dispatchEvent(new Event('layoutend'));
    };
    if (duration) this.menuTimer = setTimeout(finish, duration); else finish();
  }
  showPage(name) {
    for (const page of ['home', 'course', 'settings']) $(`${page}-page`).hidden = page !== name;
    $('home-button').classList.toggle('active', name === 'home');
    $('settings-button').classList.toggle('active', name === 'settings');
    if (innerWidth <= 800) this.toggleMenu(false);
    this.updateCommands();
  }
  renderCourses(openCourse, activeId) {
    const list = $('course-list'); list.replaceChildren();
    if (!state.courses.length) list.append(node('p', 'empty-state', '尚无课程'));
    for (const course of state.courses) {
      const button = node('button', 'course-item' + (course.id === activeId ? ' active' : ''));
      button.append(node('strong', '', course.name), node('small', '', `${course.document_count} 份资料`));
      button.onclick = () => openCourse(course.id);
      list.append(button);
    }
  }
  updateCommands() {
    const inCourse = !$('course-page').hidden && Boolean(state.course);
    for (const button of document.querySelectorAll('[data-command]')) {
      const command = button.dataset.command;
      button.disabled = ['add', 'clear', 'swap', 'fit'].includes(command) && !inCourse
        || command === 'fit' && !state.reader?.ready
        || command === 'copy' && !this.commands.getSelection();
    }
  }
  layout() {
    const workspace = $('workspace');
    workspace.classList.toggle('swapped', state.swapped);
    workspace.style.setProperty('--chat-width', state.split + '%');
    $('splitter').setAttribute('aria-valuenow', String(Math.round(state.split)));
  }
  setupSplitter() {
    const splitter = $('splitter');
    let dragging = false;
    const setSplit = value => { state.split = Math.max(25, Math.min(65, value)); this.layout(); };
    splitter.onpointerdown = event => { dragging = true; splitter.setPointerCapture(event.pointerId); event.preventDefault(); };
    splitter.onpointermove = event => {
      if (!dragging) return;
      const rect = $('workspace').getBoundingClientRect();
      const portion = (event.clientX - rect.left) / rect.width * 100;
      setSplit(state.swapped ? 100 - portion : portion);
    };
    splitter.onpointerup = event => { dragging = false; splitter.releasePointerCapture(event.pointerId); remember('split', state.split); };
    splitter.onlostpointercapture = () => { dragging = false; };
    splitter.onkeydown = event => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const direction = (event.key === 'ArrowRight' ? 1 : -1) * (state.swapped ? -1 : 1);
      setSplit(state.split + direction * 2); remember('split', state.split);
    };
  }
}
