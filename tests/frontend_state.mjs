import assert from 'node:assert/strict';
import {test} from 'node:test';
import {SelectionSession} from '../frontend/components/selection-state.js';
import {Shell} from '../frontend/components/shell.js';
import {AutoGrowInput} from '../frontend/components/input.js';
import {SelectionTools} from '../frontend/components/selection.js';

const source = {document_id: 'doc', page_start: 1, page_end: 2, selected_text: 'Gradient descent', rect: {left: 10}};
test('four tabs retain separate drafts, expansion and cached replies', () => {
  const session = new SelectionSession(source, 'course');
  const reply = {content: '演示翻译', citation: source};
  session.complete('translate', reply);
  session.current.draft = '翻译问题'; session.current.expanded = true;
  session.switch('ask'); session.current.draft = '尚未提交的问题';
  session.switch('note'); session.current.draft = '自己的理解';
  session.switch('translate');
  assert.equal(session.current.result, reply);
  assert.equal(session.current.draft, '翻译问题'); assert.equal(session.current.expanded, true);
  session.switch('ask'); assert.equal(session.current.draft, '尚未提交的问题');
  session.switch('note'); assert.equal(session.current.draft, '自己的理解');
});
test('note attachment and demo flag reflect the actual saved content', () => {
  const session = new SelectionSession(source, 'course');
  session.complete('translate', {content: '演示翻译'}); session.switch('note');
  session.current.draft = '自己的理解';
  assert.equal(session.notePayload().body, '演示翻译\n\n我的笔记：\n自己的理解');
  assert.equal(session.notePayload().demo, true);
  session.includeReply = false;
  assert.equal(session.notePayload().body, '自己的理解'); assert.equal(session.notePayload().demo, false);
  assert.equal(session.notePayload().page_end, 2); assert.equal('rect' in session.notePayload(), false);
});
test('new selection starts fresh and invalid states cannot be selected', () => {
  const first = new SelectionSession(source, 'course'); first.tabs.note.draft = 'old';
  const second = new SelectionSession({...source, selected_text: 'new'}, 'course');
  assert.equal(second.tabs.note.draft, ''); assert.equal(second.noteReplyAction, null);
  assert.throws(() => second.switch('invalid'));
});
test('autosize caps long text and resets after clearing', () => {
  const element = {offsetParent: {}, style: {}, scrollHeight: 500, addEventListener() {}};
  const input = new AutoGrowInput(element, {min: 44, max: 180});
  assert.equal(element.style.height, '180px'); assert.equal(element.style.overflowY, 'auto');
  element.scrollHeight = 20; input.setValue('');
  assert.equal(element.style.height, '44px'); assert.equal(element.style.overflowY, 'hidden');
});
test('rapid drawer reversals finish in the latest state and restore focus', async () => {
  const elements = new Map(); const events = [];
  for (const id of ['content-frame','course-menu-slot','course-menu','drawer-backdrop','menu-button']) {
    elements.set(id, {style: {}, attributes: {}, classes: new Set(), focus() { globalThis.document.activeElement = this; },
      setAttribute(key,value) { this.attributes[key]=value; }, contains(element) { return element?.inMenu; },
      classList: {toggle(name,value) { elements.get(id).classes[value?'add':'delete'](name); }}});
  }
  globalThis.document = {getElementById: id => elements.get(id), activeElement: {inMenu:true}, dispatchEvent: event => events.push(event.type)};
  globalThis.matchMedia = () => ({matches:false});
  globalThis.CustomEvent = class extends Event {};
  const shell = {};
  Shell.prototype.toggleMenu.call(shell, false);
  assert.equal(elements.get('course-menu').inert,true);
  assert.equal(document.activeElement,elements.get('menu-button'));
  Shell.prototype.toggleMenu.call(shell, true);
  await new Promise(resolve => setTimeout(resolve,270));
  assert.equal(elements.get('course-menu').hidden,false); assert.equal(elements.get('course-menu').inert,false);
  assert.equal(elements.get('menu-button').attributes['aria-expanded'],'true');
  assert.equal(elements.get('content-frame').classes.has('menu-collapsed'),false);
  Shell.prototype.toggleMenu.call(shell,false,false);
  assert.equal(elements.get('course-menu').hidden,true); assert.equal(elements.get('drawer-backdrop').hidden,true);
  assert.ok(events.includes('layoutend'));
});
test('late replies cannot overwrite a changed tab or a new selection', async () => {
  const originalFetch = globalThis.fetch;
  const pending = [];
  globalThis.fetch = () => new Promise(resolve => pending.push(resolve));
  const toolbar = {};
  globalThis.document = {getElementById: () => toolbar};
  const tools = Object.create(SelectionTools.prototype);
  tools.view = {hide() {}}; tools.render = () => {};
  tools.popup = new SelectionSession(source, 'course');
  const first = tools.request();
  tools.open('ask');
  pending.shift()({ok: true, json: async () => ({content: 'late translation'})});
  await first;
  assert.equal(tools.popup.action, 'ask'); assert.equal(tools.popup.tabs.translate.result, null);
  tools.open('translate');
  tools.clear(); tools.popup = new SelectionSession({...source, selected_text: 'new'}, 'course');
  pending.shift()({ok: true, json: async () => ({content: 'old selection'})});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(tools.popup.current.result, null); assert.equal(tools.popup.source.selected_text, 'new');
  globalThis.fetch = originalFetch;
});
