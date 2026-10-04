// Uses the installed Edge and .cache/ui-test/playwright; test server is isolated.
const {chromium} = require('../.cache/ui-test/node_modules/playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try {
    const context = await browser.newContext({viewport:{width:1360,height:850}});
    const page = await context.newPage(), errors=[];
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
    console.log('PASS: browser chat streaming/citations, popup translation follow-up, transfer, refresh persistence and mode settings');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
