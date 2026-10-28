// Generic text operations and overview dialog, against the isolated fake-model server.
const {chromium} = require('../.cache/ui-test/node_modules/playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try {
    const context=await browser.newContext({viewport:{width:1450,height:950}});
    const page=await context.newPage(), errors=[], runs=[], overviewRuns=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',req=>{
      if(req.method()==='POST'&&/\/agent\/runs$/.test(req.url()))runs.push(req.postDataJSON());
      if(req.method()==='POST'&&/\/overview\/runs$/.test(req.url()))overviewRuns.push(req.postDataJSON());
    });
    const base='http://127.0.0.1:8002';
    await page.goto(base);
    await page.waitForFunction(()=>document.querySelector('#agent-mode-label').textContent.includes('AI 模式'));
    await page.click('#home-new');
    await page.fill('#course-name','Probability UI '+Date.now());
    await page.setInputFiles('#course-files',[
      {name:'probability.txt',mimeType:'text/plain',buffer:Buffer.from('🙂 Gradient descent. The PDF integrates to one. Continuous probability distributions.')},
      {name:'robotics.txt',mimeType:'text/plain',buffer:Buffer.from('Reinforcement learning policy selects actions.')},
      {name:'unsupported.bin',mimeType:'application/octet-stream',buffer:Buffer.from('not supported')}
    ]);
    await page.click('#upload-submit');
    await page.waitForSelector('#question:not([disabled])');
    await page.waitForFunction(()=>document.querySelector('#course-overview-open').textContent==='课程概况');
    assert.equal(overviewRuns.length,1);assert.equal(overviewRuns[0].initial,true);
    await page.click('#course-overview-open');
    await page.waitForFunction(()=>document.querySelector('#overview-content').value.includes('学习梯度下降'));
    await page.fill('#overview-fields','数学、概率论');
    await page.fill('#overview-content','学习连续随机变量和概率密度函数。');
    await page.fill('#overview-supplement','可选的补充说明');
    await page.click('#overview-save');
    await page.waitForFunction(()=>document.querySelector('#overview-status').textContent.includes('当前为人工编辑版本'));
    console.log('overview manual save complete');
    await page.click('#overview-close');await page.reload();
    await page.waitForSelector('#question:not([disabled])');await page.click('#course-overview-open');
    await page.waitForFunction(()=>document.querySelector('#overview-content').value.includes('连续随机变量'));
    assert.equal(await page.inputValue('#overview-supplement'),'可选的补充说明');
    await page.click('#overview-generate');
    await page.waitForFunction(()=>document.querySelector('#overview-content').value.includes('学习梯度下降'));
    await page.screenshot({path:path.resolve('.cache/course-overview-ui.png')});
    await page.click('#overview-close');
    await page.fill('#question','什么是 gradient descent？');await page.click('#send');
    await page.waitForSelector('.message.assistant [data-text-source="message"]');
    await page.check('#translation-toggle');
    async function select(selector,text,keyboard=false){
      await page.evaluate(({selector,text,keyboard})=>{
        const el=document.querySelector(selector);const node=el.firstChild;
        const start=node.textContent.indexOf(text);if(start<0)throw new Error('selection missing: '+text);
        const range=document.createRange();range.setStart(node,start);range.setEnd(node,start+text.length);
        getSelection().removeAllRanges();getSelection().addRange(range);
        el.dispatchEvent(keyboard?new KeyboardEvent('keyup',{bubbles:true,key:'ArrowRight',shiftKey:true}):new PointerEvent('pointerup',{bubbles:true}));
      },{selector,text,keyboard});
    }
    async function ready(){await page.waitForFunction(()=>!document.querySelector('#selection-popup').hidden&&!document.querySelector('#popup-submit').disabled&&document.querySelector('#popup-answer').textContent.includes('测试模型回答'));}
    await select('.message.assistant .message-body','梯度下降',true);await ready();
    assert.equal(runs.at(-1).source.kind,'message');const messageId=runs.at(-1).source.id;
    const options=await page.locator('#document-select option').evaluateAll(els=>els.map(el=>el.value));
    const current=await page.inputValue('#document-select');
    await page.selectOption('#document-select',options.find(id=>id!==current));
    assert.equal(await page.locator('#selection-popup').isVisible(),true);
    await page.click('#popup-tab-explain');await ready();
    assert.equal(runs.at(-1).source.kind,'message');assert.equal(runs.at(-1).source.id,messageId);
    assert.equal(runs.at(-1).document_id,undefined);
    await page.click('#popup-detail');await ready();assert.equal(runs.at(-1).action,'explain_detail');
    await page.click('#popup-tab-note');await page.click('#popup-input-entry');
    await page.fill('#note-body','🙂 我的学习笔记');await page.click('#popup-save');
    await page.waitForSelector('#selection-popup[hidden]',{state:'attached'});
    await page.click('#tab-notes');await page.waitForSelector('.note [data-text-source="note"]');
    await select('.note .note-body','我的学习笔记');await ready();
    assert.equal(runs.at(-1).source.kind,'note');const noteId=runs.at(-1).source.id;
    await page.click('#popup-tab-ask');await page.click('#popup-input-entry');
    await page.fill('#popup-question','为什么？');await page.click('#popup-submit');await ready();
    await page.click('#popup-save');await page.waitForSelector('#selection-popup[hidden]',{state:'attached'});
    const noteCount=await page.locator('.note').count();assert.ok(noteCount>=2);
    await page.locator('.note').first().locator('.source-button').first().click();
    await page.waitForSelector(`[data-note-id="${noteId}"].source-highlight`);
    await page.screenshot({path:path.resolve('.cache/generic-selection-notes.png')});
    // Unrelated sources cannot be combined into a selection.
    await page.evaluate(()=>{
      const bodies=[...document.querySelectorAll('.note .note-body')];
      const range=document.createRange();range.setStart(bodies[0].firstChild,0);range.setEnd(bodies[1].firstChild,1);
      getSelection().removeAllRanges();getSelection().addRange(range);
      bodies[0].dispatchEvent(new PointerEvent('pointerup',{bubbles:true}));
    });
    await page.waitForTimeout(100);assert.equal(await page.locator('#selection-popup').isVisible(),false);
    // Additional imports mark context stale and do not auto-call the model again.
    await page.locator('.topbar summary').filter({hasText:'文件'}).click();
    await page.locator('[data-command="add"]').click();
    await page.setInputFiles('#course-files',{name:'new.txt',mimeType:'text/plain',buffer:Buffer.from('New material')});
    await page.click('#upload-submit');
    await page.waitForFunction(()=>document.querySelector('#course-overview-open').textContent.includes('建议更新'));
    assert.equal(overviewRuns.length,2); // initial + explicit manual generation
    // Narrow layout: dialog stays inside the viewport and scrolls.
    await page.setViewportSize({width:620,height:700});
    if(await page.locator('#drawer-backdrop').isVisible())await page.click('#drawer-backdrop');
    await page.locator('[data-pane="chat"]').click();await page.click('#course-overview-open');
    const dimensions=await page.locator('#overview-dialog').evaluate(el=>({width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height}));
    assert.ok(dimensions.width<=620&&dimensions.height<=700);
    await page.screenshot({path:path.resolve('.cache/course-overview-mobile.png')});
    assert.deepEqual(errors,[]);
    console.log('PASS: initial batch/partial failure, overview edit/reload/generate/stale, keyboard message selection, frozen source after file switch, note selection/save/navigation, cross-source rejection and narrow layout.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
