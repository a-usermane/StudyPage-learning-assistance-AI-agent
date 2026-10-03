import {$, node} from '../shared/dom.js';
import {state} from '../state/store.js';

export function renderHomeCourses(openCourse) {
  const container = $('home-course-list');
  container.replaceChildren();
  if (!state.courses.length) container.append(node('p', 'empty-state', '还没有课程，点击“新建课程”开始。'));
  for (const course of state.courses) {
    const button = node('button');
    button.append(node('span', '', course.name), node('small', '', `${course.document_count} 份资料`));
    button.onclick = () => openCourse(course.id);
    container.append(button);
  }
}
