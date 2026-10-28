// Requires prompt_browser_server.py. Uses actual wheel/keyboard input, no model API.
const {chromium} = require('../.cache/ui-test/node_modules/playwright');
const assert = require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try {
  for(const viewport of [{width:1360,height:850},{width:600,height:700}]){
   const context=await browser.newContext({viewport});
   const page=await context.newPage();
   await page.goto('http://127.0.0.1:8003/#/settings/prompts');
   await page.waitForSelector('#prompt-summary:not([disabled])');
   if(viewport.width<800){
    if(!await page.locator('#content-frame').evaluate(el=>el.classList.contains('menu-collapsed'))) await page.click('#menu-button');
    await page.waitForFunction(()=>document.querySelector('#content-frame').classList.contains('menu-collapsed'));
    await page.waitForFunction(()=>document.querySelector('#course-menu-slot').getBoundingClientRect().right<=document.querySelector('#content-frame').getBoundingClientRect().left+2);
   }
   const panel=page.locator('#settings-page');
   const box=await panel.boundingBox();
   const before=await page.locator('.topbar').boundingBox();
   const start=await panel.evaluate(el=>({top:el.scrollTop,height:el.clientHeight,total:el.scrollHeight}));
   assert.ok(start.total>start.height,'Settings must have content beyond the viewport');
   await page.mouse.move(box.x+12,box.y+100);
   await page.mouse.wheel(0,600);
   await page.waitForFunction(()=>document.querySelector('#settings-page').scrollTop>0,null,{timeout:4000});
   const down=await panel.evaluate(el=>el.scrollTop);
   await page.mouse.wheel(0,-600);
   await page.waitForFunction(top=>document.querySelector('#settings-page').scrollTop<top,down,{timeout:4000});
   await panel.focus();
   await page.keyboard.press('Control+End');
   await page.waitForFunction(()=>{const el=document.querySelector('#settings-page');return el.scrollTop+el.clientHeight>=el.scrollHeight-2;},null,{timeout:4000});
   await page.waitForFunction(()=>{const r=document.querySelector('#prompt-save-summary').getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;});
   const after=await page.locator('.topbar').boundingBox();
   assert.equal(before.y,after.y);
   assert.equal(await page.evaluate(()=>document.scrollingElement.scrollTop),0);
   await page.keyboard.press('Control+Home');
   await page.waitForFunction(()=>document.querySelector('#settings-page').scrollTop===0,null,{timeout:4000});
   console.log('PASS: wheel up/down, keyboard top/bottom and last save button reachable at '+viewport.width+'px; app chrome stays fixed');
   await context.close();
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
