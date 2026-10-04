import {test} from 'node:test';
import assert from 'node:assert/strict';
import {runAgent, parseSSE} from '../frontend/services/client.js';
import {SelectionSession} from '../frontend/components/selection-state.js';

test('SSE frames and split UTF-8 chunks yield final answer and source', async () => {
  assert.equal(parseSSE('event: delta\ndata: {"text":"你好"}').data.text,'你好');
  const old = globalThis.fetch, events = [];
  const encoded = new TextEncoder().encode('event: start\ndata: {"run_id":"r","mode":"live"}\n\nevent: delta\ndata: {"text":"你好"}\n\nevent: done\ndata: {"content":"你好","mode":"live","citations":[]}\n\n');
  globalThis.fetch = async () => new Response(new ReadableStream({start(controller) {
    for (let i=0;i<encoded.length;i+=7) controller.enqueue(encoded.slice(i,i+7)); controller.close();
  }}));
  try {
    const result = await runAgent('course',{question:'x'},{onEvent:e=>events.push(e)});
    assert.equal(result.content,'你好'); assert.equal(events.length,3);
  } finally { globalThis.fetch=old; }
});

test('stream failures do not become a successful demo reply', async () => {
  const old = globalThis.fetch;
  globalThis.fetch = async path => path.endsWith('/cancel') ? new Response('{}') : new Response('event: start\ndata: {"run_id":"r"}\n\nevent: error\ndata: {"detail":"连接失败"}\n\n');
  try { await assert.rejects(runAgent('course',{}),/连接失败/); }
  finally { globalThis.fetch=old; }
});

test('real popup answers save notes without a demo flag', () => {
  const session = new SelectionSession({document_id:'file',page_start:1,page_end:1,selected_text:'text'},'course');
  session.complete('translate',{content:'真实翻译',mode:'live'});
  session.switch('note');
  assert.equal(session.notePayload().demo,false);
  assert.equal(session.notePayload().body,'真实翻译');
});
