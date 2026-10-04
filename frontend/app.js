// Composition root: route coordination and wiring, with no reader or transport implementation.
import {$, notify} from './shared/dom.js';
import {api} from './services/client.js';
import {state} from './state/store.js';
import {Workspace} from './pages/workspace.js';
import {renderHomeCourses} from './pages/home.js';
import {Shell} from './components/shell.js';
import {UploadDialog} from './components/uploads.js';

const openCourse = id => { location.hash = '#/courses/' + encodeURIComponent(id); };
let routeVersion = 0;
const workspace = new Workspace(() => refreshCourses());
const uploads = new UploadDialog(async (course, documentId) => {
  if (location.hash === '#/courses/' + course.id) {
    await workspace.load(course.id, documentId);
    shell.updateCommands();
  } else {
    preferredDocument = documentId;
    openCourse(course.id);
  }
}, () => refreshCourses());
const shell = new Shell({
  newCourse: () => uploads.open(),
  addFiles: () => { if (state.course) uploads.open(state.course); },
  fit: () => workspace.zoom(1),
  getSelection: () => state.reader?.getSelectionContext()?.selected_text || workspace.selection.selection?.selected_text || ''
});
let preferredDocument;
$('retry-uploads').onclick = () => {
  if (state.course) uploads.open(state.course, state.failedUploads.get(state.course.id) || []);
};
async function refreshCourses() {
  state.courses = await api('/api/courses');
  shell.renderCourses(openCourse, state.course?.id);
  renderHomeCourses(openCourse);
}
async function route() {
  const ticket = ++routeVersion;
  const hash = location.hash || '#/';
  const match = hash.match(/^#\/courses\/([a-f0-9]{32})$/);
  try {
    if (match) {
      shell.showPage('course');
      const documentId = preferredDocument; preferredDocument = undefined;
      await workspace.load(match[1], documentId);
      if (ticket !== routeVersion) return;
      shell.renderCourses(openCourse, match[1]);
      shell.updateCommands();
    } else {
      await workspace.leave();
      if (ticket !== routeVersion) return;
      shell.showPage(hash === '#/settings' ? 'settings' : 'home');
      shell.renderCourses(openCourse, null);
    }
  } catch (error) {
    if (ticket !== routeVersion) return;
    notify(error.message, true);
    await workspace.leave(); shell.showPage('home');
    if (location.hash !== '#/') location.hash = '#/';
  }
}
window.addEventListener('hashchange', route);
(async () => {
  try {
    const health = await api('/api/health');
    state.uploadLimit = health.upload_limit;
    await refreshCourses();
    await route();
  } catch (error) { notify('无法连接本地服务：' + error.message, true); }
})();
