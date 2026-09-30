// 滚动回归：使用真实演示数据，拦截所有网络请求，不连接数据库或触发消息外发。
// 运行：node backend/tests/scroll-regression.mjs
// 可选：PLAYWRIGHT_MODULE 指向 Playwright 包；FRONTEND_ARTIFACT_DIR 保存截图。
import assert from 'node:assert/strict';
import {mkdir, readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const html = await readFile(process.env.FRONTEND_HTML || new URL('../app/static/index.html', import.meta.url), 'utf8');
const seed = JSON.parse(await readFile(new URL('../app/seed.json', import.meta.url), 'utf8'));
const browser = await chromium.launch({headless:true});
const failures = [];
let passed = 0;

async function fixture({mobile=false, width=1024, height=768}={}){
  const context = await browser.newContext({
    viewport:{width,height}, timezoneId:'Asia/Taipei', isMobile:mobile, hasTouch:mobile,
  });
  const page = await context.newPage();
  const errors = [];
  page.setDefaultTimeout(2500);
  page.on('pageerror', error=>errors.push(error.message));
  await page.clock.setFixedTime(new Date('2026-09-22T08:00:00Z'));
  await page.route('**/*', async route=>{
    const url = new URL(route.request().url());
    if(url.origin==='http://cockpit.test' && url.pathname==='/'){
      return route.fulfill({contentType:'text/html',body:html});
    }
    if(url.origin==='http://cockpit.test' && url.pathname==='/api/bootstrap'){
      return route.fulfill({json:{...seed,autoLog:[],serverTimezone:'America/New_York'}});
    }
    errors.push('Unexpected request: '+url.href);
    return route.fulfill({status:404,json:{detail:'Unexpected test request'}});
  });
  await page.goto('http://cockpit.test/');
  await page.waitForFunction(()=>ALL_CASES.length>0);
  return {page,context,errors};
}

async function test(name, options, callback){
  const {page,context,errors} = await fixture(options);
  try{
    await callback(page,context);
    assert.deepEqual(errors,[],'Browser errors or unmocked requests');
    passed++;
    console.log('PASS '+name);
  }catch(error){
    failures.push({name,message:error.message});
    console.error('FAIL '+name+'\n'+error.message);
    if(process.env.FRONTEND_ARTIFACT_DIR) await screenshot(page,'failure-'+failures.length);
  }finally{
    await context.close();
  }
}

async function screenshot(page,name){
  if(!process.env.FRONTEND_ARTIFACT_DIR) return;
  await mkdir(process.env.FRONTEND_ARTIFACT_DIR,{recursive:true});
  await page.screenshot({path:join(process.env.FRONTEND_ARTIFACT_DIR,'scroll-'+name+'.png'),fullPage:true});
}

async function navigate(page,view){
  await page.locator(`[data-nav="${view}"]`).click();
  await page.waitForFunction(view=>state.view===view,view);
}

async function tableRegion(page){
  return page.locator('#app table.data-table').first().locator('..');
}

async function moveOverTable(page){
  const region = await tableRegion(page);
  // 仅设置测试的起始视口；之后的位移全部由真实输入驱动。
  await region.evaluate(element=>window.scrollTo(0,element.getBoundingClientRect().top+window.scrollY-160));
  const box = await region.boundingBox();
  await page.mouse.move(box.x+Math.min(box.width/2,220),Math.max(190,box.y+70));
  return region;
}

async function swipe(session,from,to){
  await session.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{...from,id:1}]});
  for(let step=1;step<=10;step++){
    await session.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{
      x:from.x+(to.x-from.x)*step/10,y:from.y+(to.y-from.y)*step/10,id:1,
    }]});
    await new Promise(resolve=>setTimeout(resolve,16));
  }
  await session.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
}

try{
  await test('Vertical wheel over a wide table scrolls the page down and up',{width:900},async page=>{
    await navigate(page,'database');
    const region = await moveOverTable(page);
    const start = await page.evaluate(()=>window.scrollY);
    await page.mouse.wheel(0,480);
    await page.waitForFunction(start=>window.scrollY>start+200,start);
    assert.equal(await region.evaluate(element=>element.scrollLeft),0,'Vertical wheel must not pan the table');
    const down = await page.evaluate(()=>window.scrollY);
    await page.mouse.wheel(0,-320);
    await page.waitForFunction(down=>window.scrollY<down-150,down);
    assert.equal(await page.evaluate(()=>window.scrollX),0,'Page must stay horizontally aligned');
  });

  await test('Horizontal wheel reaches both table edges without moving the page',{width:900},async page=>{
    await navigate(page,'database');
    const region = await moveOverTable(page);
    assert.ok(await region.evaluate(element=>element.scrollWidth>element.clientWidth+100));
    const startY = await page.evaluate(()=>window.scrollY);
    await page.mouse.wheel(10000,0);
    await page.waitForFunction(()=>{
      const region=document.querySelector('#app table.data-table').parentElement;
      return Math.abs(region.scrollWidth-region.clientWidth-region.scrollLeft)<2;
    });
    await screenshot(page,'table-right-edge');
    await page.mouse.wheel(-10000,0);
    await page.waitForFunction(()=>document.querySelector('#app table.data-table').parentElement.scrollLeft<2);
    assert.equal(await page.evaluate(()=>window.scrollY),startY,'Horizontal input must not scroll the page vertically');
    assert.equal(await page.evaluate(()=>window.scrollX),0);
  });

  await test('Shift-wheel pans the table while ordinary wheel remains vertical',{width:900},async page=>{
    await navigate(page,'database');
    const region = await moveOverTable(page);
    const startY = await page.evaluate(()=>window.scrollY);
    await page.keyboard.down('Shift');
    try{ await page.mouse.wheel(0,320); }finally{ await page.keyboard.up('Shift'); }
    await page.waitForFunction(()=>document.querySelector('#app table.data-table').parentElement.scrollLeft>100);
    assert.equal(await page.evaluate(()=>window.scrollY),startY);
    assert.ok(await region.evaluate(element=>element.scrollLeft<element.scrollWidth));
  });

  await test('Wide table region is labelled, keyboard reachable and scrollable',{width:900},async page=>{
    await navigate(page,'database');
    const region = await tableRegion(page);
    assert.equal(await region.getAttribute('role'),'region');
    assert.ok(await region.getAttribute('aria-label'),'A keyboard region needs an accessible name');
    await page.locator('#dbMinutesBtn').focus();  // 工具栏最后一个控件（Export CSV 之后是两个 .xlsx 导出按钮）
    await page.keyboard.press('Tab');
    assert.ok(await region.evaluate(element=>document.activeElement===element),'Tab after the toolbar must reach the table');
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(()=>document.querySelector('#app table.data-table').parentElement.scrollLeft>10);
    await page.keyboard.press('ArrowLeft');
    await page.waitForFunction(()=>document.querySelector('#app table.data-table').parentElement.scrollLeft<2);
  });

  await test('Ctrl/Meta-wheel stays available for browser zoom over navigation',{width:390,height:844},async page=>{
    const outcome = await page.locator('#navtabs').evaluate(nav=>{
      const results=[];
      for(const modifier of ['ctrlKey','metaKey']){
        const event=new WheelEvent('wheel',{deltaY:120,[modifier]:true,bubbles:true,cancelable:true});
        nav.dispatchEvent(event);
        results.push({prevented:event.defaultPrevented,left:nav.scrollLeft});
      }
      return results;
    });
    assert.deepEqual(outcome,[{prevented:false,left:0},{prevented:false,left:0}]);
  });

  await test('Mouse drag pans navigation without selecting a tab; next click works',{width:390,height:844},async page=>{
    const nav = page.locator('#navtabs');
    const box = await nav.boundingBox();
    await page.mouse.move(box.x+240,box.y+box.height/2);
    await page.mouse.down();
    await page.mouse.move(box.x+65,box.y+box.height/2,{steps:8});
    await page.mouse.up();
    assert.ok(await nav.evaluate(element=>element.scrollLeft)>80,'Drag must move the navigation strip');
    assert.equal(await page.evaluate(()=>state.view),'home','Dragging must not activate a tab');
    await navigate(page,'followups');
  });

  await test('Navigation drag released outside the strip does not swallow the next click',{width:390,height:844},async page=>{
    const box = await page.locator('#navtabs').boundingBox();
    await page.mouse.move(box.x+240,box.y+box.height/2);
    await page.mouse.down();
    await page.mouse.move(box.x+60,box.y+box.height+80,{steps:8});
    await page.mouse.up();
    await navigate(page,'followups');
  });

  await test('Cancelled pointer gesture releases navigation drag state',{width:390,height:844},async page=>{
    const nav = page.locator('#navtabs');
    const box = await nav.boundingBox();
    await page.mouse.move(box.x+240,box.y+box.height/2);
    await page.mouse.down();
    await page.mouse.move(box.x+140,box.y+box.height/2,{steps:4});
    await nav.dispatchEvent('pointercancel',{pointerId:1,pointerType:'mouse',bubbles:true});
    const cancelled = await nav.evaluate(element=>element.scrollLeft);
    await page.mouse.move(box.x+50,box.y+box.height/2,{steps:4});
    assert.equal(await nav.evaluate(element=>element.scrollLeft),cancelled,'Pointer cancellation must stop the drag');
    await page.mouse.up();
    await navigate(page,'followups');
  });

  await test('Keyboard Tab exposes every navigation tab across mobile and tablet widths',{width:390,height:844},async page=>{
    for(const width of [390,701,768,1024]){
      await page.setViewportSize({width,height:844});
      await page.locator('[data-nav="home"]').focus();
      for(const view of ['home','submit','approvals','database','dashboard','followups']){
        const visible = await page.evaluate(view=>{
          const button=document.querySelector(`[data-nav="${view}"]`);
          const rect=button.getBoundingClientRect(),nav=document.getElementById('navtabs').getBoundingClientRect();
          return document.activeElement===button && rect.left>=nav.left-1 && rect.right<=nav.right+1;
        },view);
        assert.ok(visible,`Focused ${view} tab must be visible at ${width}px`);
        if(view!=='followups') await page.keyboard.press('Tab');
      }
    }
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(()=>state.view),'followups');
  });

  await test('Native mobile swipes pan navigation in both directions without activation',{mobile:true,width:390,height:844},async(page,context)=>{
    const session = await context.newCDPSession(page);
    const nav = page.locator('#navtabs');
    const box = await nav.boundingBox();
    const y = box.y+box.height/2;
    await swipe(session,{x:320,y},{x:65,y});
    await page.waitForFunction(()=>document.getElementById('navtabs').scrollLeft>80);
    assert.equal(await page.evaluate(()=>state.view),'home');
    await swipe(session,{x:65,y},{x:320,y});
    await page.waitForFunction(()=>document.getElementById('navtabs').scrollLeft<2);
    await navigate(page,'submit');
  });

  await test('Native mobile table swipes reach the last column and leave vertical scrolling usable',{mobile:true,width:390,height:844},async(page,context)=>{
    await navigate(page,'database');
    const region = await moveOverTable(page);
    const session = await context.newCDPSession(page);
    for(let attempt=0;attempt<6;attempt++){
      if(await region.evaluate(element=>element.scrollLeft>=element.scrollWidth-element.clientWidth-2)) break;
      await swipe(session,{x:335,y:275},{x:45,y:275});
    }
    await page.waitForFunction(()=>{
      const region=document.querySelector('#app table.data-table').parentElement;
      return region.scrollLeft>=region.scrollWidth-region.clientWidth-2;
    });
    const startY = await page.evaluate(()=>window.scrollY);
    await swipe(session,{x:195,y:660},{x:195,y:300});
    await page.waitForFunction(startY=>window.scrollY>startY+150,startY);
    assert.equal(await page.evaluate(()=>window.scrollX),0);
    assert.equal(await page.evaluate(()=>state.view),'database','Swiping a row must not open its detail');
    await screenshot(page,'mobile-table-swiped');
  });

  await test('Opening and closing a reminder retains the table horizontal position',{width:390,height:844},async page=>{
    await navigate(page,'followups');
    await page.evaluate(()=>{ state.isAdmin=true; render(); });  // "Send reminder" 只对管理员显示
    const region = await moveOverTable(page);
    await page.mouse.wheel(10000,0);
    await page.waitForFunction(()=>{
      const region=document.querySelector('#app table.data-table').parentElement;
      return region.scrollLeft>100 && region.scrollLeft>=region.scrollWidth-region.clientWidth-2;
    });
    const position = await region.evaluate(element=>element.scrollLeft);
    const button = page.locator('[data-remind-open]').first();
    const taskId = await button.getAttribute('data-remind-open');
    await button.click();
    assert.equal(await page.evaluate(()=>state.remindOpenId),taskId);
    const opened = await region.evaluate(element=>({left:element.scrollLeft,max:element.scrollWidth-element.clientWidth}));
    assert.ok(Math.abs(opened.left-Math.min(position,opened.max))<2,
      `Expanding the reminder must retain the visible columns: ${position} -> ${opened.left}`);
    await page.locator(`[data-remind-open="${taskId}"]`).click();
    assert.equal(await page.evaluate(()=>state.remindOpenId),null);
    const closed = await region.evaluate(element=>({left:element.scrollLeft,max:element.scrollWidth-element.clientWidth}));
    assert.ok(Math.abs(closed.left-Math.min(opened.left,closed.max))<2,
      `Closing the reminder must retain the visible columns: ${opened.left} -> ${closed.left}`);
  });

  await test('Sorting follow-ups retains the visible table columns',{width:390,height:844},async page=>{
    await navigate(page,'followups');
    const region = await moveOverTable(page);
    await page.mouse.wheel(10000,0);
    await page.waitForFunction(()=>document.querySelector('#app table.data-table').parentElement.scrollLeft>100);
    await page.locator('#sortDueTh').scrollIntoViewIfNeeded();
    const before = await region.evaluate(element=>element.scrollLeft);
    const direction = await page.evaluate(()=>state.followupSortDir);
    await page.locator('#sortDueTh').click();
    assert.notEqual(await page.evaluate(()=>state.followupSortDir),direction);
    const after = await region.evaluate(element=>element.scrollLeft);
    assert.ok(Math.abs(after-before)<2,`Sorting must retain horizontal position: ${before} -> ${after}`);
  });

  await test('Switching pages from the bottom returns to the new page heading',{},async page=>{
    await navigate(page,'database');
    await moveOverTable(page);
    await page.mouse.wheel(0,20000);
    await page.waitForFunction(()=>scrollY>100 && document.documentElement.scrollHeight-innerHeight-scrollY<2);
    await navigate(page,'submit');
    assert.equal(await page.evaluate(()=>window.scrollY),0,'A new page must start at its heading');
    const heading = await page.locator('#app h1').boundingBox();
    const header = await page.locator('.topbar').boundingBox();
    assert.ok(heading.y>=header.y+header.height && heading.y<page.viewportSize().height);
  });

  await test('Login controls remain visible above a toast in a short mobile viewport',{width:320,height:300},async page=>{
    await page.locator('#adminToggle').click();
    await page.evaluate(()=>toast('The server could not be reached. Check your connection and try again. '.repeat(3)));
    await page.locator('#adminLoginBtn').scrollIntoViewIfNeeded();
    const result = await page.evaluate(()=>{
      const button=document.getElementById('adminLoginBtn');
      const rect=button.getBoundingClientRect();
      const x=rect.left+rect.width/2,y=rect.top+rect.height/2;
      const clickable=button.contains(document.elementFromPoint(x,y));
      const toast=document.getElementById('scToast');
      // 提示本身穿透点击；临时参与命中测试，额外检查视觉层级是否盖住登录按钮。
      const pointerEvents=toast.style.pointerEvents;
      toast.style.pointerEvents='auto';
      const unobscured=button.contains(document.elementFromPoint(x,y));
      toast.style.pointerEvents=pointerEvents;
      return {clickable,unobscured,insideViewport:rect.left>=0 && rect.right<=innerWidth && rect.top>=0 && rect.bottom<=innerHeight};
    });
    assert.deepEqual(result,{clickable:true,unobscured:true,insideViewport:true});
    await screenshot(page,'short-mobile-login-toast');
    await page.locator('#adminLoginCancel').click();
    assert.equal(await page.locator('#adminLoginPanel').count(),0);
  });

  await test('All pages reflow when resized between desktop, tablet and narrow mobile',{},async page=>{
    for(const width of [1440,1024,768,701,390,320,1440]){
      await page.setViewportSize({width,height:900});
      for(const view of ['home','submit','approvals','database','dashboard','followups']){
        await navigate(page,view);
        const dimensions = await page.evaluate(()=>({width:innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
        assert.ok(dimensions.document<=dimensions.width+2 && dimensions.body<=dimensions.width+2,
          `${view} at ${width}px must not overflow the document: ${JSON.stringify(dimensions)}`);
        if((width===390 || width===1440) && (view==='home' || view==='database')) await screenshot(page,`${width}-${view}`);
      }
    }
  });

  console.log(`${passed} scroll regression checks passed; ${failures.length} failed.`);
  if(failures.length) process.exitCode=1;
}finally{
  await browser.close();
}
