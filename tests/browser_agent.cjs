// Uses the installed Edge and .cache/ui-test/playwright; test server is isolated.
const {chromium} = require('../.cache/ui-test/node_modules/playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try {
    const context = await browser.newContext({viewport:{width:1360,height:850}});
    const page = await context.newPage(), errors=[], runs=[];
    page.on('request',request=>{
      if(request.method()==='POST' && /\/agent\/runs$/.test(request.url())) runs.push(request.postDataJSON());
    });
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto('http://127.0.0.1:8002/');
    await page.waitForSelector('#agent-mode-label');
    await page.waitForFunction(()=>document.querySelector('#agent-mode-label').textContent.includes('AI 模式'));
    const courses = await (await page.request.get('http://127.0.0.1:8002/api/courses')).json();
    await page.goto('http://127.0.0.1:8002/#/courses/'+courses[0].id);
    await page.waitForSelector('#question:not([disabled])');
    await page.fill('#question','什么是 gradient descent？');
    await page.click('#send');
    await page.waitForFunction(()=>[...document.querySelectorAll('.message.assistant')].some(m=>m.textContent.includes('梯度下降')&&m.querySelector('.source-button')),null,{timeout:30000});
    assert.equal(await page.locator('.message.assistant .demo-badge').count(),0);
    const citations=await page.locator('.message.assistant .source-button').count();
    assert.ok(citations>0);
    await page.click('#translation-toggle');
    await page.evaluate(()=>{
      const walker=document.createTreeWalker(document.querySelector('#viewer'),NodeFilter.SHOW_TEXT);
      let text; while(text=walker.nextNode()) if(text.textContent.includes('Gradient descent')) {
        const range=document.createRange(); range.setStart(text,0);range.setEnd(text,Math.min(text.length,16));
        getSelection().removeAllRanges();getSelection().addRange(range);
        text.parentElement.dispatchEvent(new PointerEvent('pointerup',{bubbles:true})); break;
      }
    });
    await page.waitForSelector('#selection-popup:not([hidden])');
    await page.waitForFunction(()=>document.querySelector('#popup-answer').textContent.includes('测试模型回答'));
    await page.click('#popup-input-entry');
    await page.fill('#popup-question','保留英文术语');
    await page.click('#popup-submit');
    await page.waitForFunction(()=>document.querySelector('#popup-submit').disabled===false);
    assert.equal(await page.locator('#popup-tab-translate').getAttribute('aria-selected'),'true');
    assert.equal(await page.locator('#popup-detail').isVisible(),false);
    await page.click('#popup-tab-explain');
    await page.waitForFunction(()=>!document.querySelector('#popup-submit').disabled && document.querySelector('#popup-answer').textContent.includes('测试模型回答'));
    assert.equal(runs.at(-1).action,'explain');
    assert.equal(await page.locator('#popup-detail').textContent(),'详细解释');
    // A failed detailed request must retry the detailed profile, not the brief one.
    await page.route('**/agent/runs',async route=>{
      if(route.request().postDataJSON().action==='explain_detail'){
        await route.fulfill({contentType:'text/event-stream',body:'event: error\ndata: {"detail":"详细解释测试失败"}\n\n'});
        await page.unroute('**/agent/runs');
      } else await route.continue();
    });
    await page.click('#popup-detail');
    await page.waitForSelector('#popup-retry:not([hidden])');
    assert.equal(runs.at(-1).action,'explain_detail');
    await page.click('#popup-retry');
    await page.waitForFunction(()=>!document.querySelector('#popup-submit').disabled && document.querySelector('#popup-answer').textContent.includes('测试模型回答'));
    assert.equal(runs.at(-1).action,'explain_detail');
    assert.equal(await page.locator('#popup-detail').textContent(),'重新详细解释');
    await page.click('#popup-input-entry');
    await page.fill('#popup-question','再给一个小例子');
    await page.click('#popup-submit');
    await page.waitForFunction(()=>!document.querySelector('#popup-submit').disabled && document.querySelector('#popup-answer').textContent.includes('测试模型回答'));
    assert.equal(runs.at(-1).action,'explain_detail');
    await page.click('#popup-tab-translate');
    assert.equal(await page.locator('#popup-detail').isVisible(),false);
    await page.click('#popup-tab-explain');
    assert.equal(await page.locator('#popup-detail').textContent(),'重新详细解释');
    await page.click('#popup-transfer');
    await page.waitForSelector('#selection-popup[hidden]',{state:'attached'});
    await page.waitForFunction(()=>document.querySelectorAll('.message.assistant').length>=2);
    await page.screenshot({path:path.resolve('.cache/agent-workspace.png'),fullPage:true});
    await page.reload();
    await page.waitForFunction(()=>document.querySelectorAll('.message.assistant').length>=2);
    await page.goto('http://127.0.0.1:8002/#/settings');
    await page.waitForSelector('#agent-mode-select');
    await page.selectOption('#agent-mode-select','demo');
    await page.waitForFunction(()=>document.querySelector('#agent-mode-label').textContent.includes('演示模式'));
    await page.screenshot({path:path.resolve('.cache/agent-settings.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    console.log('PASS: browser chat, translation, detailed explanation request/retry/follow-up, tab isolation, transfer, persistence and settings');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
