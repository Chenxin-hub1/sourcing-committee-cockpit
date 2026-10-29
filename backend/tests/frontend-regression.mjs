// 浏览器回归：API 全部拦截，不连接实际数据库，也不触发任何邮件或 Teams 外发。
// 已安装 Playwright 时：node backend/tests/frontend-regression.mjs
// 非本地安装可通过 PLAYWRIGHT_MODULE 指定 Playwright 包的绝对路径。
import assert from 'node:assert/strict';
import {mkdir, readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const html = await readFile(new URL('../app/static/index.html', import.meta.url), 'utf8');
const browser = await chromium.launch({headless:true});
// v3 Phase-18：待办分类规则随 bootstrap 下发（这里是服务端 logic.task_rules 的子集，足够覆盖用例）
const TASK_RULES = {categories:['CQA','Volume','Technical','Timing','Supplier strategy','BPG','Saving','Further VAVE'],
  keywords:{CQA:['quality','sample','ppap'], Volume:['volume'], Technical:['drawing','test'], Timing:['timing','kw','deadline'], 'Supplier strategy':['strateg'], BPG:['bpg'], Saving:['saving','cost','costs','price'], 'Further VAVE':['vave']},
  tagSynonyms:{cost:'Saving', quality:'CQA', timing:'Timing', vave:'Further VAVE'}, functions:['Purchasing','Supplier Quality','Engineering']};
const empty = {cases:[], submissions:[], autoLog:[], serverTimezone:'America/New_York', taskRules:TASK_RULES};
// v3 Phase-6 个人账号：bootstrap 的 currentUser 决定页面权限（服务端另行强制）
const USER = {email:'test.user@zf.com', name:'Test owner', role:'user', roleLabel:'User', disabled:false, mustChangePassword:false, createdAt:'Sep 24, 9:00 AM', lastLoginAt:'Sep 24, 9:05 AM'};
const MANAGER = {...USER, email:'npi@zf.com', name:'NPI Person', role:'npi_manager', roleLabel:'Manager'};
const ADMIN = {...USER, email:'admin@zf.com', name:'Sourcing Admin', role:'admin', roleLabel:'Sourcing admin'};
const USERS = {user:USER, manager:MANAGER, admin:ADMIN};
const errors = [];
let passed = 0;

// v3 Phase-26：Submit / Approval / Follow-ups 在 Case Workflow 组，Database / Dashboard 在 Data 组 —— 侧边栏没显示就先点组名
const NAV_GROUP_OF = {submit:'workflow', approvals:'workflow', followups:'workflow', database:'data', dashboard:'data'};
async function goTo(page, view){
  const item = page.locator(`#sidenav [data-nav="${view}"]`);
  if(!(await item.isVisible())) await page.locator(`[data-nav-group="${NAV_GROUP_OF[view]}"]`).click();
  await item.click();
}

async function fixture({timezoneId='Asia/Taipei', hash='', before, api, user}={}){
  const context = await browser.newContext({timezoneId});
  const page = await context.newPage();
  page.on('pageerror', error=>errors.push(error.message));
  await page.clock.setFixedTime(new Date('2026-12-20T12:00:00Z'));
  // user: 'user' | 'manager' | 'admin' —— 带着登录令牌打开页面，bootstrap 返回对应账号
  if(user) await page.addInitScript(()=>{ try{ localStorage.setItem('sc_session_token','tok'); }catch(e){} });
  if(before) await before(page);
  await page.route('**/*', async route=>{
    const path = new URL(route.request().url()).pathname;
    if(path==='/') return route.fulfill({contentType:'text/html', body:html});
    if(api && await api(route, path)) return;
    if(path==='/api/bootstrap') return route.fulfill({json:{...empty, currentUser: user ? USERS[user] : null}});
    return route.fulfill({status:404, json:{detail:'Unexpected test request: '+path}});
  });
  await page.goto('http://cockpit.test/'+hash);
  await page.locator('#app h1').waitFor();
  return {page, context};
}

async function test(name, callback){
  const previous = errors.length;
  await callback();
  assert.deepEqual(errors.slice(previous), [], 'Browser errors');
  passed++;
  console.log('PASS '+name);
}

// 反馈 PPT 第 2 页：商务字段成为必填，每个走到提交的用例都要填一遍（件价 / 模具费按零件行，反馈人 MM 模板）
async function fillCommercial(page, over={}){
  const values = {pnPcPriceCQA_0:'1.25', pnSupplierPriceLanded_0:'1.1', pnToolingCQA_0:'120000', pnSupplierToolingCost_0:'118500', ...over};
  for(const [id,value] of Object.entries(values)) await page.locator('#'+id).fill(value);
  await page.locator('#fToolingPayment').selectOption('Lumpsum');
  await page.locator('#qFRA').selectOption('Yes');
}

async function seed(page, overrides={}){
  return page.evaluate(overrides=>{
    const c = mkCase({id:'C-TEST', swatId:'SWAT-TEST', partNumber:'1234', partDescription:'Test part',
      weekNum:40, caseNumber:1, recommendedSupplier:'Test supplier', presenter:'Test owner',
      region:'AP', cluster:'Metal', meetingDecision:'PENDING', ...overrides});
    applySnapshot({cases:[c]});
    return JSON.parse(JSON.stringify(c));
  }, overrides);
}

try{
  await test('A comments save finishing on another page preserves that page\'s draft', async()=>{
    let pending;
    const {page, context} = await fixture({user:'manager', api:async(route,path)=>{
      if(path!=='/api/cases/C-TEST/comments') return false;
      pending = route;
      return true;
    }});
    const c = await seed(page, {submitterComments:'Original background'});
    await page.evaluate(()=>goToDetail('SWAT-TEST'));
    await page.locator('#caseCommentsEdit').click();
    await page.locator('#caseCommentsIn').fill('Saved background');
    await page.locator('#caseCommentsSave').click();
    await page.waitForFunction(()=>API.pendingWrites===1);
    await goTo(page, 'submit');
    await page.locator('#fPresenter').fill('New registration draft');
    await pending.fulfill({json:{snapshot:{cases:[{...c, submitterComments:'Saved background'}]}}});
    await page.waitForFunction(()=>API.pendingWrites===0);
    assert.equal(await page.locator('#fPresenter').inputValue(), 'New registration draft');
    assert.equal(await page.evaluate(()=>state.commentsEditId), null);
    await goTo(page, 'database');
    assert.equal(await page.evaluate(()=>canRefresh()), true, 'Leaving comments must release the automatic-refresh guard');
    await page.evaluate(()=>goToDetail('SWAT-TEST'));
    assert.match(await page.locator('#caseCommentsCard').innerText(), /Saved background/);
    await context.close();
  });

  await test('Slow action-item extraction preserves newer edits and ignores an abandoned editor', async()=>{
    let pending;
    const {page, context} = await fixture({user:'manager', api:async(route,path)=>{
      if(path!=='/api/action-items/extract') return false;
      pending = route;
      return true;
    }});
    await seed(page, {committeeDiscussion:'1. Original task'});
    await page.evaluate(()=>goToDetail('SWAT-TEST'));
    await page.locator('#editCaseBtn').click();
    await page.locator('#extractTasksBtn').click();
    await page.waitForFunction(()=>API.pendingWrites===1);
    await page.locator('#editDiscussion').fill('1. Original task\nAdditional committee notes');
    await page.locator('#editPresenter').fill('Updated presenter');
    await pending.fulfill({json:{items:[]}});
    await page.locator('.action-drafts').waitFor();
    assert.equal(await page.locator('#editDiscussion').inputValue(), '1. Original task\nAdditional committee notes');
    assert.equal(await page.locator('#editPresenter').inputValue(), 'Updated presenter');
    await page.locator('#discardDraftsBtn').click();
    pending = null;
    await page.locator('#extractTasksBtn').click();
    await page.waitForFunction(()=>API.pendingWrites===1);
    await page.locator('#editPresenter').fill('Edited while request failed');
    await pending.fulfill({status:503, json:{detail:'Extraction temporarily unavailable'}});
    await page.waitForFunction(()=>state.editError?.includes('Extraction temporarily unavailable'));
    assert.equal(await page.locator('#editPresenter').inputValue(), 'Edited while request failed');
    pending = null;
    await page.locator('#extractTasksBtn').click();
    await page.waitForFunction(()=>API.pendingWrites===1);
    await goTo(page, 'submit');
    await page.locator('#fPresenter').fill('New registration draft');
    await pending.fulfill({json:{items:[]}});
    await page.waitForFunction(()=>API.pendingWrites===0);
    assert.equal(await page.locator('#fPresenter').inputValue(), 'New registration draft');
    assert.equal(await page.evaluate(()=>state.actionDrafts), null);
    await context.close();
  });

  await test('Database search keeps the cursor and active text composition while filtering', async()=>{
    const {page, context} = await fixture();
    await seed(page);
    await goTo(page, 'database');
    const search = page.locator('#dbSearch');
    await search.fill('sulier');
    await search.press('Home');
    await search.press('ArrowRight');
    await search.press('ArrowRight');
    await page.keyboard.type('pp');
    assert.equal(await search.inputValue(), 'supplier', 'Typing inside a query must keep the cursor in place');
    assert.equal(await page.locator('tr[data-swat]').count(), 1);
    // 输入法组合期间搜索框不能被替换，否则中文等尚未确认的输入会被打断。
    const composing = await search.evaluate(input=>{
      input.dispatchEvent(new CompositionEvent('compositionstart', {bubbles:true}));
      input.value = '供应商';
      input.dispatchEvent(new InputEvent('input', {bubbles:true, isComposing:true, data:'供应商'}));
      const retained = input.isConnected && document.activeElement===input;
      input.dispatchEvent(new CompositionEvent('compositionend', {bubbles:true, data:'供应商'}));
      return retained;
    });
    assert.equal(composing, true, 'An active composition must retain its input element');
    assert.equal(await page.evaluate(()=>state.searchQuery), '供应商');
    await context.close();
  });

  for(const timezoneId of ['Asia/Taipei','America/New_York','Europe/Berlin']){
    await test('Wednesday calendar values and next-year labels in '+timezoneId, async()=>{
      const {page, context} = await fixture({timezoneId, user:'user'});
      await goTo(page, 'submit');
      const dates = await page.locator('#fMeetingDate option').evaluateAll(options=>options.map(o=>({
        value:o.value, text:o.textContent, day:new Date(o.value+'T00:00:00').getDay()
      })));
      assert.equal(dates.length,12);
      for(const date of dates){
        assert.equal(date.day,3,date.text);
        assert.ok(date.text.startsWith(date.value.slice(0,4)+'-KW'),date.text);
      }
      // ISO 周（KW）：2026-12-30 是 2026-KW53，2027-01-06 是 2027-KW01
      assert.ok(dates.some(d=>d.value==='2026-12-30' && d.text.startsWith('2026-KW53 — ')), JSON.stringify(dates));
      assert.ok(dates.some(d=>d.value==='2027-01-06' && d.text.startsWith('2027-KW01 — ')), JSON.stringify(dates));
      assert.deepEqual(await page.evaluate(()=>[dateToWeekNum(new Date(2027,0,6)), dateToWeekNum(new Date(2026,8,30)),
        dateToWeekNum(new Date(2026,0,7)), dateToWeekNum(new Date(2025,11,31)), isoWeekYear(new Date(2025,11,31)), wk(40, 2026), weekDate(40)]),
        [1, 40, 2, 1, 2026, '2026-KW40', 'Sep 30, 2026']);
      await context.close();
    });
  }

  await test('Submission sends its displayed Wednesday', async()=>{
    let submitted;
    const {page, context} = await fixture({user:'user', api:async(route,path)=>{
      if(path!=='/api/submissions') return false;
      submitted = route.request().postDataJSON();
      await route.fulfill({json:{subId:'SUB-TEST',snapshot:empty}});
      return true;
    }});
    await goTo(page, 'submit');
    for(const [id,value] of Object.entries({fExistingSwat:'SWAT-1000',pnSupplier_0:'Test supplier',pnProject_0:'Test project',pnPartNumber_0:'1234',pnPartDescription_0:'Test part',fBundlePeak:'10',fBundleLife:'20'})){
      await page.locator('#'+id).fill(value);
    }
    await page.locator('#fRegionIn input[value="EU"]').check();
    await page.locator('#qFamily').selectOption('No');
    await page.locator('#qECM').selectOption('No');
    await fillCommercial(page);
    const selected = await page.locator('#fMeetingDate').inputValue();
    await page.locator('#submitCaseBtn').click();
    await page.waitForFunction(()=>document.getElementById('submitBanner')?.textContent.includes('SUB-TEST'));
    assert.equal(submitted.meetingDateISO,selected);
    assert.ok(submitted.meetingDateLabel.startsWith('Wed'));
    await context.close();
  });

  await test('Free-text project is required and family alignment needs no evidence link', async()=>{
    let submitted;
    const {page, context} = await fixture({user:'user', api:async(route,path)=>{
      if(path!=='/api/submissions') return false;
      submitted = route.request().postDataJSON();
      await route.fulfill({json:{subId:'SUB-TEST',snapshot:empty}});
      return true;
    }});
    await goTo(page, 'submit');
    assert.equal(await page.locator('#pnProject_0').evaluate(el=>el.tagName),'INPUT');
    for(const [id,value] of Object.entries({fExistingSwat:'SWAT-1001',pnSupplier_0:'Test supplier',pnPartNumber_0:'1234',pnPartDescription_0:'Test part',fBundlePeak:'10',fBundleLife:'20'})){
      await page.locator('#'+id).fill(value);
    }
    await page.locator('#qFamily').selectOption('Yes');
    await page.locator('#qFamilyAligned').selectOption('Yes');
    assert.equal(await page.locator('#qFamilyEvidence').count(),0);
    await page.locator('#qECM').selectOption('No');
    await fillCommercial(page);
    await page.locator('#submitCaseBtn').click();
    // v3 Phase-15：项目按零件行，与类型 / 供应商一起校验
    await page.waitForFunction(()=>document.getElementById('submitBanner')?.textContent.includes('Project, Sourcing Type and Recommended Supplier for every part number row'));
    assert.equal(submitted,undefined);
    await page.locator('#pnProject_0').fill('  MBEAL ');
    await page.locator('#submitCaseBtn').click();
    await page.waitForFunction(()=>document.getElementById('submitBanner')?.textContent.includes('Region'));
    assert.equal(submitted,undefined);
    await page.locator('#fRegionIn input[value="NA"]').check();
    await page.locator('#fRegionIn input[value="EU"]').check();
    await page.locator('#submitCaseBtn').click();
    await page.waitForFunction(()=>document.getElementById('submitBanner')?.textContent.includes('SUB-TEST'));
    assert.deepEqual(submitted.region,['EU','NA']);
    assert.equal(submitted.partNumbers[0].project,'MBEAL');  // 行上的项目（服务端汇总到案例级）
    assert.equal(submitted.partNumbers[0].sourcingType,'New');
    assert.equal(submitted.partNumbers[0].recommendedSupplier,'Test supplier');
    assert.ok(!('project' in submitted));
    assert.equal(submitted.familyAligned,'Yes');
    assert.ok(!('familyEvidence' in submitted));
    await context.close();
  });

  await test('Spend can be entered in USD or CNY and is shown with its EUR conversion', async()=>{
    let submitted;
    const fxSettings = {basis:'OP 2026', perEur:{USD:'1.25'}, updatedAt:'Sep 24, 9:00 AM'};
    const {page, context} = await fixture({api:async(route,path)=>{
      if(path==='/api/bootstrap'){ await route.fulfill({json:{...empty, fxSettings, currentUser:USER}}); return true; }
      if(path!=='/api/submissions') return false;
      submitted = route.request().postDataJSON();
      await route.fulfill({json:{subId:'SUB-TEST',snapshot:{...empty, fxSettings}}});
      return true;
    }});
    await goTo(page, 'submit');
    assert.equal(await page.locator('#fCurrency').inputValue(),'EUR');
    await page.locator('#fCurrency').selectOption('USD');
    const curLabels = await page.locator('.cur-label').allTextContents();
    assert.ok(curLabels.length>=2 && curLabels.every(t=>t==='USD'), curLabels);  // 支出行与商务字段的币种标签一起切换
    assert.match(await page.locator('#fxHint').textContent(),/1 EUR = 1\.25 USD \(OP 2026\)/);
    for(const [id,value] of Object.entries({fExistingSwat:'SWAT-1002',pnSupplier_0:'Test supplier',pnProject_0:'MBEAL',pnPartNumber_0:'1234',pnPartDescription_0:'Test part',
      fBundlePeak:'139000',fBundleLife:'873000'})){
      await page.locator('#'+id).fill(value);
    }
    assert.equal(await page.locator('#totalPeakDisplay').textContent(),'$139,000');
    assert.equal(await page.locator('#totalPeakEur').textContent(),'€111,200');  // 1 EUR = 1.25 USD，按除法，单独一行欧元对照
    assert.equal(await page.locator('#bundleEurRate').textContent(),'(1 EUR = 1.25 USD)');
    await page.locator('#fRegionIn input[value="EU"]').check();
    await page.locator('#qFamily').selectOption('No');
    await page.locator('#qECM').selectOption('No');
    await fillCommercial(page);
    // 没有 CNY 汇率：提示并拦截
    await page.locator('#fCurrency').selectOption('CNY');
    assert.ok(await page.locator('#fxHint.missing').count());
    await page.locator('#submitCaseBtn').click();
    await page.waitForFunction(()=>document.getElementById('submitBanner')?.textContent.includes('No exchange rate is set for CNY'));
    assert.equal(submitted,undefined);
    await page.locator('#fCurrency').selectOption('USD');
    await page.locator('#submitCaseBtn').click();
    await page.waitForFunction(()=>document.getElementById('submitBanner')?.textContent.includes('SUB-TEST'));
    assert.equal(submitted.currency,'USD');
    assert.equal(submitted.peakYearSpend,139000);  // 发送原币金额，由服务端折算
    await context.close();

    // 已折算的案例：详情显示欧元与原币，编辑页按原币编辑
    const view = await fixture();
    await seed(view.page,{peakYearSpend:111200, lifetimeSpend:698400, peakYearSpendEntered:139000, lifetimeSpendEntered:873000,
      spendCurrency:'EUR', fx:{currency:'USD', perEur:'1.25', basis:'OP 2026'}});
    await view.page.evaluate(()=>{ state.isAdmin=true; goToDetail('SWAT-TEST'); });
    const detail = await view.page.locator('#app').innerText();
    assert.ok(detail.includes('€111,200 ($139,000 entered)'), detail);
    assert.ok(detail.includes('1 EUR = 1.25 USD (OP 2026)'));
    await view.page.locator('#editCaseBtn').click();
    assert.equal(await view.page.locator('#editBundlePeak').inputValue(),'139000');
    const editText = await view.page.locator('#app').innerText();
    assert.ok(editText.includes('Bundle Peak Year Spend (USD)'));
    assert.ok(editText.includes('the rate recorded when the case was submitted'), editText);
    // 旧美元案例一次性换算后：汇率说明换成换算时间
    await view.page.evaluate(()=>{ state.detailEditMode=false; state.editBuffer=null; });
    await seed(view.page,{peakYearSpend:100, lifetimeSpend:200, peakYearSpendEntered:117, lifetimeSpendEntered:234,
      spendCurrency:'EUR', fx:{currency:'USD', perEur:'1.17', basis:'OP 2025 plan rates 2026', convertedAt:'Sep 24, 6:30 PM'}});
    await view.page.evaluate(()=>goToDetail('SWAT-TEST'));
    assert.ok((await view.page.locator('#app').innerText()).includes('€100 ($117 entered)'));
    await view.page.locator('#editCaseBtn').click();
    assert.ok((await view.page.locator('#app').innerText()).includes('converted to EUR on Sep 24, 6:30 PM'));
    // v3 早期的记录快照（1 USD = 0.92 EUR）照旧显示
    await view.page.evaluate(()=>{ state.detailEditMode=false; state.editBuffer=null; });
    await seed(view.page,{peakYearSpend:92, peakYearSpendEntered:100, spendCurrency:'EUR', fx:{currency:'USD', rate:'0.92', basis:'OP 2026'}});
    await view.page.evaluate(()=>goToDetail('SWAT-TEST'));
    assert.ok((await view.page.locator('#app').innerText()).includes('1 USD = 0.92 EUR (OP 2026)'));
    // 旧数据（无币种信息）仍按美元显示
    await seed(view.page,{peakYearSpend:1500000});
    await view.page.evaluate(()=>{ state.detailEditMode=false; state.editBuffer=null; goToDetail('SWAT-TEST'); });
    assert.ok((await view.page.locator('#app').innerText()).includes('$1,500,000'));
    await view.context.close();
  });

  await test('Exchange-rate card takes rates in the finance OP notation (1 EUR = X) and saves them as entered', async()=>{
    let saved;
    const fxSettings = {basis:'', perEur:{}, updatedAt:''};
    const {page, context} = await fixture({api:async(route,path)=>{
      if(path==='/api/bootstrap'){ await route.fulfill({json:{...empty, fxSettings, currentUser:ADMIN}}); return true; }
      if(path!=='/api/fx-settings') return false;
      saved = route.request().postDataJSON();
      await route.fulfill({json:{ok:true, snapshot:{...empty, fxSettings:{basis:saved.basis, perEur:{USD:saved.perEur.USD}, updatedAt:'Sep 24, 6:30 PM'}}}});
      return true;
    }});
    await goTo(page, 'dashboard');
    const card = await page.locator('#app').innerText();
    assert.ok(card.includes('1 EUR = ? USD') && card.includes('1 EUR = ? CNY'), card);
    await page.locator('#fxBasis').fill('OP 2025 plan rates 2026');
    await page.locator('#fxRateUSD').fill('1.17');
    await page.locator('#fxSave').click();
    await page.waitForFunction(()=>document.getElementById('fxMsg')?.textContent.includes('Saved'));
    assert.deepEqual(saved,{basis:'OP 2025 plan rates 2026', perEur:{USD:'1.17', CNY:null}});
    assert.equal(await page.locator('#fxRateUSD').inputValue(),'1.17');
    // 提交页提示与预览按除法：117 USD ≈ €100
    await goTo(page, 'submit');
    await page.locator('#fCurrency').selectOption('USD');
    assert.match(await page.locator('#fxHint').textContent(),/1 EUR = 1\.17 USD \(OP 2025 plan rates 2026\)/);
    await page.locator('#fBundlePeak').fill('117');
    assert.equal(await page.locator('#totalPeakDisplay').textContent(),'$117');
    assert.equal(await page.locator('#totalPeakEur').textContent(),'€100');
    await context.close();
  });

  await test('Presentation files are queued on the submit page, uploaded with the upload key after submitting, and listed on the case', async()=>{
    const uploads = [];
    const fileRec = {id:'F-1', name:'KW41 deck.pptx', size:2048, uploadedBy:'Test owner', uploadedAt:'Sep 24, 7:00 PM', store:'local'};
    const {page, context} = await fixture({user:'user', api:async(route,path)=>{
      if(path==='/api/submissions'){ await route.fulfill({json:{subId:'SUB-TEST', uploadKey:'key-123', snapshot:empty}}); return true; }
      if(path==='/api/submissions/SUB-TEST/files'){
        const req = route.request();
        uploads.push({name:new URL(req.url()).searchParams.get('name'), key:req.headers()['x-upload-key'], size:(req.postDataBuffer()||Buffer.alloc(0)).length});
        await route.fulfill({json:{ok:true, file:fileRec, snapshot:empty}}); return true;
      }
      return false;
    }});
    await goTo(page, 'submit');
    await page.locator('#fFiles').setInputFiles([
      {name:'KW41 deck.pptx', mimeType:'application/vnd.openxmlformats-officedocument.presentationml.presentation', buffer:Buffer.alloc(2048, 1)},
      {name:'tool.exe', mimeType:'application/octet-stream', buffer:Buffer.from('x')},
    ]);
    await page.waitForFunction(()=>document.getElementById('scToast')?.textContent.includes('only PowerPoint, PDF, Excel or Word'));
    assert.deepEqual(await page.locator('#fileQueue .fname').allTextContents(), ['📎 KW41 deck.pptx']);
    for(const [id,value] of Object.entries({fExistingSwat:'SWAT-1009',pnSupplier_0:'Test supplier',pnProject_0:'MBEAL',pnPartNumber_0:'1234',pnPartDescription_0:'Test part',
      fBundlePeak:'100',fBundleLife:'200'})){
      await page.locator('#'+id).fill(value);
    }
    await page.locator('#fRegionIn input[value="EU"]').check();
    await page.locator('#qFamily').selectOption('No');
    await page.locator('#qECM').selectOption('No');
    await fillCommercial(page);
    await page.locator('#submitCaseBtn').click();
    await page.waitForFunction(()=>document.getElementById('submitBanner')?.textContent.includes('1 file attached'));
    assert.deepEqual(uploads, [{name:'KW41 deck.pptx', key:'key-123', size:2048}]);
    assert.equal(await page.locator('#fileQueue .fname').count(), 0);  // 队列已清空
    await context.close();

    // 案例页：所有人看到下载链接；管理员可以删
    let deleted;
    const admin = await fixture({api:async(route,path)=>{
      if(path==='/api/bootstrap'){ await route.fulfill({json:{...empty, currentUser:ADMIN}}); return true; }
      if(path==='/api/cases/C-TEST/files/F-1' && route.request().method()==='DELETE'){ deleted = true; await route.fulfill({json:{ok:true, snapshot:empty}}); return true; }
      return false;
    }});
    await seed(admin.page,{files:[fileRec]});
    await admin.page.evaluate(()=>goToDetail('SWAT-TEST'));
    const link = admin.page.locator('.file-list a');
    assert.equal(await link.getAttribute('href'), '/api/files/F-1');
    assert.equal(await link.textContent(), 'KW41 deck.pptx');
    assert.ok((await admin.page.locator('.file-list .fmeta').textContent()).includes('2 KB · Test owner'));
    assert.equal(await admin.page.locator('#caseFileAdd').count(), 1);
    admin.page.once('dialog', d=>d.accept());
    await admin.page.locator('[data-file-remove="F-1"]').click();
    await admin.page.waitForFunction(()=>document.getElementById('scToast')?.textContent.includes('removed'));
    assert.equal(deleted, true);
    await admin.context.close();
    const viewer = await fixture();
    await seed(viewer.page,{files:[fileRec]});
    await viewer.page.evaluate(()=>goToDetail('SWAT-TEST'));
    assert.equal(await viewer.page.locator('.file-list a').count(), 1);
    assert.equal(await viewer.page.locator('[data-file-remove], #caseFileAdd').count(), 0);  // 非管理员只能下载
    await viewer.context.close();
  });

  await test('Commercial fields are mandatory, BPG / FRA gates block, and values reach the payload and detail page', async()=>{
    let submitted;
    const fxSettings = {basis:'OP 2026', perEur:{USD:'1.25'}, updatedAt:'Sep 24, 9:00 AM'};
    const {page, context} = await fixture({api:async(route,path)=>{
      if(path==='/api/bootstrap'){ await route.fulfill({json:{...empty, fxSettings, currentUser:USER}}); return true; }
      if(path!=='/api/submissions') return false;
      submitted = route.request().postDataJSON();
      await route.fulfill({json:{subId:'SUB-TEST',snapshot:{...empty, fxSettings}}});
      return true;
    }});
    await goTo(page, 'submit');
    for(const [id,value] of Object.entries({fExistingSwat:'SWAT-1003',pnSupplier_0:'Test supplier',pnProject_0:'MBEAL',pnPartNumber_0:'1234',pnPartDescription_0:'Test part',
      fBundlePeak:'1000000',fBundleLife:'4000000'})){
      await page.locator('#'+id).fill(value);
    }
    await page.locator('#fRegionIn input[value="EU"]').check();
    await page.locator('#qFamily').selectOption('No');
    await page.locator('#qECM').selectOption('No');
    const banner = text => page.waitForFunction(t=>document.getElementById('submitBanner')?.textContent.includes(t), text);
    // 缺件价 → 拦截；缺 Tooling Payment → 拦截
    await page.locator('#submitCaseBtn').click();
    await banner('Pc Price CQA');
    for(const [id,value] of Object.entries({pnPcPriceCQA_0:'10.50', pnSupplierPriceLanded_0:'10', pnToolingCQA_0:'100000', pnSupplierToolingCost_0:'99999.99', pnAvgVolume_0:'378979'})) await page.locator('#'+id).fill(value);
    await page.locator('#submitCaseBtn').click();
    await banner('Tooling Payment');
    await page.locator('#fToolingPayment').selectOption('MPC');
    // 4 Mio EUR 生命周期支出：BPG 提示变红、必答且不能为 No
    assert.ok(await page.locator('#bpgHint.missing').count(), 'BPG hint should turn red above 3 Mio EUR');
    await page.locator('#submitCaseBtn').click();
    await banner('whether a BPG is available');
    await page.locator('#qBPG').selectOption('No');
    assert.equal(await page.locator('#bpgWarning').evaluate(el=>getComputedStyle(el).display),'block');
    await page.locator('#submitCaseBtn').click();
    await banner('requires an available BPG');
    await page.locator('#qBPG').selectOption('Yes');
    // Level 2 → FRA 必答
    await page.locator('#submitCaseBtn').click();
    await banner('FRA');
    await page.locator('#qFRA').selectOption('Yes');
    // 低于 CQA 答 No 才出现理由栏，且必填
    assert.equal(await page.locator('#cqaJustificationField').evaluate(el=>getComputedStyle(el).display),'none');
    await page.locator('#qBelowCQA').selectOption('No');
    assert.equal(await page.locator('#cqaJustificationField').evaluate(el=>getComputedStyle(el).display),'block');
    await page.locator('#submitCaseBtn').click();
    await banner('justification');
    await page.locator('#fCqaJustification').fill('Raw material index');
    await page.locator('#fFotWeeks').fill('12');
    await page.locator('#fAmoTotal').fill('30000');
    await page.locator('#fAmoPcs').fill('120000');
    // 换成 USD：4 Mio USD / 1.25 = 3.2 Mio EUR，仍超线；币种标签同步
    await page.locator('#fCurrency').selectOption('USD');
    assert.ok((await page.locator('.cur-label').allTextContents()).every(t=>t==='USD'));
    assert.ok(await page.locator('#bpgHint.missing').count());
    assert.equal(await page.locator('#fPresenter').inputValue(),'Test owner');  // v3 Phase-28：默认本人，可改成上会的同事
    await page.locator('#fPresenter').fill('  Lingqing Hu ');
    await page.locator('#submitCaseBtn').click();
    await banner('SUB-TEST');
    assert.equal(submitted.presenter,'Lingqing Hu');
    assert.equal(submitted.submitterName,'Test owner');
    assert.equal(submitted.partNumbers[0].pcPriceCQA,'10.50');
    assert.equal(submitted.partNumbers[0].supplierToolingCost,'99999.99');
    assert.equal(submitted.partNumbers[0].averageVolume,378979);
    assert.equal(submitted.partNumbers[0].lifetimeVolume,null);
    assert.equal(submitted.pcPriceCQA,undefined);
    assert.equal(submitted.toolingPayment,'MPC');
    assert.equal(submitted.bpgAvailable,'Yes');
    assert.equal(submitted.fraAvailable,'Yes');
    assert.equal(submitted.belowCQA,'No');
    assert.equal(submitted.cqaJustification,'Raw material index');
    assert.equal(submitted.fotLeadTimeWeeks,12);
    assert.equal(submitted.ppapLeadTimeWeeks,null);
    assert.equal(submitted.amortizationTotal,'30000');
    assert.equal(submitted.amortizationPcs,120000);
    assert.equal(submitted.annualCapacity,null);
    await context.close();

    // 详情页：折算后的件价显示欧元与原币；编辑页按原币预填；旧案例给出说明
    const view = await fixture();
    await seed(view.page,{spendCurrency:'EUR', fx:{currency:'USD', perEur:'1.25', basis:'OP 2026'},
      pcPriceCQA:'8.4', pcPriceCQAEntered:'10.5', supplierPriceLanded:'8', supplierPriceLandedEntered:'10',
      toolingCQA:'80000', toolingCQAEntered:'100000', supplierToolingCost:'79999.992', supplierToolingCostEntered:'99999.99',
      toolingPayment:'MPC', bpgAvailable:'Yes', fraAvailable:'Yes', belowCQA:'No', cqaJustification:'Raw material index',
      strategicSupplier:'', ltaAvailable:'', fotLeadTimeWeeks:12, ppapLeadTimeWeeks:null,
      amortizationTotal:'24000', amortizationTotalEntered:'30000', amortizationPcs:120000, amortizationPerPc:'0.2',
      usmcaEligible:'', annualCapacity:null, lifetimeCapacity:null});
    await view.page.evaluate(()=>{ state.isAdmin=true; goToDetail('SWAT-TEST'); });
    const detail = await view.page.locator('#app').innerText();
    assert.ok(detail.includes('€8.40 ($10.50 entered)'), detail);
    // 模具费只显示 2 位小数（件价仍可到 4 位）
    assert.ok(detail.includes('€79,999.99 ($99,999.99 entered)'), detail);
    assert.ok(detail.includes('Tooling Payment\nMPC'), detail);
    assert.ok(detail.includes('No — Raw material index'), detail);
    assert.ok(detail.includes('12 weeks from KO'), detail);
    assert.ok(detail.includes('€24,000.00 ($30,000.00 entered) into 120,000 pcs = €0.20/pc'), detail);
    assert.ok(!detail.includes('PPAP lead time'), 'empty optional fields stay hidden');
    await view.page.locator('#editCaseBtn').click();
    assert.equal(await view.page.locator('#editPnPcPriceCQA_0').inputValue(),'10.5');
    assert.equal(await view.page.locator('#editPcPriceCQA').count(),0);
    assert.equal(await view.page.locator('#editToolingPayment').inputValue(),'MPC');
    assert.equal(await view.page.locator('#editPpapLeadTimeWeeks').inputValue(),'');
    await view.page.evaluate(()=>{ state.detailEditMode=false; state.editBuffer=null; });
    await seed(view.page,{peakYearSpend:1500000});
    await view.page.evaluate(()=>goToDetail('SWAT-TEST'));
    assert.ok((await view.page.locator('#app').innerText()).includes('Not provided at registration'));
    // 多零件案例：件价 / 产量按行列成一张表，顶层没有件价
    await seed(view.page,{spendCurrency:'EUR', toolingPayment:'Lumpsum', pcPriceCQA:null, supplierPriceLanded:null,
      partNumbers:[{partNumber:'PN-A', partDescription:'A', peakYearSpend:1, lifetimeSpend:2, pcPriceCQA:'1', supplierPriceLanded:'0.9', averageVolume:1000, lifetimeVolume:null, toolingCQA:'0', supplierToolingCost:'0'},
                   {partNumber:'PN-B', partDescription:'B', peakYearSpend:1, lifetimeSpend:2, pcPriceCQA:'2', supplierPriceLanded:'2.2', averageVolume:null, lifetimeVolume:5, toolingCQA:'10', supplierToolingCost:'12'}]});
    await view.page.evaluate(()=>goToDetail('SWAT-TEST'));
    const multi = await view.page.locator('#app').innerText();
    assert.ok(multi.includes('Prices, volumes and tooling per part number'), multi);
    assert.ok(multi.includes('PN-A\t€1.00\t€0.90\t1,000 pcs\t—\t€0.00\t€0.00'), multi);
    assert.ok(multi.includes('PN-B\t€2.00\t€2.20\t—\t5 pcs\t€10.00\t€12.00'), multi);
    await view.page.locator('#editCaseBtn').click();
    assert.equal(await view.page.locator('#editPnPcPriceCQA_1').inputValue(),'2');
    assert.equal(await view.page.locator('#editPnLtVolume_1').inputValue(),'5');
    await view.context.close();
  });

  await test('BPG "No" only shows the red warning when the bundle Lifetime Spend converts to more than 3 Mio EUR', async()=>{
    // v3 Phase-36：北美同事 312,698 USD、BPG 选 No 就出红字（之前选 No 不看金额）
    const fxSettings = {basis:'OP 2026', perEur:{USD:'1.17'}, updatedAt:'Oct 28, 9:00 AM'};
    const {page, context} = await fixture({user:'user', api:async(route,path)=>{
      if(path!=='/api/bootstrap') return false;
      await route.fulfill({json:{...empty, fxSettings, currentUser:USER}});
      return true;
    }});
    await goTo(page, 'submit');
    const warning = ()=>page.locator('#bpgWarning').evaluate(el=>getComputedStyle(el).display);
    await page.locator('#fCurrency').selectOption('USD');
    await page.locator('#fBundlePeak').fill('44671');
    await page.locator('#fBundleLife').fill('312698');
    await page.locator('#qBPG').selectOption('No');
    assert.equal(await warning(), 'none');
    // 金额改到超线（3.6 Mio USD ≈ 3.08 Mio EUR）：不用重新选 BPG，红字跟着出现；改回去又消失
    await page.locator('#fBundleLife').fill('3600000');
    assert.equal(await warning(), 'block');
    await page.locator('#fBundleLife').fill('3400000');
    assert.equal(await warning(), 'none');
    // 换成 EUR：3.4 Mio EUR 超线
    await page.locator('#fCurrency').selectOption('EUR');
    assert.equal(await warning(), 'block');
    await page.locator('#qBPG').selectOption('Yes');
    assert.equal(await warning(), 'none');
    await context.close();
  });

  await test('Registration deadline follows admin settings and late registrations need an exception with a reason', async()=>{
    // 固定时间 2026-12-20（周日）12:00Z。默认规则：周一 23:59 —— 本周三 12/23 仍开放，没有例外入口
    const plain = await fixture({user:'user'});
    await goTo(plain.page, 'submit');
    assert.equal(await plain.page.locator('#fMeetingDate option').first().getAttribute('value'),'2026-12-23');
    assert.equal(await plain.page.locator('#fLateException').count(),0);
    // v3 Phase-26：截止规则收进会议日期旁的 ⓘ（悬停显示，读屏从 aria-label 读到）
    assert.ok((await plain.page.locator('label:has(~ #fMeetingDate) .info-tip').getAttribute('aria-label')).includes('Registrations close Monday 23:59 (America/New_York)'));
    await plain.context.close();

    // 管理员规则：会前 5 天 18:00 柏林时间 = 周五 12/18 18:00，已过 → 最早只能选 12/30，可申请例外登记 12/23
    let submitted, savedSettings;
    const registrationSettings = {daysBefore:5, cutoffTime:'18:00', timezone:'Europe/Berlin', updatedAt:'Dec 1, 9:00 AM'};
    // v3 Phase-22：截止已过时，普通用户与 Manager 看不到例外入口，最早只能选下周三
    for(const role of [USER, MANAGER]){
      const other = await fixture({user:'user', api:async(route,path)=>{
        if(path!=='/api/bootstrap') return false;
        await route.fulfill({json:{...empty, registrationSettings, currentUser:role}});
        return true;
      }});
      await goTo(other.page, 'submit');
      assert.equal(await other.page.locator('#fMeetingDate option').first().getAttribute('value'),'2026-12-30');
      assert.equal(await other.page.locator('#fLateException').count(),0, role.role);
      await other.context.close();
    }
    const {page, context} = await fixture({api:async(route,path)=>{
      if(path==='/api/bootstrap'){ await route.fulfill({json:{...empty, registrationSettings, currentUser:ADMIN}}); return true; }
      if(path==='/api/registration-settings'){ savedSettings = route.request().postDataJSON(); await route.fulfill({json:{ok:true, snapshot:{...empty, registrationSettings:{...savedSettings, updatedAt:'now'}}}}); return true; }
      if(path!=='/api/submissions') return false;
      submitted = route.request().postDataJSON();
      await route.fulfill({json:{subId:'SUB-LATE',snapshot:empty}});
      return true;
    }});
    await goTo(page, 'submit');
    assert.equal(await page.locator('#fMeetingDate option').first().getAttribute('value'),'2026-12-30');
    assert.ok((await page.locator('label:has(~ #fMeetingDate) .info-tip').getAttribute('aria-label')).includes('Registrations close Friday 18:00 (Europe/Berlin)'));
    for(const [id,value] of Object.entries({fExistingSwat:'SWAT-1004',pnSupplier_0:'Test supplier',pnProject_0:'MBEAL',pnPartNumber_0:'1234',pnPartDescription_0:'Test part',fBundlePeak:'10',fBundleLife:'20'})){
      await page.locator('#'+id).fill(value);
    }
    await page.locator('#fRegionIn input[value="EU"]').check();
    await page.locator('#qFamily').selectOption('No');
    await page.locator('#qECM').selectOption('No');
    await fillCommercial(page);
    await page.locator('#fLateException').check();
    assert.equal(await page.locator('#fMeetingDate option').first().getAttribute('value'),'2026-12-23');
    assert.ok((await page.locator('#fMeetingDate option').first().textContent()).includes('deadline passed'));
    assert.equal(await page.locator('#lateReasonField').evaluate(el=>getComputedStyle(el).display),'block');
    await page.locator('#fMeetingDate').selectOption('2026-12-23');
    await page.locator('#submitCaseBtn').click();
    await page.waitForFunction(()=>document.getElementById('submitBanner')?.textContent.includes('reason for the late registration'));
    assert.equal(submitted,undefined);
    await page.locator('#fLateReason').fill('Customer escalation');
    await page.locator('#submitCaseBtn').click();
    await page.waitForFunction(()=>document.getElementById('submitBanner')?.textContent.includes('SUB-LATE'));
    assert.equal(submitted.meetingDateISO,'2026-12-23');
    assert.equal(submitted.lateException,true);
    assert.equal(submitted.lateReason,'Customer escalation');

    // 审批页标出例外申请；Dashboard 管理员卡片保存规则
    await page.evaluate(()=>{ applySnapshot({submissions:[{subId:'SUB-LATE', status:'Waiting for Registration Confirmation', submitterName:'Test owner', submitterEmail:'t@example.com', presenter:'Lingqing Hu',
      submittedAt:'Dec 20, 2026 7:00 AM', partNumber:'1234', partDescription:'Test part', caseId:'SWAT-1004', region:'EU', meetingDateLabel:'Wed, Dec 23, 2026',
      lateRegistration:{reason:'Customer escalation', deadline:'Fri, Dec 18, 2026 18:00 (Europe/Berlin)'}}]}); });
    await goTo(page, 'approvals');
    const approvals = await page.locator('#app').innerText();
    assert.ok(approvals.includes('Late registration — exception requested'), approvals);
    assert.ok(approvals.includes('Customer escalation'));
    assert.ok(approvals.includes('Presenter: Lingqing Hu'), approvals);  // v3 Phase-28：上会人不是提交人时写出来
    await goTo(page, 'dashboard');
    assert.ok((await page.locator('h3:has-text("Registration Deadline") .info-tip').getAttribute('aria-label')).includes('Friday 18:00 (Europe/Berlin)'));
    await page.locator('#regDaysBefore').selectOption('1');
    await page.locator('#regCutoffTime').fill('17:30');
    await page.locator('#regTimezone').fill('');
    await page.locator('#regSave').click();
    await page.waitForFunction(()=>document.getElementById('regMsg')?.textContent.includes('Saved'));
    assert.deepEqual(savedSettings,{daysBefore:1, cutoffTime:'17:30', timezone:''});
    assert.ok((await page.locator('h3:has-text("Registration Deadline") .info-tip').getAttribute('aria-label')).includes('Tuesday 17:30 (America/New_York)'));
    await context.close();
  });

  await test('Follow-up tags are free text, categories derive from keywords, and the owner gets a function', async()=>{
    let saved;
    const {page, context} = await fixture({api:async(route,path)=>{
      if(!path.startsWith('/api/cases/')) return false;
      saved = route.request().postDataJSON();
      await route.fulfill({json:{ok:true, case:{}, snapshot:{...empty, cases:[]}}});
      return true;
    }});
    await seed(page,{meetingDecision:'APPROVED', sourcingPresentationLink:'https://example.com/deck.pptx', actionStatus:'Open',
      followUps:[{id:'FU-T1', task:'Negotiate consignment', responsible:'SP ABC', dueDate:'2027-02-18', notes:'', status:'Open', tags:['Cost'], notify:'SP ABC', notifyEmail:'sp@example.com', cc:''}]});
    await page.evaluate(()=>{ state.isAdmin=true; goToDetail('SWAT-TEST'); });
    let text = '';
    assert.deepEqual(await page.locator('tr[data-task-expand="FU-T1"] .cat-tag').allTextContents(), ['Saving']);  // 旧标签 Cost 按同义词归到 Saving
    await page.locator('[data-task-toggle="FU-T1"]').click();  // v3 Phase-40：标签在展开后的详情里
    assert.ok((await page.locator('#taskDetail_FU-T1').innerText()).includes('Tags\nCost'));
    await page.locator('#editCaseBtn').click();
    assert.equal(await page.locator('#editFuCat_0').count(), 0);  // 没有勾选框了
    assert.equal(await page.locator('#editFuTags_0').inputValue(), 'Cost');
    assert.ok((await page.locator('#editFuAuto_0').innerText()).includes('Saving'));
    await page.locator('#editFuTask_0').fill('Check PPAP samples for KW45');
    await page.locator('#editFuTags_0').fill('Cost, VAVE');
    const auto = await page.locator('#editFuAuto_0 .cat-tag').allTextContents();
    assert.deepEqual(auto, ['CQA','Timing','Saving','Further VAVE']);  // 边输入边预览，顺序按固定分类
    await page.locator('#editFuFunc_0').fill('Purchasing');
    assert.ok((await page.locator('#functionOptions option').allTextContents()).length>=3 || await page.locator('#functionOptions option').count()>=3);
    await page.locator('#saveCaseBtn').click();
    await page.waitForFunction(()=>!state.detailEditMode);
    assert.deepEqual(saved.followUps[0].tags, ['Cost','VAVE']);
    assert.equal(saved.followUps[0].ownerFunction, 'Purchasing');
    assert.equal(saved.followUps[0].task, 'Check PPAP samples for KW45');
    // Follow-ups 页：八个分类 + Uncategorized；按自动分类筛选；职能列与筛选
    await seed(page,{meetingDecision:'APPROVED', actionStatus:'Open',
      followUps:[{id:'FU-T1', task:'Negotiate consignment', responsible:'SP ABC', ownerFunction:'Purchasing', dueDate:'2027-02-18', status:'Open', tags:['Cost'], notifyEmail:'sp@example.com'},
                 {id:'FU-T2', task:'Follow up', responsible:'Q Lee', dueDate:'2027-02-18', status:'Closed', tags:[], notifyEmail:'q@example.com'}]});
    await goTo(page, 'followups');
    const options = await page.locator('#fFollowupTag option').allTextContents();
    assert.deepEqual(options, ['Category: All','CQA','Volume','Technical','Timing','Supplier strategy','BPG','Saving','Further VAVE','Uncategorized']);
    text = await page.locator('#app').innerText();
    assert.ok(text.includes('1 open task') && text.includes('SP ABC\nPurchasing'), text);
    await page.locator('#fFollowupTag').selectOption('CQA');
    assert.ok((await page.locator('#app').innerText()).includes('0 open tasks'));
    await page.locator('#fFollowupTag').selectOption('Saving');
    assert.ok((await page.locator('#app').innerText()).includes('1 open task'));
    await page.locator('#fFollowupTag').selectOption('');
    await page.locator('#fFollowupFunction').selectOption('Purchasing');
    assert.ok((await page.locator('#app').innerText()).includes('1 open task'));
    await page.locator('#fFollowupStatus').selectOption('Closed');
    text = await page.locator('#app').innerText();
    assert.ok(text.includes('0 tasks'), text);  // 职能筛选仍是 Purchasing，Closed 的那条属于 Q Lee
    await page.locator('#fFollowupFunction').selectOption('');
    text = await page.locator('#app').innerText();
    assert.ok(text.includes('1 task') && text.includes('Uncategorized'), text);
    await context.close();
  });

  await test('Multi-region cases match each region filter and count once per region', async()=>{
    const {page, context} = await fixture();
    await page.evaluate(()=>{
      const base = {partNumber:'1', partDescription:'P', weekNum:40, recommendedSupplier:'S', presenter:'O',
        cluster:'Metal', meetingDecision:'APPROVED'};
      applySnapshot({cases:[
        mkCase({...base, id:'C-1', swatId:'SWAT-1', caseNumber:1, region:'EU + NA'}),
        mkCase({...base, id:'C-2', swatId:'SWAT-2', caseNumber:2, region:'EU'}),
        mkCase({...base, id:'C-3', swatId:'SWAT-3', caseNumber:3, region:'AP'}),
      ]});
      state.view='database'; render();
    });
    const shown = async region=>{
      await page.locator('#fRegion').selectOption(region);
      return page.evaluate(()=>document.querySelector('.resultcount').textContent);
    };
    assert.deepEqual(await page.locator('#fRegion option').allTextContents(),['Region: All','AP','EU','NA']);
    assert.equal(await shown('EU'),'2 cases');
    assert.equal(await shown('NA'),'1 case');
    assert.equal(await shown('AP'),'1 case');
    await goTo(page, 'dashboard');
    const bars = await page.evaluate(()=>{
      const card=[...document.querySelectorAll('.breakdown-card')].find(el=>el.textContent.includes('by Region'));
      return {rows:[...card.querySelectorAll('.bar-row')].map(r=>r.querySelector('.blabel').textContent+'='+r.querySelector('.bar-num').textContent),
        note:(card.querySelector('h4 .info-tip')?.getAttribute('aria-label')||'').includes('counted once in each')};  // v3 Phase-26：说明收进 ⓘ
    });
    assert.deepEqual(bars.rows.sort(),['AP=1','EU=2','NA=1']);
    assert.ok(bars.note);
    await context.close();
  });

  await test('Document URLs are safe and attribute text round-trips unchanged', async()=>{
    const {page, context} = await fixture();
    await seed(page,{sourcingPresentationLink:'javascript:alert(1)',finalDocLink:'java&#x73;cript:alert(1)'});
    await page.evaluate(()=>goToDetail('SWAT-TEST'));
    assert.equal(await page.locator('#app a').count(),0);
    const url = 'https://example.test/doc?a=1&copy;=2';
    await page.evaluate(url=>{ ALL_CASES[0].sourcingPresentationLink=url; render(); },url);
    assert.equal(await page.locator('#app a').getAttribute('href'),url);
    assert.equal(await page.evaluate(()=>{
      const container=document.createElement('div');
      container.innerHTML='<input value="'+escapeAttr('&quot; <test> "')+'">';
      return container.firstChild.value;
    }),'&quot; <test> "');
    await context.close();
  });

  await test('Malformed case hash remains usable', async()=>{
    const {page,context} = await fixture({hash:'#case/%E0%A4%A'});
    assert.match(await page.locator('#scToast').textContent(),/invalid/);
    await goTo(page, 'database');
    assert.equal(new URL(page.url()).hash,'');
    await context.close();
  });

  await test('Valid reminder deep links open the case on initial load', async()=>{
    const initial=await fixture();
    const c=await seed(initial.page);
    await initial.context.close();
    const {page,context}=await fixture({hash:'#case/SWAT-TEST',api:async(route,path)=>{
      if(path!=='/api/bootstrap') return false;
      await route.fulfill({json:{...empty,cases:[c]}});
      return true;
    }});
    assert.equal(await page.evaluate(()=>state.view),'detail');
    assert.equal(await page.locator('#app h1').textContent(),'Test part');
    await page.locator('#backToDb').press('Enter');
    assert.equal(await page.evaluate(()=>state.view),'database');
    assert.equal(new URL(page.url()).hash,'');
    await context.close();
  });

  await test('Structured validation errors remain readable', async()=>{
    const {page,context} = await fixture({api:async(route,path)=>{
      if(path!=='/api/check') return false;
      await route.fulfill({status:422,json:{detail:[{loc:['body','partNumbers',0,'peakYearSpend'],msg:'Must be nonnegative'}]}});
      return true;
    }});
    const message = await page.evaluate(async()=>{
      try{ await API.post('/api/check',{}); }catch(error){ return error.detail; }
    });
    assert.equal(message,'partNumbers: 0: peakYearSpend: Must be nonnegative');
    await context.close();
  });

  await test('Admin login reveals the password field on demand; a wrong password leaves a usable error panel', async()=>{
    const {page,context} = await fixture({api:async(route,path)=>{
      if(path!=='/api/auth/login') return false;
      const body = route.request().postDataJSON();
      await route.fulfill({status:401,json:{detail: body.password ? 'Wrong email or password.' : 'Password required.'}});
      return true;
    }});
    await page.locator('#adminToggle').click();
    assert.equal(await page.locator('#adminPasswordInput').isVisible(), false);  // v3 Phase-16：默认只有邮箱
    await page.locator('#adminEmailInput').fill('admin@zf.com');
    await page.locator('#adminLoginBtn').click();
    await page.locator('#adminPasswordInput').waitFor({state:'visible'});  // 服务端说要密码 → 展开
    assert.ok((await page.locator('#adminLoginErr').textContent()).includes('Sourcing admin account'));
    await page.locator('#adminPasswordInput').fill('wrong');
    await page.locator('#adminLoginBtn').click();
    await page.locator('#adminLoginErr').waitFor({state:'visible'});
    assert.equal(await page.locator('#adminLoginErr').textContent(),'Wrong email or password.');
    assert.equal(await page.locator('#adminLoginBtn').isEnabled(),true);
    await page.locator('#adminPasswordInput').press('Escape');
    assert.equal(await page.locator('#adminLoginPanel').count(),0);
    await context.close();
  });

  await test('Cancelled login ignores the late response and revokes its token', async()=>{
    let pending, requests=0, logouts=0;
    const {page,context} = await fixture({api:async(route,path)=>{
      if(path==='/api/auth/login'){ requests++; pending=route; return true; }
      if(path==='/api/auth/logout'){ logouts++; await route.fulfill({json:{ok:true}}); return true; }
      return false;
    }});
    await page.locator('#adminToggle').click();
    await page.locator('#adminEmailInput').fill('test.user@zf.com');
    await page.locator('#adminEmailInput').press('Enter');
    await page.locator('#adminEmailInput').press('Enter');
    await page.waitForFunction(()=>API.pendingWrites===1);
    await page.locator('#adminLoginCancel').click();
    assert.equal(requests,1);
    const revoked=page.waitForResponse('**/api/auth/logout');
    await pending.fulfill({json:{ok:true, token:'cancelled-token', user:USER}});
    await revoked;
    assert.equal(logouts,1);
    assert.deepEqual(await page.evaluate(()=>[state.user, API.sessionToken()]),[null, '']);
    await context.close();
  });

  await test('Storage restrictions keep the login token in memory, and a password change keeps the submission draft', async()=>{
    const {page,context} = await fixture({before:page=>page.addInitScript(()=>{
      Storage.prototype.getItem=()=>{throw new Error('Storage blocked');};
      Storage.prototype.setItem=()=>{throw new Error('Storage blocked');};
    }),api:async(route,path)=>{
      // 改密码只有管理员有（Phase-16）：这里以管理员身份登录
      const me = {...USER, role:'admin', roleLabel:'Sourcing admin'};
      if(path==='/api/auth/login'){ await route.fulfill({json:{ok:true, token:'memory-token', user:me}}); return true; }
      if(path==='/api/auth/password'){ await route.fulfill({json:{ok:true, user:me}}); return true; }
      return false;
    }});
    await goTo(page, 'submit');
    await page.locator('#submitLoginBtn').click();  // 提交页的登录门槛打开登录面板
    await page.locator('#adminEmailInput').fill('test.user@zf.com');
    await page.locator('#adminLoginBtn').click();  // 邮箱直接登录
    await page.locator('#submitCaseBtn').waitFor();
    assert.equal(await page.evaluate(()=>API.sessionToken()),'memory-token');
    assert.deepEqual(await page.evaluate(()=>[document.getElementById('fSubmitter').value, document.getElementById('fSubmitterEmail').value, document.getElementById('fSubmitter').readOnly]),
      ['Test owner', 'test.user@zf.com', true]);  // 提交人取自账号，只读
    await page.locator('#pnSupplier_0').fill('Unsaved draft');
    await page.locator('#adminToggle').click();
    await page.locator('#toPassword').click();
    await page.locator('#curPasswordInput').fill('user-pass-123');
    await page.locator('#adminPasswordInput').fill('new-pass-456789');
    await page.locator('#adminLoginBtn').click();
    await page.waitForFunction(()=>document.getElementById('scToast')?.textContent.includes('Password changed'));
    assert.equal(await page.locator('#pnSupplier_0').inputValue(),'Unsaved draft');
    await context.close();
  });

  await test('Bootstrap clears expired login sessions', async()=>{
    let sentToken;
    const {page,context}=await fixture({before:page=>page.addInitScript(()=>localStorage.setItem('sc_session_token','expired')),
      api:async(route,path)=>{
        if(path!=='/api/bootstrap') return false;
        sentToken = route.request().headers()['x-session-token'];
        await route.fulfill({json:{...empty,currentUser:null}});
        return true;
      }});
    assert.equal(sentToken,'expired');
    assert.deepEqual(await page.evaluate(()=>[state.user, state.isAdmin, API.sessionToken()]),[null, false, '']);
    assert.equal(await page.locator('#adminToggle').textContent(),'Log in / Register');
    await context.close();
  });

  await test('Submitting needs a login; registering opens the form with the account as read-only submitter', async()=>{
    let registered;
    const newUser = {...USER, email:'new.buyer@zf-lifetec.com', name:'New Buyer'};
    const {page,context} = await fixture({api:async(route,path)=>{
      if(path!=='/api/auth/register') return false;
      registered = {body:route.request().postDataJSON(), token:route.request().headers()['x-session-token']};
      await route.fulfill({json:{ok:true, token:'new-token', user:newUser}});
      return true;
    }});
    await goTo(page, 'submit');
    assert.equal(await page.locator('#submitCaseBtn').count(),0);
    assert.ok((await page.locator('#app').innerText()).includes('Log in to submit a case'));
    assert.equal(await page.locator('[data-nav="accounts"]').count(),0);
    await page.locator('#submitRegisterBtn').click();
    assert.equal(await page.locator('#adminLoginPanel').getAttribute('data-mode'),'register');
    assert.deepEqual(await page.locator('.auth-tabs button').allTextContents(), ['Log in','Register']);  // 面板顶部登录 / 注册页签
    await page.locator('#toLogin').click();
    assert.equal(await page.locator('#adminLoginPanel').getAttribute('data-mode'),'login');
    await page.locator('#toRegister').click();
    assert.ok((await page.locator('#adminLoginPanel').innerText()).includes('@zf.com or @zf-lifetec.com'));
    assert.equal(await page.locator('#adminPasswordInput').count(),0);  // 注册不设密码
    await page.locator('#regNameInput').fill('New Buyer');
    await page.locator('#adminEmailInput').fill('New.Buyer@zf-lifetec.com');
    await page.locator('#adminLoginBtn').click();
    await page.locator('#submitCaseBtn').waitFor();
    assert.deepEqual(registered,{body:{name:'New Buyer', email:'New.Buyer@zf-lifetec.com'}, token:undefined});
    assert.equal(await page.locator('#adminLoginPanel').count(),0);
    assert.equal(await page.locator('#adminToggle').textContent(),'New Buyer · User');
    assert.equal(await page.evaluate(()=>localStorage.getItem('sc_session_token')),'new-token');
    assert.deepEqual(await page.evaluate(()=>[document.getElementById('fSubmitter').value, document.getElementById('fSubmitterEmail').value, document.getElementById('fPresenter').value]),['New Buyer','new.buyer@zf-lifetec.com','New Buyer']);
    // 普通用户没有 Accounts 页，也进不去
    assert.equal(await page.locator('[data-nav="accounts"]').count(),0);
    assert.equal(await page.evaluate(()=>{ state.view='accounts'; render(); return state.view; }),'home');
    // 登出回到登录门槛
    await page.locator('#adminToggle').click();
    const loggedOut = page.waitForRequest('**/api/auth/logout');
    await page.route('**/api/auth/logout', route=>route.fulfill({json:{ok:true}}));
    await page.locator('#adminLogoutBtn').click();
    await loggedOut;
    await goTo(page, 'submit');
    assert.equal(await page.locator('#submitLoginGate').count(),1);
    await context.close();
  });

  await test('Accounts page lets the Sourcing admin rename and change roles, disable accounts and reset a password that is shown once', async()=>{
    const calls=[];
    let users=[ADMIN, USER];
    const {page,context} = await fixture({user:'admin', api:async(route,path)=>{
      const method=route.request().method(), p=decodeURIComponent(path);
      if(p==='/api/users' && method==='GET'){ calls.push({p, token:route.request().headers()['x-session-token']}); await route.fulfill({json:{ok:true, users}}); return true; }
      if(p==='/api/users/test.user@zf.com' && method==='PUT'){
        const body=route.request().postDataJSON(); calls.push({p, body});
        users=users.map(u=>u.email==='test.user@zf.com'?{...u,...body, roleLabel:body.role==='npi_manager'?'Manager':body.role==='admin'?'Sourcing admin':u.roleLabel}:u);
        // 提升为管理员：服务端在这次响应里附临时密码（Phase-16）
        await route.fulfill({json:{ok:true, users, ...(body.role==='admin' ? {temporaryPassword:'promo-Temp-456'} : {})}}); return true;
      }
      if(p==='/api/users/test.user@zf.com/reset-password'){
        calls.push({p});
        users=users.map(u=>u.email==='test.user@zf.com'?{...u, mustChangePassword:true}:u);
        await route.fulfill({json:{ok:true, users, temporaryPassword:'tmp-Secret-123'}}); return true;
      }
      return false;
    }});
    assert.equal(await page.locator('#adminToggle').textContent(),'Sourcing Admin · Sourcing admin');
    await page.locator('[data-nav="accounts"]').click();
    const roleSelect = page.locator('[data-user-role="test.user@zf.com"]');
    await roleSelect.waitFor();
    assert.deepEqual(calls,[{p:'/api/users', token:'tok'}]);
    assert.equal(await page.locator('[data-user-role="admin@zf.com"]').isDisabled(),true);  // 自己的角色让别的管理员改
    assert.equal(await page.locator('[data-user-disable="admin@zf.com"]').count(),0);
    await roleSelect.selectOption('npi_manager');
    await page.waitForFunction(()=>document.getElementById('scToast')?.textContent.includes('Account updated'));
    assert.deepEqual(calls[1],{p:'/api/users/test.user@zf.com', body:{role:'npi_manager'}});
    assert.equal(await page.locator('[data-user-role="test.user@zf.com"]').inputValue(),'npi_manager');
    // v3 Phase-28：改名（注册时填错的名字会成为 Presenter）；清空不发请求、恢复原名
    const nameInput = page.locator('[data-user-name="test.user@zf.com"]');
    assert.equal(await nameInput.inputValue(),'Test owner');
    await nameInput.fill('   ');
    await nameInput.blur();
    await page.waitForFunction(()=>document.getElementById('scToast')?.textContent.includes('cannot be empty'));
    assert.equal(await nameInput.inputValue(),'Test owner');
    assert.equal(calls.length,2);
    await nameInput.fill(' Lingqing Hu ');
    await nameInput.blur();
    await page.waitForFunction(()=>state.accounts.find(u=>u.email==='test.user@zf.com')?.name==='Lingqing Hu');
    assert.equal(await page.locator('[data-user-name="test.user@zf.com"]').inputValue(),'Lingqing Hu');
    assert.deepEqual(calls[2],{p:'/api/users/test.user@zf.com', body:{name:'Lingqing Hu'}});
    await page.locator('[data-user-disable="test.user@zf.com"]').click();
    await page.waitForFunction(()=>document.querySelector('[data-user-disable="test.user@zf.com"]')?.textContent==='Enable');
    assert.deepEqual(calls[3],{p:'/api/users/test.user@zf.com', body:{disabled:true}});
    assert.ok((await page.locator('#app').innerText()).includes('Disabled'));
    // 非管理员没有密码，也就没有 Reset password 按钮；提升为管理员时拿到临时密码
    assert.equal(await page.locator('[data-user-reset="test.user@zf.com"]').count(),0);
    await page.locator('[data-user-role="test.user@zf.com"]').selectOption('admin');
    await page.locator('#accountsNotice').waitFor();
    assert.ok((await page.locator('#accountsNotice').innerText()).includes('promo-Temp-456'));
    await page.locator('#accountsNoticeClose').click();
    page.once('dialog', d=>d.accept());
    await page.locator('[data-user-reset="test.user@zf.com"]').click();
    await page.locator('#accountsNotice').waitFor();
    const notice = await page.locator('#accountsNotice').innerText();
    assert.ok(notice.includes('test.user@zf.com') && notice.includes('tmp-Secret-123') && notice.includes('only this once'), notice);
    assert.ok((await page.locator('#app').innerText()).includes('Temporary password'));
    await page.locator('#accountsNoticeClose').click();
    assert.equal(await page.locator('#accountsNotice').count(),0);
    // 换页再回来不再显示临时密码；登出后 Accounts 页消失
    await page.locator('[data-nav="home"]').click();
    await page.locator('[data-nav="accounts"]').click();
    assert.equal(await page.locator('#accountsNotice').count(),0);
    await context.close();
  });

  await test('A temporary password forces a password change before the page grants any rights', async()=>{
    const {page,context} = await fixture({api:async(route,path)=>{
      if(path!=='/api/bootstrap') return false;
      await route.fulfill({json:{...empty, currentUser:{...ADMIN, mustChangePassword:true}}});
      return true;
    }});
    await page.locator('#adminLoginPanel[data-mode="password"]').waitFor();
    assert.ok((await page.locator('#adminLoginPanel').innerText()).includes('reset by the Sourcing admin'));
    assert.deepEqual(await page.evaluate(()=>[state.isAdmin, state.isSysAdmin]),[false, false]);
    assert.equal(await page.locator('[data-nav="accounts"]').count(),0);
    await page.mouse.click(5,5);  // 点外面不能关掉
    assert.equal(await page.locator('#adminLoginPanel').count(),1);
    await goTo(page, 'submit');
    assert.equal(await page.locator('#submitLoginGate').count(),1);
    await context.close();
  });

  await test('Delete resets detail selection after the server removes the row', async()=>{
    const {page,context} = await fixture({api:async(route,path)=>{
      if(!path.startsWith('/api/cases/')) return false;
      await route.fulfill({json:{snapshot:empty, filesRemoved:2}});
      return true;
    }});
    // v3 Phase-27：附件随案例删除 —— 确认文案写明会删几个文件，删完提示实际删了几个
    await seed(page, {files:[{id:'F-1', name:'deck.pptx'}, {id:'F-2', name:'final.pdf'}]});
    await page.evaluate(()=>{state.isAdmin=true; API.setSessionToken('test'); goToDetail('SWAT-TEST');});
    await page.locator('[data-delete-ask]').click();
    assert.match(await page.locator('.confirm-inline').innerText(), /^Delete this case and its 2 attached files\?/);
    await page.locator('[data-delete-confirm]').click();
    await page.waitForFunction(()=>state.view==='database');
    assert.equal(await page.locator('#scToast').innerText(), 'Case SWAT-TEST deleted with 2 attached files.');
    assert.deepEqual(await page.evaluate(()=>[state.pendingDeleteId,state.selectedSwatId,state.detailEditMode]),[null,null,false]);
    assert.equal(new URL(page.url()).hash,'');
    await context.close();
  });

  // v3 Phase-17：首页的周会 Excel 导入（管理员）—— 预览、勾选、缺日期手填、按顺序导入
  await test('Weekly Excel import previews each file, asks for a missing meeting date, and imports only the ticked files', async()=>{
    const calls=[], libraryCalls=[];
    const library = [{path:'2025/KW46, 12.11.2025/KW46_SBS Sourcing Alignment Committee_MM.xlsx', name:'KW46_SBS Sourcing Alignment Committee_MM.xlsx', folder:'KW46, 12.11.2025', weekNum:46, meetingYear:2025, meetingDateISO:'2025-11-12', imported:true},
                     {path:'2026/KW37, 09.09.2026/KW37 09.09.2026_SBS Sourcing Alignment Committee_Updated Agenda 3.xlsx', name:'KW37 09.09.2026_SBS Sourcing Alignment Committee_Updated Agenda 3.xlsx', folder:'KW37, 09.09.2026', weekNum:37, meetingYear:2026, meetingDateISO:'2026-09-09', imported:false}];
    const {page,context} = await fixture({user:'admin', api:async(route,path)=>{
      if(path==='/api/import/library' && route.request().method()==='GET'){ await route.fulfill({json:{ok:true, files:library}}); return true; }
      if(path==='/api/import/library'){
        const body = route.request().postDataJSON(); libraryCalls.push(body);
        const preview = {ok:true, file:'KW37 09.09.2026_SBS Sourcing Alignment Committee_Updated Agenda 3.xlsx', weekNum:37, meetingYear:2026, meetingDateISO:'2026-09-09', meetingDateLabel:'Wed, Sep 9, 2026', cases:7, rows:9, warnings:[], replaces:0, committed:false, preview:[]};
        await route.fulfill({json: body.commit ? {...preview, committed:true, added:7, snapshot:empty} : preview}); return true;
      }
      if(path!=='/api/import/excel') return false;
      const u = new URL(route.request().url()); const name=u.searchParams.get('name'), commit=u.searchParams.get('commit')==='true', date=u.searchParams.get('meetingDate')||'';
      calls.push({name, commit, date, sourceUrl:u.searchParams.get('sourceUrl')||'', size:(route.request().postDataBuffer()||Buffer.alloc(0)).length, token:route.request().headers()['x-session-token']});
      if(name.startsWith('KW46') && !date){ await route.fulfill({status:422, json:{detail:'Cannot tell the meeting date from the file name — enter it in the import form.'}}); return true; }
      const kw = name.startsWith('KW46') ? 46 : name.startsWith('KW38') ? 38 : 39, year = kw===46 ? 2025 : 2026;
      const preview = {ok:true, file:name, weekNum:kw, meetingYear:year, meetingDateISO:`${year}-01-01`, meetingDateLabel:`Wed, KW${kw}`, cases:kw===38?2:3, rows:5,
        warnings: kw===39 ? ['Row 8 peak spend: cannot read amount \'4 < 750k\''] : [], replaces: kw===39 ? 3 : 0, committed:false, preview:[]};
      if(!commit){ await route.fulfill({json:preview}); return true; }
      await route.fulfill({json:{...preview, committed:true, added:preview.cases, snapshot:empty}}); return true;
    }});
    assert.equal(await page.locator('#dropzone').count(),1);
    // 随程序发布的历史文件：下拉框列出、已导入的标 (imported)、"Add all not yet imported" 只算没导过的
    await page.locator('#importLibrarySelect').waitFor();
    assert.deepEqual(await page.locator('#importLibrarySelect option').allTextContents(), ['Choose a stored weekly file…',
      '2025-KW46 · KW46_SBS Sourcing Alignment Committee_MM.xlsx (imported)', '2026-KW37 · KW37 09.09.2026_SBS Sourcing Alignment Committee_Updated Agenda 3.xlsx']);
    assert.equal(await page.locator('#importLibraryAddAll').textContent(),'Add all not yet imported (1)');
    await page.locator('#importLibrarySelect').selectOption(library[1].path);
    await page.locator('#importLibraryAdd').click();
    await page.waitForFunction(()=>state.importQueue.length===1 && state.importQueue[0].status==='ready');
    assert.deepEqual(libraryCalls, [{path:library[1].path, commit:false, sourceUrl:''}]);
    assert.ok((await page.locator('#importQueue').innerText()).includes('2026-KW37 · Wed, Sep 9, 2026 · 7 cases, 9 part rows'));
    assert.equal(await page.locator('#importLibraryAddAll').isDisabled(), true);  // 已在列表里
    await page.locator('#importRunBtn').click();
    await page.waitForFunction(()=>!!state.importResults);
    assert.deepEqual(libraryCalls[1], {path:library[1].path, commit:true, sourceUrl:''});
    assert.ok((await page.locator('#app').innerText()).includes('7 cases imported from 1 file'));
    assert.ok((await page.locator('#importLibrarySelect option').allTextContents())[2].endsWith('(imported)'));  // 导完标记
    await page.locator('#importClearBtn').click();
    const xlsx = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    await page.locator('#importFiles').setInputFiles([
      {name:'KW39 23.09.2026_SBS Sourcing Alignment Committee_MM.xlsx', mimeType:xlsx, buffer:Buffer.alloc(300, 1)},
      {name:'KW46_SBS Sourcing Alignment Committee_MM.xlsx', mimeType:xlsx, buffer:Buffer.alloc(200, 2)},
      {name:'KW38 16.09.2026_SBS Sourcing Alignment Committee_Meeting Minutes.xlsx', mimeType:xlsx, buffer:Buffer.alloc(100, 3)},
      {name:'notes.txt', mimeType:'text/plain', buffer:Buffer.from('x')},
    ]);
    await page.waitForFunction(()=>state.importQueue.length===3 && state.importQueue.every(e=>e.status!=='checking'));
    assert.deepEqual(calls.map(c=>[c.name.slice(0,4), c.commit, c.size, c.token]), [['KW39',false,300,'tok'],['KW46',false,200,'tok'],['KW38',false,100,'tok']]);
    const list = await page.locator('#importQueue').innerText();
    assert.ok(list.includes('2026-KW39') && list.includes('3 cases, 5 part rows') && list.includes('replaces 3 imported before') && list.includes('1 note'), list);
    assert.ok(list.includes('Cannot tell the meeting date'), list);
    assert.equal(await page.locator('[data-import-date="1"]').count(),1);  // 缺日期的文件出现日期框
    assert.equal(await page.locator('#importRunBtn').textContent(),'Import 2 selected files');
    await page.locator('[data-import-warn="0"]').click();
    assert.ok((await page.locator('#importQueue').innerText()).includes("cannot read amount"));
    await page.locator('[data-import-date="1"]').fill('2025-11-12');
    await page.locator('[data-import-date="1"]').dispatchEvent('change');
    await page.waitForFunction(()=>state.importQueue[1].status==='ready');
    assert.equal(await page.locator('#importRunBtn').textContent(),'Import 3 selected files');
    await page.locator('[data-import-include="2"]').uncheck();  // 不导 KW38
    await page.locator('#importSourceUrl').fill('https://sp.example.com/KW39');
    await page.locator('#importRunBtn').click();
    await page.waitForFunction(()=>!!state.importResults);
    const commits = calls.filter(c=>c.commit);
    assert.deepEqual(commits.map(c=>[c.name.slice(0,4), c.date, c.sourceUrl]), [['KW39','','https://sp.example.com/KW39'],['KW46','2025-11-12','https://sp.example.com/KW39']]);
    const text = await page.locator('#app').innerText();
    assert.ok(text.includes('6 cases imported from 2 files, 3 earlier imports replaced'), text);
    assert.ok(text.includes('✓ Imported 3 cases (replaced 3)'), text);
    await context.close();
    // 普通用户与 Manager 看不到导入卡片
    for(const user of ['user','manager']){
      const other = await fixture({user});
      assert.equal(await other.page.locator('#dropzone').count(),0);
      await other.context.close();
    }
  });

  await test('Exports block formulas hidden behind whitespace and preserve numeric cells', async()=>{
    const {page,context} = await fixture();
    assert.deepEqual(await page.evaluate(()=>[
      formulaGuard('=SUM(A1)'),formulaGuard('  =SUM(A1)'),formulaGuard('\n=SUM(A1)'),
      formulaGuard('\t12'),formulaGuard(-123),formulaGuard('normal')
    ]),["'=SUM(A1)","'  =SUM(A1)","'\n=SUM(A1)","'\t12",'-123','normal']);
    await goTo(page, 'dashboard');
    await page.locator('[data-period="week"]').click();
    assert.doesNotMatch(await page.locator('#app').textContent(),/undefined|Invalid Date|NaN/);
    await context.close();
  });

  await test('Agenda and Minutes buttons download the server-made .xlsx for the selected week', async()=>{
    const requested = [];
    const {page,context} = await fixture({api:async(route,path)=>{
      if(!path.startsWith('/api/exports/')) return false;
      const url = new URL(route.request().url());
      requested.push(path+'?week='+url.searchParams.get('week'));
      if(path.endsWith('/minutes')){ await route.fulfill({status:422, json:{detail:'week: Input should be greater than or equal to 1'}}); return true; }
      await route.fulfill({status:200, headers:{'content-disposition':'attachment; filename="KW40 30.09.2026_SBS Sourcing Alignment Committee_Agenda.xlsx"'},
        contentType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', body:Buffer.from('PK-fake')});
      return true;
    }});
    await seed(page,{weekNum:40});
    await page.evaluate(()=>{ window.__saved = []; saveBlobFile = async (blob, filename)=>{ window.__saved.push({filename, type:blob.type, size:blob.size}); }; });
    await goTo(page, 'dashboard');
    await page.locator('[data-period="week"]').click();
    await page.locator('#dashAgendaBtn').click();
    await page.waitForFunction(()=>window.__saved.length===1);
    assert.deepEqual(requested,['/api/exports/agenda?week=40']);
    assert.deepEqual(await page.evaluate(()=>window.__saved),[{filename:'KW40 30.09.2026_SBS Sourcing Alignment Committee_Agenda.xlsx', type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', size:7}]);
    assert.equal(await page.locator('#dashAgendaBtn').isEnabled(), true);
    // 服务端报错 → toast，按钮可再点
    await page.locator('#dashMinutesBtn').click();
    await page.waitForFunction(()=>document.getElementById('scToast')?.textContent.includes('Export failed'));
    assert.equal(requested[1],'/api/exports/minutes?week=40');
    assert.equal(await page.locator('#dashMinutesBtn').isEnabled(), true);
    await context.close();
  });

  await test('Database page exports Agenda and Minutes for the filtered cases via POST', async()=>{
    const posted = [];
    const {page,context} = await fixture({api:async(route,path)=>{
      if(!path.startsWith('/api/exports/')) return false;
      posted.push({path, method: route.request().method(), body: route.request().postDataJSON()});
      await route.fulfill({status:200, headers:{'content-disposition':'attachment; filename="KW40 30.09.2026_SBS Sourcing Alignment Committee_MM.xlsx"'},
        contentType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', body:Buffer.from('PK-fake')});
      return true;
    }});
    await page.evaluate(()=>{
      applySnapshot({cases:[mkCase({id:'C-A', swatId:'SWAT-A', partNumber:'1', partDescription:'A', weekNum:40, caseNumber:1, region:'EU', meetingDecision:'PENDING'}),
                           mkCase({id:'C-B', swatId:'SWAT-B', partNumber:'2', partDescription:'B', weekNum:40, caseNumber:2, region:'NA', meetingDecision:'APPROVED'})]});
      window.__saved = []; saveBlobFile = async (blob, filename)=>{ window.__saved.push({filename}); };
    });
    await goTo(page, 'database');
    await page.locator('#fRegion').selectOption('NA');
    await page.locator('#dbMinutesBtn').click();
    await page.waitForFunction(()=>window.__saved.length===1);
    assert.deepEqual(posted,[{path:'/api/exports/minutes', method:'POST', body:{ids:['C-B']}}]);
    assert.deepEqual(await page.evaluate(()=>window.__saved),[{filename:'KW40 30.09.2026_SBS Sourcing Alignment Committee_MM.xlsx'}]);
    await page.locator('#fRegion').selectOption('');
    await page.locator('#dbAgendaBtn').click();
    await page.waitForFunction(()=>window.__saved.length===2);
    assert.deepEqual(posted[1],{path:'/api/exports/agenda', method:'POST', body:{ids:['C-A','C-B']}});  // 表的顺序：同周同级按地区 EU 在 NA 前（Phase-28）
    await context.close();
  });

  await test('Follow-up feedback: a logged-in user reports closure with an Outlook mail attached, managers see it awaiting approval', async()=>{
    const task = {id:'FU-R1', task:'Send BP', responsible:'SP ABC', dueDate:'2027-02-18', status:'Open', tags:['BPG'], notifyEmail:'sp@example.com'};
    const fb = {id:'FB-1', when:'Sep 28, 9:00 AM', by:'Test owner', byEmail:'test.user@zf.com', text:'BP 50K negotiated, committed for 2026', files:[], status:'pending', notify:{to:'admin@zf.com', result:'sent'}, decision:null};
    const posted=[], uploads=[];
    const withFeedback = extra => [ (()=>{ const c = JSON.parse(JSON.stringify(seedCase)); c.followUps[0].feedback=[{...fb, ...extra}]; return c; })() ];
    let seedCase;
    const {page,context} = await fixture({user:'user', api:async(route,path)=>{
      if(path==='/api/tasks/FU-R1/feedback' && route.request().method()==='POST'){
        posted.push(route.request().postDataJSON());
        await route.fulfill({json:{ok:true, feedback:fb, snapshot:{...empty, cases:withFeedback({})}}}); return true;
      }
      if(path==='/api/tasks/FU-R1/feedback/FB-1/files'){
        const req=route.request();
        uploads.push({name:new URL(req.url()).searchParams.get('name'), token:req.headers()['x-session-token']});
        const file={id:'F-9', name:'closure.msg', size:512, uploadedBy:'Test owner', uploadedAt:'Sep 28, 9:01 AM', store:'local'};
        await route.fulfill({json:{ok:true, file, snapshot:{...empty, cases:withFeedback({files:[file]})}}}); return true;
      }
      return false;
    }});
    seedCase = await seed(page,{meetingDecision:'APPROVED', actionStatus:'Open', followUps:[task]});
    await goTo(page, 'followups');
    await page.locator('[data-feedback-toggle="FU-R1"]').click();
    assert.ok((await page.locator('.fb-section').innerText()).includes('No feedback yet'));
    await page.locator('[data-feedback-open="FU-R1"]').click();
    await page.locator('[data-feedback-send="FU-R1"]').click();
    assert.equal(await page.locator('#fbErr_FU-R1').textContent(),'Describe what was done before submitting the feedback.');
    await page.locator('#fbText_FU-R1').fill('BP 50K negotiated, committed for 2026');
    await page.locator('#fbFiles_FU-R1').setInputFiles([{name:'tool.exe', mimeType:'application/octet-stream', buffer:Buffer.from('x')}]);
    await page.locator('[data-feedback-send="FU-R1"]').click();
    assert.match(await page.locator('#fbErr_FU-R1').textContent(), /tool\.exe: only PowerPoint, PDF, Excel, Word or Outlook email/);
    assert.equal(posted.length,0);
    await page.locator('#fbFiles_FU-R1').setInputFiles([{name:'closure.msg', mimeType:'application/vnd.ms-outlook', buffer:Buffer.alloc(512, 1)}]);
    await page.locator('[data-feedback-send="FU-R1"]').click();
    await page.waitForFunction(()=>document.getElementById('scToast')?.textContent.includes('notified by email'));
    assert.deepEqual(posted,[{text:'BP 50K negotiated, committed for 2026'}]);
    assert.deepEqual(uploads,[{name:'closure.msg', token:'tok'}]);
    // 提交后：条目待审、附件可下载、按钮显示待审数；普通用户没有审批按钮
    await page.locator('[data-feedback-entry="FB-1"]').waitFor();
    const entry = await page.locator('[data-feedback-entry="FB-1"]').innerText();
    assert.ok(entry.includes('Awaiting approval') && entry.includes('BP 50K negotiated') && entry.includes('Approvers notified (admin@zf.com): sent'), entry);
    assert.equal(await page.locator('[data-feedback-entry="FB-1"] .file-list a').getAttribute('href'),'/api/files/F-9');
    assert.equal(await page.locator('[data-feedback-toggle="FU-R1"]').textContent(),'Hide feedback');
    assert.ok((await page.locator('.resultcount').innerText()).includes('1 feedback to approve'));
    assert.equal(await page.locator('[data-decision-open]').count(),0);
    await context.close();
    // 未登录：能看历史，不能汇报
    const viewer = await fixture();
    await seed(viewer.page,{meetingDecision:'APPROVED', actionStatus:'Open', followUps:[{...task, feedback:[fb]}]});
    await goTo(viewer.page, 'followups');
    await viewer.page.locator('[data-feedback-toggle="FU-R1"]').click();
    assert.ok((await viewer.page.locator('.fb-section').innerText()).includes('Log in to report progress'));
    assert.equal(await viewer.page.locator('[data-feedback-open]').count(),0);
    await viewer.context.close();
  });

  await test('Follow-up feedback: the Manager rejects with a remark or approves the last open task with the final document link', async()=>{
    const task = {id:'FU-R1', task:'Send BP', responsible:'SP ABC', dueDate:'2027-02-18', status:'Open', tags:['BPG'], notifyEmail:'sp@example.com'};
    const fb = {id:'FB-1', when:'Sep 28, 9:00 AM', by:'Test owner', byEmail:'test.user@zf.com', text:'BP 50K negotiated', files:[], status:'pending', notify:{to:'npi@zf.com', result:'skipped'}, decision:null};
    const decisions=[];
    const {page,context} = await fixture({user:'manager', api:async(route,path)=>{
      if(path!=='/api/tasks/FU-R1/feedback/FB-1/decision') return false;
      const body = route.request().postDataJSON(); decisions.push(body);
      const c = JSON.parse(JSON.stringify(seedCase));
      const decided = {...fb, status:body.decision, decision:{when:'Sep 28, 10:00 AM', by:'NPI Person', byEmail:'npi@zf.com', remark:body.remark, notify:{to:'sp@example.com', cc:'test.user@zf.com', result:'skipped'}}};
      if(body.decision==='approved'){ c.followUps[0]={...task, status:'Closed', closure:{when:'Sep 28, 10:00 AM', by:'NPI Person', feedbackId:'FB-1'}, feedback:[decided]}; c.actionStatus='Closed'; c.finalDocLink=body.finalDocLink; }
      else c.followUps[0]={...task, feedback:[decided]};
      await route.fulfill({json:{ok:true, feedback:decided, case:c, snapshot:{...empty, cases:[c]}}});
      return true;
    }});
    const seedCase = await seed(page,{meetingDecision:'APPROVED', actionStatus:'Open', finalDocLink:'', followUps:[{...task, feedback:[fb]}]});
    await page.evaluate(()=>goToDetail('SWAT-TEST'));
    await page.locator('tr[data-task-expand="FU-R1"] .task-title').click();  // v3 Phase-40：反馈区在展开后的行里
    await page.locator('[data-decision-open="FB-1"]').click();
    assert.equal(await page.locator('#fbFinal_FB-1').count(),1);  // 最后一条开放待办：要最终文件链接
    await page.locator('[data-decision-send="FB-1"][data-decision="rejected"]').click();
    assert.match(await page.locator('#fbDecErr_FB-1').textContent(), /Add a remark/);
    assert.equal(decisions.length,0);
    await page.locator('#fbRemark_FB-1').fill('Negotiate another 0.02 EUR/pc');
    await page.locator('[data-decision-send="FB-1"][data-decision="rejected"]').click();
    await page.waitForFunction(()=>document.getElementById('scToast')?.textContent.includes('Feedback rejected'));
    assert.deepEqual(decisions,[{decision:'rejected', remark:'Negotiate another 0.02 EUR/pc', finalDocLink:''}]);
    let entry = await page.locator('[data-feedback-entry="FB-1"]').innerText();
    assert.ok(entry.includes('Rejected') && entry.includes('Not accepted by NPI Person') && entry.includes('Negotiate another 0.02 EUR/pc') && entry.includes('cc test.user@zf.com'), entry);
    assert.equal(await page.locator('[data-decision-open]').count(),0);
    assert.equal(await page.locator('[data-feedback-open="FU-R1"]').count(),1);  // 待办仍开放，经理也能再汇报
    // 再来一条待审的 → approve 带最终链接
    await seed(page,{meetingDecision:'APPROVED', actionStatus:'Open', finalDocLink:'', followUps:[{...task, feedback:[fb]}]});
    await page.evaluate(()=>goToDetail('SWAT-TEST'));
    await page.locator('[data-decision-open="FB-1"]').click();
    await page.locator('#fbFinal_FB-1').fill('https://zf.sharepoint.com/final.pptx');
    await page.locator('[data-decision-send="FB-1"][data-decision="approved"]').click();
    await page.waitForFunction(()=>document.getElementById('scToast')?.textContent.includes('Feedback approved'));
    assert.deepEqual(decisions[1],{decision:'approved', remark:'', finalDocLink:'https://zf.sharepoint.com/final.pptx'});
    const section = await page.locator('.fb-section').innerText();
    assert.ok(section.includes('Closed by NPI Person') && section.includes('Approved') && !section.includes('Report progress'), section);
    assert.ok((await page.locator('#app').innerText()).includes('Closed'));
    await context.close();
  });

  // v3 Phase-15（领导 2026-09-29）：金额按 bundle 一个数、必填；项目 / 类型 / 供应商按零件行
  await test('Bundle spend is entered once per registration and project, type and supplier per part number row', async()=>{
    let submitted;
    const {page, context} = await fixture({user:'user', api:async(route,path)=>{
      if(path!=='/api/submissions') return false;
      submitted = route.request().postDataJSON();
      await route.fulfill({json:{subId:'SUB-B',snapshot:empty}});
      return true;
    }});
    await goTo(page, 'submit');
    assert.equal(await page.locator('#pnPeak_0, #pnLife_0, #fProjectIn, #fSupplierIn, #fSourcingType').count(), 0);
    await page.locator('#addPartNumberBtn').click();
    for(const [id,value] of Object.entries({fExistingSwat:'SWAT-1500', pnPartNumber_0:'PN1', pnPartDescription_0:'Spool', pnProject_0:'MBEAL', pnSupplier_0:'Supplier A',
      pnPartNumber_1:'PN2', pnPartDescription_1:'Cover', pnProject_1:'ACR8', pnSupplier_1:'Supplier B',
      pnPcPriceCQA_1:'0.5', pnSupplierPriceLanded_1:'0.4', pnToolingCQA_1:'0', pnSupplierToolingCost_1:'0'})){
      await page.locator('#'+id).fill(value);
    }
    await page.locator('#pnSourcingType_1').selectOption('GCS');
    await page.locator('#fRegionIn input[value="EU"]').check();
    await page.locator('#qFamily').selectOption('No');
    await page.locator('#qECM').selectOption('No');
    await fillCommercial(page);
    // 没填 bundle 金额 → 拦截；填了以后预览与 BPG 提示按 bundle 金额
    await page.locator('#submitCaseBtn').click();
    await page.waitForFunction(()=>document.getElementById('submitBanner')?.textContent.includes('bundle Peak Year Spend and Lifetime Spend'));
    assert.equal(submitted,undefined);
    await page.locator('#fBundlePeak').fill('578000');
    await page.locator('#fBundleLife').fill('3500000');
    assert.equal(await page.locator('#totalLifetimeDisplay').textContent(),'€3,500,000');
    assert.equal(await page.locator('#totalLifetimeEur').textContent(),'€3,500,000');
    assert.equal(await page.locator('#bundleEurRate').textContent(),'');
    assert.ok(await page.locator('#bpgHint.missing').count(), 'BPG hint follows the bundle lifetime spend');
    await page.locator('#qBPG').selectOption('Yes');
    await page.locator('#submitCaseBtn').click();
    await page.waitForFunction(()=>document.getElementById('submitBanner')?.textContent.includes('SUB-B'));
    assert.equal(submitted.peakYearSpend,578000);
    assert.equal(submitted.lifetimeSpend,3500000);
    assert.deepEqual(submitted.partNumbers.map(r=>[r.partNumber, r.project, r.sourcingType, r.recommendedSupplier]),
      [['PN1','MBEAL','New','Supplier A'], ['PN2','ACR8','GCS','Supplier B']]);
    assert.ok(submitted.partNumbers.every(r=>!('peakYearSpend' in r) && !('lifetimeSpend' in r)));
    assert.ok(!('project' in submitted) && !('recommendedSupplier' in submitted) && !('sourcingType' in submitted));
    await context.close();

    // 案例详情：零件行表带项目 / 类型 / 供应商，金额只显示 bundle；编辑页按行改供应商、改 bundle 金额
    let saved;
    const view = await fixture({api:async(route,path)=>{
      if(path==='/api/bootstrap'){ await route.fulfill({json:{...empty, currentUser:ADMIN}}); return true; }
      if(path==='/api/cases/C-TEST' && route.request().method()==='PUT'){ saved = route.request().postDataJSON(); await route.fulfill({json:{ok:true, case:{}, snapshot:empty}}); return true; }
      return false;
    }});
    await seed(view.page,{partNumbers:[{partNumber:'PN1', partDescription:'Spool', project:'MBEAL', sourcingType:'New', recommendedSupplier:'Supplier A'},
        {partNumber:'PN2', partDescription:'Cover', project:'ACR8', sourcingType:'GCS', recommendedSupplier:'Supplier B'}],
      project:'MBEAL, ACR8', sourcingType:'New, GCS', recommendedSupplier:'Supplier A, Supplier B', peakYearSpend:578000, lifetimeSpend:3500000, spendCurrency:'EUR',
      files:[{id:'F-9', name:'2026.09.30 MBEAL+ACR8 Spool PN1+1, Supplier A+Supplier B.pptx', originalName:'final v3.pptx', size:2048, uploadedBy:'Test owner', uploadedAt:'Sep 30, 9:00 AM', store:'local'}]});
    await view.page.evaluate(()=>goToDetail('SWAT-TEST'));
    const detail = await view.page.locator('#app').innerText();
    assert.ok(detail.includes('Bundle Peak Year Spend: €578,000') && detail.includes('Bundle Lifetime Spend: €3,500,000'), detail);
    assert.ok(detail.includes('Supplier A, Supplier B') && detail.includes('GCS'), detail);
    assert.ok(detail.includes('uploaded as final v3.pptx'), detail);  // 系统改过名的文件显示原文件名
    await view.page.locator('#editCaseBtn').click();
    assert.equal(await view.page.locator('#editPnPeak_0, #editProject, #editSupplier, #editSourcingType').count(), 0);
    assert.equal(await view.page.locator('#editPnSupplier_1').inputValue(),'Supplier B');
    await view.page.locator('#editPnSupplier_1').fill('Supplier A');
    await view.page.locator('#editPnSourcingType_1').selectOption('C/O');
    await view.page.locator('#editBundleLife').fill('3600000');
    await view.page.locator('#saveCaseBtn').click();
    await view.page.waitForFunction(()=>document.getElementById('scToast')?.textContent.includes('Case saved') || !document.getElementById('saveCaseBtn'));
    assert.equal(saved.lifetimeSpend,3600000);
    assert.equal(saved.peakYearSpend,578000);
    assert.deepEqual(saved.partNumbers.map(r=>[r.partNumber, r.project, r.sourcingType, r.recommendedSupplier]),
      [['PN1','MBEAL','New','Supplier A'], ['PN2','ACR8','C/O','Supplier A']]);
    await view.context.close();
  });

  await test('Manual reminders are offered to Managers and admins only', async()=>{
    const {page,context} = await fixture();
    await seed(page,{meetingDecision:'APPROVED', actionStatus:'Open',
      followUps:[{id:'FU-R1', task:'Send BP', responsible:'SP ABC', dueDate:'2027-02-18', status:'Open', tags:['BPG'], notifyEmail:'sp@example.com'}]});
    await goTo(page, 'followups');
    assert.equal(await page.locator('[data-remind-open]').count(), 0);
    assert.ok((await page.locator('#app').innerText()).includes('Send reminder: Manager'));
    await page.evaluate(()=>{ applySnapshot({currentUser:{email:'npi@zf.com', name:'NPI Person', role:'npi_manager', roleLabel:'Manager'}}); render(); });
    assert.equal(await page.locator('[data-remind-open="FU-R1"]').count(), 1);
    await context.close();
  });

  await test('CSV downloads retain UTF-8 BOM and neutralize formula cells', async()=>{
    const {page,context}=await fixture();
    await seed(page,{recommendedSupplier:'  =SUM(A1)',partDescription:'零件'});
    const downloaded=page.waitForEvent('download');
    await page.evaluate(()=>downloadCasesCsv(ALL_CASES,'test.csv'));
    const download=await downloaded;
    const data=await readFile(await download.path());
    assert.deepEqual([...data.subarray(0,3)],[0xef,0xbb,0xbf]);
    assert.match(data.toString('utf8'),/零件/);
    assert.match(data.toString('utf8'),/"'  =SUM\(A1\)"/);
    await context.close();
  });

  await test('Hourly refresh preserves dirty forms and ignores snapshots overtaken by writes', async()=>{
    let bootstrapCalls=0, pending;
    const {page,context} = await fixture({before:page=>page.addInitScript(()=>{
      const original=window.setInterval;
      window.setInterval=(callback,delay,...args)=>{
        if(delay===3600000){window.testRefresh=callback; return 1;}
        return original(callback,delay,...args);
      };
    }),api:async(route,path)=>{
      if(path==='/api/bootstrap'){
        bootstrapCalls++;
        if(bootstrapCalls===1) await route.fulfill({json:{...empty, currentUser:USER}}); else pending=route;
        return true;
      }
      if(path==='/api/check'){ await route.fulfill({json:{ok:true}}); return true; }
      return false;
    }});
    await goTo(page, 'submit');
    await page.locator('#pnSupplier_0').fill('Keep this');
    await page.evaluate(()=>window.testRefresh());
    assert.equal(bootstrapCalls,1);
    assert.equal(await page.locator('#pnSupplier_0').inputValue(),'Keep this');
    await goTo(page, 'database');
    const requested=page.waitForRequest('**/api/bootstrap');
    await page.evaluate(()=>{window.refreshDone=window.testRefresh();});
    await requested;
    await page.evaluate(async()=>{await API.post('/api/check',{}); ALL_CASES=[mkCase({swatId:'NEW-WRITE'})];});
    await pending.fulfill({json:empty});
    await page.evaluate(()=>window.refreshDone);
    assert.equal(await page.evaluate(()=>ALL_CASES[0]?.swatId),'NEW-WRITE');
    await context.close();
  });
  for(const [name,viewport] of [['desktop',{width:1440,height:900}],['mobile',{width:390,height:844}]]){
    await test('All seven pages render and navigate at '+name+' viewport',async()=>{
      const {page,context}=await fixture({user:'admin', api:async(route,path)=>{
        if(path!=='/api/users') return false;
        await route.fulfill({json:{ok:true, users:[ADMIN, MANAGER, USER]}});
        return true;
      }});
      await page.setViewportSize(viewport);
      await page.evaluate(()=>{applySnapshot({cases:HAND_CASES}); render();});
      for(const view of ['home','submit','approvals','database','dashboard','followups','accounts']){
        if(view==='home' || view==='accounts') await page.locator(`[data-nav="${view}"]`).click(); else await goTo(page, view);
        assert.equal(await page.evaluate(()=>state.view),view);
        assert.equal(await page.locator('#app h1').isVisible(),true);
        assert.doesNotMatch(await page.locator('#app').textContent(),/\[object Object\]|undefined|Invalid Date|NaN/);
        if(process.env.FRONTEND_ARTIFACT_DIR && (view==='home' || view==='submit')){
          await mkdir(process.env.FRONTEND_ARTIFACT_DIR,{recursive:true});
          await page.screenshot({path:join(process.env.FRONTEND_ARTIFACT_DIR,`${name}-${view}.png`),fullPage:true});
        }
      }
      await context.close();
    });
  }
  // ===== v3 Phase-18：领导第三轮反馈 =====
  await test('Week labels, week filters and sorting are year-aware; the home page has no example chips', async()=>{
    const {page, context} = await fixture();
    assert.equal(await page.locator('.qs-chip').count(), 0);
    await page.evaluate(()=>{
      const base = {partNumber:'1', partDescription:'P', recommendedSupplier:'S', presenter:'O', cluster:'Metal', meetingDecision:'APPROVED'};
      applySnapshot({cases:[
        mkCase({...base, id:'C-1', swatId:'SWAT-A', weekNum:51, caseNumber:1, meetingYear:2025, meetingDateISO:'2025-12-17', meetingDateLabel:'Wed, Dec 17, 2025', recommendedSupplier:'Zeta', peakYearSpend:300}),
        mkCase({...base, id:'C-2', swatId:'SWAT-B', weekNum:51, caseNumber:2, meetingYear:2026, meetingDateISO:'2026-12-16', meetingDateLabel:'Wed, Dec 16, 2026', recommendedSupplier:'Alpha', peakYearSpend:100, commodity:'CA Casting', commodityRaw:'CA04'}),
        mkCase({...base, id:'C-3', swatId:'SWAT-C', weekNum:40, caseNumber:3, meetingYear:2026, meetingDateISO:'2026-09-30', meetingDateLabel:'Wed, Sep 30, 2026', recommendedSupplier:'Mid', peakYearSpend:200}),
      ]});
      state.view='database'; render();
    });
    const col = async n => page.evaluate(n=>[...document.querySelectorAll('tbody tr')].map(r=>r.children[n].textContent.trim()), n);
    assert.deepEqual(await col(0), ['2026-KW51','2026-KW40','2025-KW51']);  // 默认按年+周倒序，2025 的 KW51 不再冒充 2026
    assert.deepEqual(await page.locator('#fYear option').allTextContents(), ['Year: All','2025','2026']);
    assert.deepEqual(await page.locator('#fWeekFrom option').allTextContents(), ['From week','2025-KW51','2026-KW40','2026-KW51']);
    await page.locator('#fYear').selectOption('2025');
    assert.deepEqual(await col(0), ['2025-KW51']);
    assert.deepEqual(await page.locator('#fWeekFrom option').allTextContents(), ['From week','2025-KW51']);
    await page.locator('#fYear').selectOption('');
    // v3 Phase-25：只选 From week 就只看这一周（To 自动跟上），之后的周不混进来；再选更晚的 To 才是范围
    await page.locator('#fWeekFrom').selectOption('202640');
    assert.equal(await page.locator('#fWeekTo').inputValue(), '202640');
    assert.deepEqual(await col(0), ['2026-KW40']);
    await page.locator('#fWeekTo').selectOption('202651');
    assert.deepEqual(await col(0), ['2026-KW51','2026-KW40']);
    await page.locator('#clearFilters').click();
    // 表头排序：供应商升序 → 再点降序；金额；周
    await page.locator('th[data-sort="supplier"]').click();
    assert.deepEqual(await col(7), ['Alpha','Mid','Zeta']);
    await page.locator('th[data-sort="supplier"]').click();
    assert.deepEqual(await col(7), ['Zeta','Mid','Alpha']);
    await page.locator('th[data-sort="spend"]').click();
    assert.deepEqual(await col(3), ['SWAT-A','SWAT-C','SWAT-B']);  // 金额默认降序
    await page.locator('th[data-sort="week"]').click();
    assert.deepEqual(await col(0), ['2026-KW51','2026-KW40','2025-KW51']);
    await page.locator('th[data-sort="week"]').click();
    assert.deepEqual(await col(0), ['2025-KW51','2026-KW40','2026-KW51']);
    assert.ok((await page.locator('th[data-sort="week"]').innerText()).includes('▲'));
    // Commodity 筛选与单元格副标题；搜索命中周标签
    assert.deepEqual(await page.locator('#fCommodity option').allTextContents(), ['Commodity: All','CA Casting']);
    await page.locator('#fCommodity').selectOption('CA Casting');
    assert.deepEqual(await col(3), ['SWAT-B']);
    assert.ok((await col(6))[0].includes('CA Casting'));
    await page.locator('#clearFilters').click();
    await page.locator('#dbSearch').fill('2025-KW51');
    assert.deepEqual(await col(3), ['SWAT-A']);
    await page.locator('#dbSearch').fill('');
    // 详情页与时间线也带年份；Commodity 显示原文
    await page.locator('tr[data-swat="SWAT-B"]').click();
    const text = await page.locator('#app').innerText();
    assert.ok(text.includes('2026-KW51 · Wed, Dec 16, 2026') && text.includes('Commodity\nCA Casting (Excel: CA04)'), text);
    await context.close();
  });

  await test('Top navigation groups pages into Case Workflow and Data with a sidebar; section notes open on hover', async()=>{
    const {page, context} = await fixture({user:'admin'});
    await page.setViewportSize({width:1500, height:900});
    const top = ()=>page.locator('#navtabs button').allTextContents();
    const side = ()=>page.locator('#sidenav button .sn-label').allTextContents();
    assert.deepEqual(await top(), ['Home','Case Workflow','Data','Accounts']);
    assert.equal(await page.locator('#sidenav').isVisible(), false);  // 首页没有侧边栏
    await page.locator('[data-nav-group="workflow"]').click();
    assert.equal(await page.evaluate(()=>state.view), 'submit');
    assert.deepEqual(await side(), ['Submit Case','Approval','Follow-ups']);
    assert.equal(await page.locator('#sidenav [aria-current="page"] .sn-label').textContent(), 'Submit Case');
    assert.deepEqual(await page.locator('#sidenav .sn-node').allTextContents(), ['1','2','3']);  // 流程组：步骤号
    assert.equal(await page.locator('#sidenav').evaluate(el=>el.classList.contains('is-sequence')), true);
    assert.match(await page.locator('#sidenav [data-nav="approvals"]').getAttribute('title'), /Confirm or return/);
    // 有待审登记：数量同时出现在组名与侧边栏，管理员点组名直接到 Approval
    await page.evaluate(()=>{ applySnapshot({cases:HAND_CASES, submissions:[{subId:'SUB-9', status:'Waiting for Registration Confirmation', submitterName:'T', submitterEmail:'t@example.com',
      submittedAt:'Dec 20, 2026 7:00 AM', partNumber:'1', partDescription:'P', caseId:'SWAT-9', region:'EU', meetingDateLabel:'Wed, Dec 23, 2026'}]}); render(); });
    assert.equal(await page.locator('[data-nav-group="workflow"] .count-badge').textContent(), '1');
    assert.equal(await page.locator('#sidenav [data-nav="approvals"] .count-badge').textContent(), '1');
    // 每项下面一行实时状态；收起成窄条只留编号，偏好记在本机浏览器
    assert.equal(await page.locator('#sidenav [data-nav="approvals"] .sn-meta').textContent(), '1 waiting');
    assert.match(await page.locator('#sidenav [data-nav="submit"] .sn-meta').textContent(), /^KW\d\d · by Mon 23:59$/);
    await page.locator('#navCollapse').click();
    assert.equal(await page.locator('#sidenav').evaluate(el=>el.classList.contains('is-collapsed')), true);
    assert.equal(await page.locator('#sidenav [data-nav="approvals"] .sn-text').isVisible(), false);
    assert.equal(await page.evaluate(()=>localStorage.getItem('sc_nav_collapsed')), '1');
    assert.match(await page.locator('#sidenav [data-nav="approvals"]').getAttribute('title'), /^Approval — 1 waiting$/);
    await page.locator('#navCollapse').click();
    assert.equal(await page.locator('#sidenav [data-nav="approvals"] .sn-text').isVisible(), true);
    await page.locator('[data-nav="home"]').click();
    await page.locator('[data-nav-group="workflow"]').click();
    assert.equal(await page.evaluate(()=>state.view), 'approvals');
    // Data：默认 Database，再回来时打开上次看的页面
    await page.locator('[data-nav-group="data"]').click();
    assert.equal(await page.evaluate(()=>state.view), 'database');
    assert.deepEqual(await side(), ['Database','Dashboard']);
    assert.equal(await page.locator('#sidenav').evaluate(el=>el.classList.contains('is-sequence')), false);  // Data 没有先后，不连线
    assert.equal(await page.locator('#sidenav .sn-node svg').count(), 2);
    await page.locator('#sidenav [data-nav="dashboard"]').click();
    await page.locator('[data-nav="home"]').click();
    await page.locator('[data-nav-group="data"]').click();
    assert.equal(await page.evaluate(()=>state.view), 'dashboard');
    // 板块说明收进 ⓘ：平时不显示，悬停才出现；读屏软件能从 aria-label 读到
    await goTo(page, 'database');
    assert.equal(await page.locator('.pagehead p').count(), 0);
    const tip = page.locator('.pagehead .info-tip');
    assert.equal(await tip.locator('.info-pop').isVisible(), false);
    assert.match(await tip.getAttribute('aria-label'), /consolidated automatically/);
    await tip.hover();
    assert.equal(await tip.locator('.info-pop').isVisible(), true);
    // Database 窗口不到 1440px：侧边栏让位给表格，变成上方横向标签；其他页面仍在左侧
    const layout = ()=>page.evaluate(()=>getComputedStyle(document.querySelector('.shell')).flexDirection);
    assert.equal(await layout(), 'row');
    await page.setViewportSize({width:1280, height:900});
    assert.equal(await layout(), 'column');
    await goTo(page, 'dashboard');
    assert.equal(await layout(), 'row');
    // 案例详情不显示侧边栏，顶部高亮 Data
    await goTo(page, 'database');
    await page.locator('#app tbody tr[data-swat]').first().click();
    assert.equal(await page.evaluate(()=>state.view), 'detail');
    assert.equal(await page.locator('#sidenav').isVisible(), false);
    assert.equal(await page.locator('#navtabs button.active').textContent(), 'Data');
    await context.close();
  });

  await test('Database week sort lists each week by level (L2, L3, L4) then region (AP, EU, NA) in both directions', async()=>{
    const {page, context} = await fixture();
    await page.evaluate(()=>{
      const base = {partNumber:'1', partDescription:'P', recommendedSupplier:'S', presenter:'O', cluster:'Metal', meetingDecision:'PENDING', meetingYear:2026};
      const mk = (swat, weekNum, caseNumber, decisionLevel, region='EU')=>mkCase({...base, id:swat, swatId:swat, weekNum, caseNumber, decisionLevel, region});
      applySnapshot({cases:[mk('42-L4-EU',42,1,'Level 4'), mk('42-L2-NA',42,4,'Level 2','NA'), mk('42-L4-AP',42,2,'Level 4','AP'),
                            mk('42-L2-AP+EU',42,5,'Level 2','AP + EU'), mk('42-L3',42,3,'Level 3'), mk('42-none',42,6,''),
                            mk('43-L4',43,1,'Level 4'), mk('43-L3',43,2,'Level 3')]});
      state.view='database'; render();
    });
    const swats = ()=>page.evaluate(()=>[...document.querySelectorAll('tbody tr')].map(r=>r.dataset.swat));
    const week42 = ['42-L2-AP+EU','42-L2-NA','42-L3','42-L4-AP','42-L4-EU','42-none'];
    assert.deepEqual(await swats(), ['43-L3','43-L4', ...week42]);  // 默认周倒序，周内顺序不变
    await page.locator('th[data-sort="week"]').click();
    assert.deepEqual(await swats(), [...week42, '43-L3','43-L4']);
    await context.close();
  });

  await test('Dashboard selects a year, counts real follow-up actions and charts them by function and owner', async()=>{
    const requested = [];
    const {page, context} = await fixture({api:async(route,path)=>{
      if(!path.startsWith('/api/exports/')) return false;
      requested.push(path+'?'+new URL(route.request().url()).searchParams.toString());
      await route.fulfill({status:200, headers:{'content-disposition':'attachment; filename="x.xlsx"'}, contentType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', body:Buffer.from('xlsx!!!')});
      return true;
    }});
    await page.evaluate(()=>{ window.__saved = []; saveBlobFile = async (blob, filename)=>{ window.__saved.push(filename); }; });
    await page.evaluate(()=>{
      const base = {partNumber:'1', partDescription:'P', recommendedSupplier:'S', presenter:'O', cluster:'Metal', meetingDecision:'APPROVED'};
      const task = (id, status, fn, owner) => ({id, task:'t '+id, status, ownerFunction:fn, responsible:owner, dueDate:'2027-01-01', tags:[], notifyEmail:'x@example.com'});
      applySnapshot({cases:[
        mkCase({...base, id:'C-1', swatId:'SWAT-A', weekNum:40, caseNumber:1, meetingYear:2026, meetingDateISO:'2026-09-30', actionStatus:'Overdue',
          followUps:[task('T1','Open','Purchasing','Ann'), task('T2','Overdue','Supplier Quality','Bob'), task('T3','Closed','Purchasing','Ann')]}),
        mkCase({...base, id:'C-2', swatId:'SWAT-B', weekNum:41, caseNumber:1, meetingYear:2026, meetingDateISO:'2026-10-07', actionStatus:null, followUps:[]}),  // 已决议、没有待办：Closed 必须是 0
        mkCase({...base, id:'C-3', swatId:'SWAT-C', weekNum:51, caseNumber:1, meetingYear:2025, meetingDateISO:'2025-12-17', actionStatus:'Open',
          followUps:[task('T4','Open','','Cid')]}),
        mkCase({...base, id:'C-4', swatId:'SWAT-D', weekNum:41, caseNumber:2, meetingYear:2026, meetingDateISO:'2026-10-07', meetingDecision:'PENDING', actionStatus:null}),
      ]});
      state.view='dashboard'; render();
    });
    const tiles = async ()=> page.evaluate(()=>Object.fromEntries([...document.querySelectorAll('.tile')].map(t=>[t.dataset.kpi, Number(t.querySelector('.num').textContent)])));
    const bars = async title => page.evaluate(title=>{
      const card=[...document.querySelectorAll('.breakdown-card')].find(el=>el.querySelector('h4').textContent===title);
      return [...card.querySelectorAll('.bar-row')].map(r=>r.querySelector('.blabel').textContent+'='+r.querySelector('.bar-num').textContent);
    }, title);
    assert.deepEqual(await page.locator('#dashYearSelect option').allTextContents(), ['2025','2026']);
    assert.equal(await page.locator('#dashYearSelect').inputValue(), '2026');
    let t = await tiles();
    assert.deepEqual([t.approved, t.pending, t.open, t.overdue, t.closedaction], [2, 1, 1, 1, 1]);
    let text = await page.locator('#app').innerText();
    assert.ok(text.includes('Total Cases\n3') && text.toLowerCase().includes('action status · 2026') && !text.includes('YTD'), text);
    assert.deepEqual(await bars('Open actions by function'), ['Purchasing=1']);
    assert.deepEqual(await bars('Overdue actions by function'), ['Supplier Quality=1']);
    assert.deepEqual(await bars('Open actions by owner'), ['Ann=1']);
    assert.deepEqual(await bars('Overdue actions by owner'), ['Bob=1']);
    assert.deepEqual(await bars('Cases by Cluster · 2026'), ['Metal=3']);
    await page.locator('#dashYearSelect').selectOption('2025');
    t = await tiles();
    assert.deepEqual([t.approved, t.open, t.overdue, t.closedaction], [1, 1, 0, 0]);
    assert.deepEqual(await bars('Open actions by function'), ['Function not set=1']);
    assert.ok((await page.locator('#app').innerText()).includes('No overdue actions in this scope.'));
    // 周视图只列所选年份的周；导出带年份
    await page.locator('[data-period="week"]').click();
    assert.deepEqual(await page.locator('#dashWeekSelect option').allTextContents(), ['2025-KW51 — Dec 17, 2025']);
    await page.locator('#dashAgendaBtn').click();
    await page.waitForFunction(()=>window.__saved.length===1);
    assert.deepEqual(requested, ['/api/exports/agenda?week=51&year=2025']);
    // 点 Closed 格子 → Follow-ups 页按 Closed + 年份
    await page.locator('[data-period="year"]').click();
    await page.locator('#dashYearSelect').selectOption('2026');
    await page.locator('.tile[data-kpi="closedaction"]').click();
    assert.equal(await page.evaluate(()=>state.view), 'followups');
    assert.equal(await page.locator('#fFollowupStatus').inputValue(), 'Closed');
    assert.equal(await page.locator('#fFollowupYear').inputValue(), '2026');
    text = await page.locator('#app').innerText();
    assert.ok(text.includes('1 task') && text.includes('t T3'), text);
    await context.close();
  });

  await test('Case page lists uploaded files on one line each and attaches presentations from the server library', async()=>{
    const posted = [];
    let seeded;
    const {page, context} = await fixture({user:'manager', api:async(route,path)=>{
      if(path==='/api/presentation-library'){
        await route.fulfill({json:{ok:true, folder:'D:\\apps\\cockpit\\data\\presentations', files:[  // 服务端按文件夹、文件名排好序（根目录在前）
          {path:'Final report.pdf', name:'Final report.pdf', folder:'', size:2048, modified:'Oct 1, 3:05 PM'},
          {path:'KW39, 23.09.2026/MBEAL deck.pptx', name:'MBEAL deck.pptx', folder:'KW39, 23.09.2026', size:338000, modified:'Oct 1, 3:05 PM'}]}});
        return true;
      }
      if(path.endsWith('/files/from-library')){
        posted.push({path, body:route.request().postDataJSON(), token:route.request().headers()['x-session-token']});
        const file = {id:'F-L1', name:'2026.10.08 Test project Test part 1234, Test supplier.pptx', originalName:'MBEAL deck.pptx', size:338000, uploadedBy:'NPI Person', uploadedAt:'Oct 8, 10:00 AM', store:'local'};
        const c = {...seeded, files:[file]};
        await route.fulfill({json:{ok:true, file, case:c, snapshot:{...empty, cases:[c]}}});
        return true;
      }
      return false;
    }});
    await page.evaluate(()=>{
      const c = mkCase({id:'C-TEST', swatId:'SWAT-TEST', partNumber:'1234', partDescription:'Test part', weekNum:40, caseNumber:1, project:'Test project', recommendedSupplier:'Test supplier', presenter:'O', region:'AP', cluster:'Metal', meetingDecision:'APPROVED',
        files:[{id:'F-0', name:'2026.10.01 GM C1UC_UL2 APT Mount Bracket R003W668A, Proto Gage Tool & Die, Inc.pdf', originalName:'20260410 C1UCUL2 110000034383 Bundle Report - 10.04.2026 (4).pdf', size:346112, uploadedBy:'Ewa', uploadedAt:'Oct 1, 3:05 PM', store:'local'}]});
      window.__case = c;
      applySnapshot({cases:[c]}); goToDetail('SWAT-TEST');
    });
    seeded = await page.evaluate(()=>JSON.parse(JSON.stringify(window.__case)));
    await page.setViewportSize({width:1100, height:900});
    // 文件名一行显示（领导截图里是一字一行）：名称宽度接近卡片宽度，高度只有一两行
    const box = await page.locator('.file-list .fname').boundingBox();
    const li = await page.locator('.file-list li').boundingBox();
    assert.ok(box.width > li.width*0.6 && box.height < 60, JSON.stringify({box, li}));
    assert.ok((await page.locator('.file-list .fmeta').innerText()).includes('uploaded as 20260410'));
    // 服务器文件库：下拉框按文件夹分组，选中后 POST 相对路径
    await page.waitForFunction(()=>document.querySelectorAll('#caseLibSelect option').length>1);
    assert.deepEqual(await page.locator('#caseLibSelect option').allTextContents(), ['Select a file from the server library…','Final report.pdf (2 KB)','MBEAL deck.pptx (330.1 KB)'.replace('330.1 KB','330 KB')]);
    assert.deepEqual(await page.locator('#caseLibSelect optgroup').evaluateAll(els=>els.map(e=>e.label)), ['KW39, 23.09.2026']);
    assert.ok((await page.locator('#app').innerText()).includes('D:\\apps\\cockpit\\data\\presentations'));
    await page.locator('#caseLibSelect').selectOption('KW39, 23.09.2026/MBEAL deck.pptx');
    await page.locator('#caseLibAttach').click();
    await page.waitForFunction(()=>document.querySelectorAll('.file-list li').length===1 && document.body.innerText.includes('attached as'));
    assert.deepEqual(posted, [{path:'/api/cases/C-TEST/files/from-library', body:{path:'KW39, 23.09.2026/MBEAL deck.pptx'}, token:'tok'}]);
    assert.ok((await page.locator('.file-list .fmeta').innerText()).includes('uploaded as MBEAL deck.pptx'));
    // 普通用户看不到文件库
    const other = await fixture({user:'user'});
    await other.page.evaluate(c=>{ applySnapshot({cases:[c]}); goToDetail('SWAT-TEST'); }, seeded);
    assert.equal(await other.page.locator('#caseLibSelect').count(), 0);
    await other.context.close();
    await context.close();
  });

  // ===== v3 Phase-19：同事试用反馈 =====
  await test('Submit lists every missing field at once and offers "No tooling involved"', async()=>{
    let submitted;
    const {page, context} = await fixture({user:'user', api:async(route,path)=>{
      if(path!=='/api/submissions') return false;
      submitted = route.request().postDataJSON();
      await route.fulfill({json:{subId:'SUB-TEST',snapshot:empty}});
      return true;
    }});
    await goTo(page, 'submit');
    assert.deepEqual(await page.locator('#fToolingPayment option').allTextContents(), ['Select...','Lumpsum','MPC','No tooling involved']);
    await page.locator('#submitCaseBtn').click();
    const items = await page.locator('#submitBanner .problem-list li').allTextContents();
    assert.ok(items.length >= 8, items.join(' | '));
    for(const needle of ['Part Number and Part Description','Project, Sourcing Type','Region','bundle Peak Year Spend','SWAT Case #','Family Case','change management (CCB)','Pc Price CQA','Tooling Payment (Lumpsum, MPC or No tooling involved)'])
      assert.ok(items.some(t=>t.includes(needle)), needle+' missing in: '+items.join(' | '));
    assert.ok((await page.locator('#submitBanner').innerText()).startsWith(`⚠ Please fix these ${items.length} points before submitting:`));
    assert.equal(submitted, undefined);
    // 补齐后只剩一条：原样一句话显示
    for(const [id,value] of Object.entries({fExistingSwat:'SWAT-1000',pnSupplier_0:'S',pnProject_0:'P',pnPartNumber_0:'1234',pnPartDescription_0:'Part',fBundlePeak:'10',fBundleLife:'20'}))
      await page.locator('#'+id).fill(value);
    await page.locator('#qFamily').selectOption('No');
    await page.locator('#qECM').selectOption('No');
    await fillCommercial(page);
    await page.locator('#fToolingPayment').selectOption('No tooling involved');
    await page.locator('#submitCaseBtn').click();
    assert.equal(await page.locator('#submitBanner').innerText(), '⚠ Please select at least one Region before submitting.');
    await page.locator('#fRegionIn input[value="EU"]').check();
    await page.locator('#submitCaseBtn').click();
    await page.waitForFunction(()=>document.getElementById('submitBanner')?.textContent.includes('SUB-TEST'));
    assert.equal(submitted.toolingPayment, 'No tooling involved');
    await context.close();
  });

  await test('Server-side problems arrive as one list in the submit banner', async()=>{
    const {page, context} = await fixture({user:'user', api:async(route,path)=>{
      if(path!=='/api/submissions') return false;
      await route.fulfill({status:422, json:{detail:'⚠ First server problem.\n⚠ Second server problem.'}});
      return true;
    }});
    await goTo(page, 'submit');
    for(const [id,value] of Object.entries({fExistingSwat:'SWAT-1000',pnSupplier_0:'S',pnProject_0:'P',pnPartNumber_0:'1234',pnPartDescription_0:'Part',fBundlePeak:'10',fBundleLife:'20'}))
      await page.locator('#'+id).fill(value);
    await page.locator('#fRegionIn input[value="EU"]').check();
    await page.locator('#qFamily').selectOption('No');
    await page.locator('#qECM').selectOption('No');
    await fillCommercial(page);
    await page.locator('#submitCaseBtn').click();
    await page.waitForFunction(()=>document.querySelectorAll('#submitBanner .problem-list li').length===2);
    assert.deepEqual(await page.locator('#submitBanner .problem-list li').allTextContents(), ['First server problem.','Second server problem.']);
    await context.close();
  });

  await test('Case edit lists every problem, accepts an uploaded file as the presentation, keeps edits across uploads, and lets the admin move the week', async()=>{
    let saved, uploads = 0;
    let current;
    const {page, context} = await fixture({user:'admin', api:async(route,path)=>{
      if(path==='/api/presentation-library'){ await route.fulfill({json:{ok:true, folder:'', files:[]}}); return true; }
      if(path==='/api/cases/C-TEST/files'){
        uploads++;
        current = {...current, files:[{id:'F-1', name:'2026.10.08 deck.pptx', originalName:'deck.pptx', size:2048, uploadedBy:'Sourcing Admin', uploadedAt:'Oct 8, 9:00 AM', store:'local'}]};
        await route.fulfill({json:{ok:true, file:current.files[0], case:current, snapshot:{...empty, cases:[current]}}});
        return true;
      }
      if(path==='/api/cases/C-TEST' && route.request().method()==='PUT'){
        saved = route.request().postDataJSON();
        const moved = {...current, weekNum:41, meetingYear:2026, meetingDateISO:'2026-10-07', meetingDateLabel:'Wed, Oct 7, 2026', meetingDecision:saved.meetingDecision, followUps:saved.followUps};
        await route.fulfill({json:{ok:true, case:moved, snapshot:{...empty, cases:[moved]}}});
        return true;
      }
      return false;
    }});
    current = await seed(page, {meetingYear:2026, meetingDateISO:'2026-09-30', meetingDateLabel:'Wed, Sep 30, 2026', files:[]});
    await page.evaluate(()=>goToDetail('SWAT-TEST'));
    await page.locator('#editCaseBtn').click();
    // 改周：只有 Sourcing admin 有这个输入框，预览新周
    assert.equal(await page.locator('#editMeetingDate').inputValue(), '2026-09-30');
    await page.locator('#editMeetingDate').fill('2026-10-09');
    assert.ok((await page.locator('#editMeetingWeek').innerText()).startsWith('→ 2026-KW41 · Wed, Oct 7, 2026'));
    // 多个问题一次列出
    await page.locator('#editDecision').selectOption('APPROVED');
    await page.locator('#addTaskBtn').click();
    await page.locator('#editFuTask_0').fill('Send samples');
    await page.locator('#saveCaseBtn').click();
    const items = await page.locator('.block-warning .problem-list li').allTextContents();
    assert.equal(items.length, 2, items.join(' | '));
    assert.ok(items[0].includes('Sourcing Presentation') && items[1].includes('Follow-up task 1'), items.join(' | '));
    assert.equal(saved, undefined);
    // 编辑状态下上传演示文件：未保存的内容（待办、改周）不丢
    await page.locator('#editFuEmail_0').fill('a@zf.com');
    await page.locator('#caseFileInput').setInputFiles([{name:'deck.pptx', mimeType:'application/vnd.openxmlformats-officedocument.presentationml.presentation', buffer:Buffer.alloc(2048,1)}]);
    await page.waitForFunction(()=>document.querySelectorAll('.file-list li').length===1);
    assert.equal(uploads, 1);
    assert.equal(await page.evaluate(()=>state.detailEditMode), true);
    assert.equal(await page.locator('#editFuTask_0').inputValue(), 'Send samples');
    assert.equal(await page.locator('#editFuEmail_0').inputValue(), 'a@zf.com');
    assert.equal(await page.locator('#editMeetingDate').inputValue(), '2026-10-09');
    assert.ok((await page.locator('#app').innerText()).includes('Optional — 1 file attached below'));
    // 有文件即满足演示文稿规则：不填链接也能存，一次保存待办 + 改周
    await page.locator('#saveCaseBtn').click();
    await page.waitForFunction(()=>!state.detailEditMode);
    assert.equal(saved.sourcingPresentationLink, '');
    assert.equal(saved.meetingDate, '2026-10-09');
    assert.equal(saved.followUps[0].task, 'Send samples');
    const text = await page.locator('#app').innerText();
    assert.ok(text.includes('2026-KW41 · Wed, Oct 7, 2026') && text.includes('1 file under Sourcing Presentation Files'), text);
    await context.close();
    // Manager：看不到改周输入框，载荷里也不带 meetingDate
    let mgrSaved;
    const mgr = await fixture({user:'manager', api:async(route,path)=>{
      if(path==='/api/presentation-library'){ await route.fulfill({json:{ok:true, folder:'', files:[]}}); return true; }
      if(path==='/api/cases/C-TEST'){ mgrSaved = route.request().postDataJSON(); await route.fulfill({json:{ok:true, case:{}, snapshot:{...empty, cases:[]}}}); return true; }
      return false;
    }});
    await seed(mgr.page, {meetingYear:2026, meetingDateISO:'2026-09-30'});
    await mgr.page.evaluate(()=>goToDetail('SWAT-TEST'));
    await mgr.page.locator('#editCaseBtn').click();
    assert.equal(await mgr.page.locator('#editMeetingDate').count(), 0);
    await mgr.page.locator('#saveCaseBtn').click();
    await mgr.page.waitForFunction(()=>!state.detailEditMode);
    assert.ok(!('meetingDate' in mgrSaved), JSON.stringify(Object.keys(mgrSaved)));
    await mgr.context.close();
  });

  // ===== v3 Phase-37 / 38 / 39：领导 2026-10-28 反馈 =====
  await test('Edit Case picks a Commodity (Cluster follows), the detail page shows the registration screening answers, and Level 4 needs no presentation', async()=>{
    const COMMODITY_OPTIONS = [{cluster:'Chemical', commodity:'Textiles'}, {cluster:'Metal', commodity:'FF Forging, Forming & Tubes'},
      {cluster:'Electronics, EA and Pyro', commodity:'Pyro'}];
    let saved;
    const {page, context} = await fixture({user:'admin', api:async(route,path)=>{
      if(path==='/api/presentation-library'){ await route.fulfill({json:{ok:true, folder:'', files:[]}}); return true; }
      if(path==='/api/cases/C-TEST' && route.request().method()==='PUT'){
        saved = route.request().postDataJSON();
        const after = await page.evaluate(()=>ALL_CASES[0]);
        const updated = {...after, meetingDecision:saved.meetingDecision, decisionLevel:saved.decisionLevel, cluster:'Metal', commodity:saved.commodity};
        await route.fulfill({json:{ok:true, case:updated, snapshot:{cases:[updated]}}});
        return true;
      }
      return false;
    }});
    // 导入时认不出的 Commodity（Excel 里写成了人名），已在编辑页改过 Cluster
    await seed(page, {source:{kind:'excel', file:'KW47.xlsx', row:4}, cluster:'Metal', commodity:'Yajun Zhao', commodityRaw:'Yajun Zhao',
      decisionLevel:'Level 2', createdDate:'Nov 19, 9:00 AM'});
    await page.evaluate(opts=>applySnapshot({commodityOptions:opts}), COMMODITY_OPTIONS);
    await page.evaluate(()=>goToDetail('SWAT-TEST'));
    const info = ()=>page.locator('.info-grid', {hasText:'SWAT Case Number'}).innerText();
    // Excel 导入的案例没有登记单：四项筛查答案都是 —
    assert.ok(/Family Case\?\s*—/.test(await info()) && /Passed CCB2\?\s*—/.test(await info()), await info());

    await page.locator('#editCaseBtn').click();
    assert.equal(await page.locator('#editCommodity').inputValue(), 'Yajun Zhao');
    assert.ok((await page.locator('#editCommodity option:checked').textContent()).includes('not in the list'));
    assert.equal(await page.locator('#editCluster').isDisabled(), false);
    await page.locator('#editCommodity').selectOption('Pyro');
    assert.equal(await page.locator('#editCluster').inputValue(), 'Electronics, EA and Pyro');
    assert.equal(await page.locator('#editCluster').isDisabled(), true);
    await page.locator('#editCommodity').selectOption('FF Forging, Forming & Tubes');
    assert.equal(await page.locator('#editCluster').inputValue(), 'Metal');
    await page.locator('#saveCaseBtn').click();
    await page.waitForFunction(()=>!state.detailEditMode);
    assert.equal(saved.commodity, 'FF Forging, Forming & Tubes');
    assert.equal(saved.cluster, 'Metal');
    assert.ok((await info()).includes('FF Forging, Forming & Tubes (Excel: Yajun Zhao)'), await info());

    // 在线登记确认的案例：从这条登场记录的登记单读出答案（同一 SWAT、创建时间 = 提交时间）
    await page.evaluate(()=>{
      const c = {...ALL_CASES[0], source:null, commodityRaw:'', createdDate:'Oct 20, 10:00 AM'};
      applySnapshot({cases:[c], submissions:[
        {subId:'SUB-OLD', status:'Registration Confirmed', approvedSwatId:'SWAT-TEST', submittedAt:'Sep 1, 8:00 AM', isFamilyCase:'No', involvesECM:'No'},
        {subId:'SUB-1', status:'Registration Confirmed', approvedSwatId:'SWAT-TEST', submittedAt:'Oct 20, 10:00 AM',
          isFamilyCase:'Yes', familyAligned:'Yes', involvesECM:'Yes', ccbApproved:'Yes'}]});
      render();
    });
    const text = await info();
    assert.ok(/Family Case\?\s*Yes/.test(text) && /Family Alignment Done\?\s*Yes/.test(text)
      && /Involves CCB\?\s*Yes/.test(text) && /Passed CCB2\?\s*Yes/.test(text), text);

    // Level 4：记录 Approved 不要求演示文稿；Level 2 照旧要求（在线登记的案例才有这条规则）
    await page.locator('#editCaseBtn').click();
    await page.locator('#editDecisionLevel').selectOption('Level 2');
    await page.locator('#editDecision').selectOption('APPROVED');
    await page.locator('#saveCaseBtn').click();
    assert.ok((await page.locator('.block-warning').first().textContent()).includes('Sourcing Presentation'));
    await page.locator('#editDecisionLevel').selectOption('Level 4');
    await page.locator('#saveCaseBtn').click();
    await page.waitForFunction(()=>!state.detailEditMode);
    assert.equal(saved.decisionLevel, 'Level 4');
    assert.equal(saved.meetingDecision, 'APPROVED');
    await context.close();
  });

  // ===== v3 Phase-20：上传区分 Meeting minutes 与 Presentations =====
  await test('Home upload card separates meeting minutes from presentations, attaches matched presentations and uploads new ones', async()=>{
    const SAMPLE = '1. 110000034978 SPR8 Tube_34235239A_ NA_CO_L2_Iron Force Huzhou_Tube_Haojie.pdf';
    let files = [
      {path:'KW15, 08.04.2026/'+SAMPLE, name:SAMPLE, folder:'KW15, 08.04.2026', size:338000, modified:'Oct 8, 9:00 AM',
        match:{rowId:'C-1', swatId:'110000034978', label:'2026-KW15 · Case #1 · 110000034978', by:'SWAT number', attached:false}},
      {path:'Unsorted/random.pdf', name:'random.pdf', folder:'Unsorted', size:2048, modified:'Oct 8, 9:00 AM', match:null},
    ];
    const attachCalls = [], uploads = [];
    const {page, context} = await fixture({user:'admin', api:async(route,path)=>{
      if(path==='/api/import/library'){ await route.fulfill({json:{ok:true, files:[]}}); return true; }
      if(path==='/api/presentation-library'){ await route.fulfill({json:{ok:true, folder:'data/presentations', files}}); return true; }
      if(path==='/api/presentation-library/attach'){
        const body = route.request().postDataJSON(); attachCalls.push(body.paths);
        files = files.map(f=>f.match && body.paths.includes(f.path) ? {...f, match:{...f.match, attached:true}} : f);
        await route.fulfill({json:{ok:true, snapshot:empty, files,
          attached: body.paths.filter(p=>p.startsWith('KW15')).map(p=>({path:p, label:'2026-KW15 · Case #1 · 110000034978', name:'x.pdf', by:'SWAT number'})),
          skipped: body.paths.filter(p=>!p.startsWith('KW15')).map(p=>({path:p, reason:'No matching case — attach it on the case page.'}))}});
        return true;
      }
      if(path==='/api/presentation-library/files'){
        const name = new URL(route.request().url()).searchParams.get('name'); uploads.push(name);
        const file = {path:'KW20, 13.05.2026/'+name, name, folder:'KW20, 13.05.2026', size:10, modified:'Oct 8, 9:01 AM',
          match:{rowId:'C-2', swatId:'110000035000', label:'2026-KW20 · Case #3 · 110000035000', by:'SWAT number', attached:false}};
        files = [...files, file];
        await route.fulfill({json:{ok:true, path:file.path, file, files}});
        return true;
      }
      return false;
    }});
    const headings = await page.locator('.upload-kind').allTextContents();
    assert.deepEqual(headings.map(h=>h.split(' ')[0]+' '+h.split(' ')[2]), ['1 Meeting','2 Presentations']);
    await page.waitForFunction(()=>document.querySelectorAll('#presSelect option').length===3);
    const opts = await page.locator('#presSelect option').allTextContents();
    assert.equal(opts[1], SAMPLE+' — → 2026-KW15 · Case #1 · 110000034978');
    assert.equal(opts[2], 'random.pdf — no matching case — attach it on the case page');
    assert.deepEqual(await page.locator('#presSelect optgroup').evaluateAll(els=>els.map(e=>e.label)), ['KW15, 08.04.2026','Unsorted']);
    assert.equal(await page.locator('#presAttachAll').innerText(), 'Attach all matched, not yet attached (1)');
    // 单个挂接（对不上的会说明原因）
    await page.locator('#presSelect').selectOption('Unsorted/random.pdf');
    await page.locator('#presAttachOne').click();
    await page.waitForFunction(()=>document.querySelector('.pres-results')?.textContent.includes('1 skipped'));
    // 批量挂接
    await page.locator('#presAttachAll').click();
    await page.waitForFunction(()=>document.querySelector('.pres-results')?.textContent.includes('1 attached'));
    assert.deepEqual(attachCalls, [['Unsorted/random.pdf'], ['KW15, 08.04.2026/'+SAMPLE]]);
    assert.ok((await page.locator('#presSelect option').allTextContents())[1].includes('✓ attached to 2026-KW15'));
    assert.equal(await page.locator('#presAttachAll').isDisabled(), true);
    // 从本机上传进文件库：.exe 被拦，PDF 上传后提示可批量挂接
    await page.locator('#presUploadInput').setInputFiles([
      {name:'3. 110000035000 deck.pdf', mimeType:'application/pdf', buffer:Buffer.alloc(10,1)},
      {name:'KW15 MM.xlsx', mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer:Buffer.from('x')}]);
    await page.waitForFunction(()=>document.getElementById('presUploadMsg')?.textContent.includes('uploaded'));
    assert.deepEqual(uploads, ['3. 110000035000 deck.pdf']);
    assert.equal(await page.locator('#presUploadMsg').innerText(), '1 uploaded, 1 matched to a case — press "Attach all matched", 1 failed.');
    assert.ok((await page.locator('.pres-results').innerText()).includes('only PDF or PowerPoint'));  // 周会 Excel 不进演示文件库
    assert.equal(await page.locator('#presAttachAll').innerText(), 'Attach all matched, not yet attached (1)');
    await context.close();
  });

  await test('Committee Discussion keeps its line breaks and its numbered action items can be added as follow-up tasks', async()=>{
    const requests = [];
    const drafts = [
      {ref:'1', task:'Share deck', responsible:'SP Melisa', dueDate:'2026-10-09', dueText:'by 09.10.2026', dueEstimated:false, notes:''},
      {ref:'2', task:'Kickoff Kimball', responsible:'BUP Rafal', dueDate:'2026-10-16', dueText:'KW42', dueEstimated:true, notes:'Due date estimated from "KW42" — please confirm.'},
      {ref:'2a', task:'Check VA', responsible:'', dueDate:'', dueText:'', dueEstimated:false, notes:'Carrie to approve.'},
    ];
    const {page, context} = await fixture({user:'admin', api:async(route,path)=>{
      if(path==='/api/presentation-library'){ await route.fulfill({json:{ok:true, folder:'', files:[]}}); return true; }
      if(path!=='/api/action-items/extract') return false;
      const body = route.request().postDataJSON();
      requests.push(body);
      await route.fulfill({json:{items: body.text.startsWith('1.') ? drafts : []}});
      return true;
    }});
    const notes = '1. Share deck -- SP Melisa by 09.10.2026\n2. Kickoff Kimball -- BUP Rafal KW42\na. Check VA';
    await seed(page, {meetingYear:2026, meetingDateISO:'2026-10-07', meetingDateLabel:'Wed, Oct 7, 2026', meetingDecision:'APPROVED',
      sourcingPresentationLink:'https://zf.sharepoint.com/deck', committeeDiscussion:notes,
      followUps:[{id:'FU-1', task:'1. Share deck', responsible:'SP Melisa', dueDate:'2026-10-09', status:'Open', notifyEmail:'m@zf.com', tags:[], notes:''}]});
    await page.evaluate(()=>goToDetail('SWAT-TEST'));
    // 查看页：纪要一条一行
    assert.equal(await page.locator('.discussion-box').evaluate(el=>getComputedStyle(el).whiteSpace), 'pre-wrap');
    assert.equal((await page.locator('.discussion-box').innerText()).split('\n').length, 3);
    await page.locator('#editCaseBtn').click();
    // 没有编号任务：提示写法
    await page.locator('#editDiscussion').fill('Approved, no open points.');
    await page.locator('#extractTasksBtn').click();
    await page.waitForFunction(()=>document.querySelector('.action-drafts')?.textContent.includes('No numbered action items'));
    await page.locator('#discardDraftsBtn').click();
    assert.equal(await page.locator('.action-drafts').count(), 0);
    // 用编辑框里（还没保存）的纪要和这条记录的会议日期去识别
    await page.locator('#editDiscussion').fill(notes);
    await page.locator('#extractTasksBtn').click();
    await page.locator('.action-draft').first().waitFor();
    assert.deepEqual(requests.at(-1), {text:notes, meetingDateISO:'2026-10-07'});
    const rows = await page.locator('.action-draft').allInnerTexts();
    assert.equal(rows.length, 3);
    assert.ok(rows[0].includes('1. Share deck') && rows[0].includes('(already in the list)'), rows[0]);
    assert.ok(rows[1].includes('Owner: BUP Rafal') && rows[1].includes('2026-10-16 (estimated from "KW42")'), rows[1]);
    assert.deepEqual(await page.locator('[data-draft]').evaluateAll(els=>els.map(el=>el.checked)), [false, true, true]);
    assert.equal(await page.locator('#addDraftsBtn').innerText(), 'Add 2 selected as follow-up tasks');
    await page.locator('[data-draft="2"]').uncheck();
    assert.equal(await page.locator('#addDraftsBtn').innerText(), 'Add 1 selected as follow-up task');
    // 加进待办：已有任务里没保存的输入不丢；新任务带编号、负责人、日期、备注，邮箱留给人填
    await page.locator('#editFuEmail_0').fill('melisa@zf.com');
    await page.locator('#addDraftsBtn').click();
    assert.equal(await page.locator('.action-drafts').count(), 0);
    assert.equal(await page.locator('#editFuEmail_0').inputValue(), 'melisa@zf.com');
    assert.equal(await page.locator('#editFuTask_1').inputValue(), '2. Kickoff Kimball');
    assert.equal(await page.locator('#editFuResp_1').inputValue(), 'BUP Rafal');
    assert.equal(await page.locator('#editFuDue_1').inputValue(), '2026-10-16');
    assert.ok((await page.locator('#editFuNotes_1').inputValue()).includes('estimated from "KW42"'));
    assert.equal(await page.locator('#editFuEmail_1').inputValue(), '');
    assert.equal(await page.locator('#editFuTask_2').count(), 0);
    await context.close();
  });

  await test('Follow-ups show owners by full name, edit a task in place (also from the reminder log) and fill in the owner\'s function', async()=>{
    // v3 Phase-29（领导 2026-10-16）
    const puts = [];
    let current = null;
    const {page, context} = await fixture({user:'manager', api:async(route,path)=>{
      if(!path.startsWith('/api/tasks/') || route.request().method()!=='PUT') return false;
      const body = route.request().postDataJSON();
      puts.push({path, body});
      const id = decodeURIComponent(path.split('/').pop());
      current.followUps = current.followUps.map(t=> t.id===id ? {...t, ...body} : t);
      await route.fulfill({json:{ok:true, task:current.followUps.find(t=>t.id===id), snapshot:{cases:[current]}}});
      return true;
    }});
    current = await page.evaluate(()=>{
      const task = (id, status, owner, name, fn, due) => ({id, task:'t '+id, status, responsible:owner, ownerName:name, ownerFunction:fn,
        dueDate:due, tags:[], notifyEmail:'x@example.com', cc:'', channel:'Email + Teams'});
      const c = mkCase({id:'C-1', swatId:'SWAT-A', partNumber:'1', partDescription:'P', recommendedSupplier:'S', presenter:'O', cluster:'Metal',
        weekNum:40, caseNumber:1, meetingYear:2026, meetingDateISO:'2026-09-30', meetingDecision:'APPROVED', actionStatus:'Overdue',
        followUps:[task('T1','Open','andreas.huber1@zf-lifetec.com','Andreas Huber','Sales','2027-01-01'),
                   task('T2','Overdue','Robert Nieczyporuk','Robert Nieczyporuk','','2026-12-01')]});
      applySnapshot({cases:[c], autoLog:[{id:'L1', when:'Dec 20, 12:42 AM', trigger:'Overdue by 19 days', swatId:'SWAT-A', taskId:'T2', task:'t T2',
        to:'x@example.com', cc:'', channel:'Email + Teams', delivery:{email:'skipped', teams:'skipped'}}]});
      return JSON.parse(JSON.stringify(c));
    });
    await goTo(page, 'followups');
    // 状态筛选与同排写法一致；负责人统一显示全名，筛选也按全名
    assert.deepEqual(await page.locator('#fFollowupStatus option').allTextContents(), ['Status: Open + Overdue','Open','Overdue','Closed','Status: All']);
    const owners = await page.locator('tr[data-task-row] td:nth-child(4)').allInnerTexts();
    assert.ok(owners[0].startsWith('Robert Nieczyporuk') && owners[1].startsWith('Andreas Huber\nSales'), owners.join(' | '));
    assert.deepEqual(await page.locator('#fFollowupOwner option').allTextContents(), ['Owner: All','Andreas Huber','Robert Nieczyporuk']);
    // 行内编辑：保存只发这一条
    await page.locator('[data-task-edit="T1"]').first().click();
    assert.equal(await page.locator('#teOwner_T1').inputValue(), 'andreas.huber1@zf-lifetec.com');
    await page.locator('#teTask_T1').fill('Track cost recovery with MB (65K EUR)');
    await page.locator('#teChannel_T1').selectOption('Email');
    await page.locator('[data-task-save="T1"]').click();
    await page.waitForFunction(()=>!state.followupEditId);
    assert.equal(puts.length, 1);
    assert.equal(puts[0].path, '/api/tasks/T1');
    assert.deepEqual(puts[0].body, {task:'Track cost recovery with MB (65K EUR)', tags:[], responsible:'andreas.huber1@zf-lifetec.com', ownerFunction:'Sales',
      dueDate:'2027-01-01', status:'Open', channel:'Email', notifyEmail:'x@example.com', cc:'', notes:''});
    assert.ok((await page.locator('#app').innerText()).includes('Track cost recovery with MB (65K EUR)'));
    // 从自动提醒日志打开：筛选藏起来的待办也能改（日志里的 Edit 清掉筛选）
    await page.locator('#fFollowupStatus').selectOption('Open');
    assert.equal(await page.locator('#teTask_T2').count(), 0);
    await page.locator('[data-log-edit="T2"]').click();
    assert.equal(await page.locator('#fFollowupStatus').inputValue(), 'all');
    assert.equal(await page.locator('#teTask_T2').inputValue(), 't T2');
    // 换成已知职能的人：职能自动带出
    await page.locator('#teOwner_T2').fill('andreas.huber1@zf-lifetec.com');
    await page.locator('#teOwner_T2').press('Tab');
    assert.equal(await page.locator('#teFunc_T2').inputValue(), 'Sales');
    // 开放的待办没有收件邮箱：前端先拦住，不发请求，已填内容不丢
    await page.locator('#teEmail_T2').fill('');
    await page.locator('[data-task-save="T2"]').click();
    assert.ok((await page.locator('#teErr_T2').innerText()).includes('Send reminder to'));
    assert.equal(puts.length, 1);
    assert.equal(await page.locator('#teOwner_T2').inputValue(), 'andreas.huber1@zf-lifetec.com');
    await page.locator('[data-task-edit="T2"]').last().click();  // Cancel
    assert.equal(await page.locator('#teTask_T2').count(), 0);
    // Dashboard 按负责人统计也用全名
    await goTo(page, 'dashboard');
    const ownerBars = await page.evaluate(()=>{
      const card=[...document.querySelectorAll('.breakdown-card')].find(el=>el.querySelector('h4').textContent==='Overdue actions by owner');
      return [...card.querySelectorAll('.bar-row')].map(r=>r.querySelector('.blabel').textContent);
    });
    assert.deepEqual(ownerBars, ['Robert Nieczyporuk']);
    await context.close();
  });

  // v3 Phase-30：零件号表格 —— 从委员会 Excel 粘贴、键盘、Fill all、按格子标红
  await test('Part numbers are entered in an Excel-like table: paste from the committee Excel, keyboard, fill all, cell checks', async()=>{
    let submitted;
    const {page, context} = await fixture({user:'user', api:async(route,path)=>{
      if(path!=='/api/submissions') return false;
      submitted = route.request().postDataJSON();
      await route.fulfill({json:{subId:'SUB-GRID',snapshot:empty}});
      return true;
    }});
    await goTo(page, 'submit');
    // 数字读法：带单位 / 第二种货币取表单币种那个；有两种读法的不猜
    const reads = await page.evaluate(()=>[
      ['0,0865 Euro/pc\n0,0952 USD/pc', {}], ['0,0865 Euro/pc\n0,0952 USD/pc', {currency:'USD'}], ['1.234,56', {}], ['1,234.56', {}],
      ['3.796.085', {integer:true}], ['378.979', {integer:true}], ['39,157 Euro\n325.000 RMB', {}], ['110.273 EUR 121.300 USD', {}],
      ['tbd', {}], ['0,56 RMB/pc', {}], ['391K Euro', {}], ['0.02532', {}], ['10.50', {}], ['0,2108 Euro/pc\n1,75 RMB/pc\n (Q2/25 RM index)', {}],
      ['', {}], ['1,5', {integer:true}], ['00,7089 Euro/pc', {}], ['101266Euro\n850000 RMB', {}],
    ].map(([t,o])=>parseGridNumber(t,o)));
    assert.deepEqual(reads.map(r=>r.error ? (r.choices ? r.choices : 'error') : r.value), [
      '0.0865', '0.0952', '1234.56', '1234.56', 3796085, 378979, ['39.157','39157'], ['110.273','110273'],
      'error', 'error', 'error', 'error', '10.50', '0.2108', null, 'error', '0.7089', '101266']);
    assert.ok(reads[9].error.includes('is in CNY') && reads[10].error.includes('K / Mio') && reads[11].error.includes('4 decimal places'), JSON.stringify(reads));
    assert.deepEqual(await page.evaluate(()=>parseClipboardTable('"a\nb"\tc\r\nd\t"x""y"\r\n\r\n')), [['a\nb','c'],['d','x"y']]);
    assert.deepEqual(await page.evaluate(()=>['New part','Carry over','GCS','Rebid',''].map(normalizeSourcingType)), ['New','C/O','GCS',null,'']);

    // 委员会 MM 表（KW39 写法）连同表头复制：按表头对列，其他列跳过；Supplier 是合并格，下面几行为空
    const q = c=> /[\t\n"]/.test(String(c)) ? '"'+String(c).replace(/"/g,'""')+'"' : String(c);
    const tsv = rows=> rows.map(r=>r.map(q).join('\t')).join('\r\n')+'\r\n';
    const header = ['#','Region','Type','Project/ Product','Commodity','Parent PF Code','SWAT ID / Bundle ID','Part Description','PN','Recommended Supplier (s)','Presenter','Decision Level',
      'Peak Year Spend\nEuro','LT Spend\nEuro','Comment','Sourcing Decision ','Notes/Task/ Resp./ Due Date','CQA PC PRICE','Rec. Supplier Landed','Average Volume','LT volume',
      'Average Year Saving vs CQA','LT saving','CQA Tooling','Rec. Supplier Tooling ','Tooling Saving vs CQA'];
    const committee = [header,
      ['1','EU, NA','New','MBEAL','CH01','CH01016\nMedium Precision','B/2025/00361\n110000034017','ECU Housing, WMS','R003B136A','Ningbo Deke','Sandra Novegil','L2','439K Euro','2,5Mio Euro','1. note','Approved','',
        '0,64 Euro/pc','0,74 Euro/pc','378979','3410814','37897.9','341081.4','277000','4352','-272648'],
      ['','','New part','MBEAL','CH01','CH01016','B/2025/00361\n110000034018','ECU Housing, w/o WMS','R003H147A','','','','139K Euro','873K Euro','','','',
        '0,64 Euro/pc','tbd','165280','1322241','','','39,157 Euro\n325.000 RMB','138908',''],
      ['','','Carry over','MBEAL\nFamily 8','CH01','CH01016','B/2025/00361\n110000034019','ECU Cover','R004D369A, R004D370A','','','','139K Euro','852K Euro','','','',
        '0,12 Euro/pc','0,18 Euro/pc','525.895','4733055','','','0','49529','']];
    const paste = (selector, text)=> page.evaluate(([sel,t])=>{
      const el = document.querySelector(sel), dt = new DataTransfer();
      dt.setData('text/plain', t); el.focus();
      el.dispatchEvent(new ClipboardEvent('paste', {clipboardData:dt, bubbles:true, cancelable:true}));
    }, [selector, text]);
    await paste('#pnPartNumber_0', tsv(committee));
    const v = id=> page.locator('#'+id).inputValue();
    const bad = id=> page.locator('#'+id).evaluate(el=>el.classList.contains('pn-bad'));
    assert.equal(await page.locator('[data-pn-grid="submit"] tbody tr').count(), 3);
    assert.deepEqual([await v('pnSourcingType_0'), await v('pnSourcingType_1'), await v('pnSourcingType_2')], ['New','New','C/O']);
    assert.deepEqual([await v('pnProject_2'), await v('pnPartDescription_1'), await v('pnSupplier_1'), await v('pnSupplier_2')], ['MBEAL Family 8','ECU Housing, w/o WMS','Ningbo Deke','Ningbo Deke']);
    assert.deepEqual([await v('pnPcPriceCQA_0'), await v('pnAvgVolume_2'), await v('pnLtVolume_0'), await v('pnSupplierToolingCost_1')], ['0.64','525895','3410814','138908']);
    assert.deepEqual([await bad('pnSupplierPriceLanded_1'), await bad('pnToolingCQA_1'), await bad('pnPartNumber_2'), await bad('pnPcPriceCQA_0')], [true, true, true, false]);
    assert.equal(await v('pnSupplierPriceLanded_1'), 'tbd');
    const msg = await page.locator('[data-pn-grid="submit"] .pn-grid-msg').innerText();
    assert.ok(msg.includes('Pasted 3 rows (columns matched by their header)') && msg.includes('not used') && msg.includes('3 cells need a look'), msg);
    assert.ok(msg.includes('Row 2 · Tooling CQA: "39,157 Euro 325.000 RMB" has several') || msg.includes('Row 2 · Tooling CQA'), msg);
    assert.equal(await page.locator('.pn-count').textContent(), '3 part numbers');
    // 有两种读法：点选一个；其他红格改掉后自动变回正常
    await page.locator('[data-pn-pick="pnToolingCQA_1"][data-value="39157"]').click();
    assert.deepEqual([await v('pnToolingCQA_1'), await bad('pnToolingCQA_1')], ['39157', false]);
    await page.locator('#pnSupplierPriceLanded_1').fill('0,66');
    await page.locator('#pnPartNumber_2').fill('R004D369A');
    assert.deepEqual([await bad('pnSupplierPriceLanded_1'), await bad('pnPartNumber_2')], [false, false]);

    // Enter 往下，最后一行再按 Enter 加一行（带上一行的项目 / 类型 / 供应商），× 删行
    await page.locator('#pnPcPriceCQA_2').press('Enter');
    assert.equal(await page.evaluate(()=>document.activeElement.id), 'pnPcPriceCQA_3');
    assert.deepEqual([await v('pnSupplier_3'), await v('pnSourcingType_3')], ['Ningbo Deke','C/O']);
    await page.locator('#pnPcPriceCQA_3').press('Shift+Enter');
    assert.equal(await page.evaluate(()=>document.activeElement.id), 'pnPcPriceCQA_2');
    await page.locator('#pnPartNumber_3').locator('xpath=ancestor::tr').locator('.pn-remove').click();
    assert.equal(await page.locator('[data-pn-grid="submit"] tbody tr').count(), 3);
    // Fill all：把第 1 行的值填到所有行
    await page.locator('#pnProject_0').fill('MBEAL');
    await page.locator('[data-pn-fill="project"]').click();
    assert.equal(await v('pnProject_2'), 'MBEAL');
    // 重复零件号：标黄提示，不拦
    await page.locator('#pnPartNumber_2').fill('r003b136a');
    assert.ok(await page.locator('#pnPartNumber_0.pn-dup').count() && await page.locator('#pnPartNumber_2.pn-dup').count());
    assert.ok((await page.locator('[data-pn-grid="submit"] .pn-grid-msg').innerText()).includes('R003B136A is in rows 1, 3'));
    await page.locator('#pnPartNumber_2').fill('R004D369A');
    assert.equal(await page.locator('.pn-dup').count(), 0);

    // 提交：缺项在格子上标红，并说是哪一行
    await page.locator('#pnPartDescription_1').fill('');
    for(const [id,value] of Object.entries({fExistingSwat:'B/2025/00361', fBundlePeak:'10', fBundleLife:'20'})) await page.locator('#'+id).fill(value);
    await page.locator('#fRegionIn input[value="EU"]').check();
    await page.locator('#qFamily').selectOption('No');
    await page.locator('#qECM').selectOption('No');
    await fillCommercial(page);
    await page.locator('#submitCaseBtn').click();
    await page.waitForFunction(()=>document.getElementById('submitBanner')?.textContent.includes('Missing in row 2 (marked red)'));
    assert.equal(submitted, undefined);
    assert.ok(await page.locator('#pnPartDescription_1.pn-missing').count());
    await page.locator('#pnPartDescription_1').fill('ECU Housing, w/o WMS');
    assert.equal(await page.locator('.pn-missing').count(), 0);
    await page.locator('#submitCaseBtn').click();
    await page.waitForFunction(()=>document.getElementById('submitBanner')?.textContent.includes('SUB-GRID'));
    assert.deepEqual(submitted.partNumbers.map(r=>[r.sourcingType, r.project, r.partNumber, r.recommendedSupplier, r.supplierPriceLanded, r.toolingCQA, r.averageVolume, r.lifetimeVolume]), [
      ['New','MBEAL','R003B136A','Ningbo Deke','1.1','120000',378979,3410814],
      ['New','MBEAL','R003H147A','Ningbo Deke','0.66','39157',165280,1322241],
      ['C/O','MBEAL','R004D369A','Ningbo Deke','0.18','0',525895,4733055]]);
    await context.close();

    // 编辑页：同一个表格；没改过的原值（1.125）不拦，新填的歧义值拦下保存；不带表头的粘贴从光标所在格往右填
    let saved, puts = 0;
    const view = await fixture({api:async(route,path)=>{
      if(path==='/api/bootstrap'){ await route.fulfill({json:{...empty, currentUser:ADMIN}}); return true; }
      if(path==='/api/cases/C-TEST' && route.request().method()==='PUT'){ puts++; saved = route.request().postDataJSON(); await route.fulfill({json:{ok:true, case:{}, snapshot:empty}}); return true; }
      return false;
    }});
    await seed(view.page, {partNumbers:[{partNumber:'PN1', partDescription:'Spool', project:'MBEAL', sourcingType:'', recommendedSupplier:'Supplier A',
      pcPriceCQA:1.125, supplierPriceLanded:1, toolingCQA:0, supplierToolingCost:0, averageVolume:1000, lifetimeVolume:null}], sourcingType:'', spendCurrency:'EUR'});
    await view.page.evaluate(()=>goToDetail('SWAT-TEST'));
    await view.page.locator('#editCaseBtn').click();
    const ev = id=> view.page.locator('#'+id).inputValue();
    assert.deepEqual([await ev('editPnPcPriceCQA_0'), await ev('editPnSourcingType_0')], ['1.125', '']);
    await view.page.locator('#editPnToolingCQA_0').fill('39,157');
    await view.page.locator('#saveCaseBtn').click();
    await view.page.waitForFunction(()=>document.querySelector('.block-warning')?.textContent.includes('Row 1 · Tooling CQA'));
    assert.equal(puts, 0);
    assert.ok(await view.page.locator('#editPnToolingCQA_0.pn-bad').count(), 'still red after the editor re-renders');
    await view.page.evaluate(([sel,t])=>{
      const el = document.querySelector(sel), dt = new DataTransfer();
      dt.setData('text/plain', t); el.focus();
      el.dispatchEvent(new ClipboardEvent('paste', {clipboardData:dt, bubbles:true, cancelable:true}));
    }, ['#editPnPartDescription_0, #editPnDesc_0', 'Spool\tPN1\tSupplier A\r\nCover\tPN2\tSupplier B\t0,6\r\n']);
    assert.deepEqual([await ev('editPnDesc_1'), await ev('editPnNumber_1'), await ev('editPnSupplier_1'), await ev('editPnPcPriceCQA_1'), await ev('editPnPcPriceCQA_0')],
      ['Cover','PN2','Supplier B','0.6','1.125']);
    await view.page.locator('#editPnToolingCQA_0').fill('39157');
    await view.page.locator('#saveCaseBtn').click();
    await view.page.waitForFunction(()=>!document.getElementById('saveCaseBtn'));
    assert.deepEqual(saved.partNumbers.map(r=>[r.partNumber, r.sourcingType, r.pcPriceCQA, r.toolingCQA, r.averageVolume, r.lifetimeVolume]),
      [['PN1','','1.125','39157',1000,null], ['PN2','','0.6',null,null,null]]);
    assert.ok(saved.partNumbers.every(r=>!('_ok' in r)));
    await view.context.close();
  });

  // v3 Phase-31：Case Comments 单独一块；提交人本人与经理 / 管理员可改，单独保存，Edit Case 里没保存的内容不丢。
  // 普通用户能不能改由服务端回答（页面拿不到提交人邮箱），经理 / 管理员不用问
  await test('Case Comments have their own card that the submitter and managers can edit', async()=>{
    let seeded = null, sent = null, canEdit = true;
    const asked = [];
    const api = async(route,path)=>{
      if(path==='/api/cases/C-TEST/comments/access'){ asked.push(path); await route.fulfill({json:{canEdit}}); return true; }
      if(path!=='/api/cases/C-TEST/comments') return false;
      sent = {method:route.request().method(), body:route.request().postDataJSON()};
      await route.fulfill({json:{ok:true, snapshot:{...empty, cases:[{...seeded, submitterComments:sent.body.comments,
        submitterCommentsEdited:{by:'Test owner', when:'Dec 20, 7:00 AM'}}]}}});
      return true;
    };
    const mine = await fixture({user:'user', api});
    seeded = await seed(mine.page, {committeeDiscussion:'Pending for Sourcing Committee Review'});
    await mine.page.evaluate(()=>goToDetail('SWAT-TEST'));
    const card = mine.page.locator('.section-card', {has: mine.page.locator('h3', {hasText:'Case Comments'})});
    assert.match(await card.innerText(), /No comments yet\./);
    await mine.page.locator('#caseCommentsEdit').click();  // 服务端答"能"之后按钮才出现
    await mine.page.locator('#caseCommentsIn').fill('No tooling budget available. CO current supplier Getac.');
    assert.equal(await mine.page.evaluate(()=>canRefresh()), false);  // 输入中不被每小时刷新冲掉
    await mine.page.locator('#caseCommentsSave').click();
    await mine.page.waitForFunction(()=>!document.getElementById('caseCommentsIn'));
    assert.deepEqual(sent, {method:'PUT', body:{comments:'No tooling budget available. CO current supplier Getac.'}});
    assert.match(await card.innerText(), /No tooling budget available\. CO current supplier Getac\.\s+Last edited by Test owner · Dec 20, 7:00 AM/);
    assert.equal(await mine.page.locator('#caseCommentsEdit').innerText(), 'Edit comments');
    // 会议讨论那一块不受影响
    assert.match(await mine.page.locator('.section-card', {has: mine.page.locator('h3', {hasText:/^Committee Discussion/})}).innerText(), /Pending for Sourcing Committee Review/);
    await mine.context.close();

    assert.equal(asked.length, 1);  // 同一账号同一案例只问一次

    // 别人登记的案例：普通用户只能看，没有编辑按钮
    canEdit = false;
    const other = await fixture({user:'user', api});
    await seed(other.page, {submitterComments:'Background'});
    await other.page.evaluate(()=>goToDetail('SWAT-TEST'));
    await other.page.waitForFunction(()=>Object.values(commentAccess).includes(false));
    assert.equal(await other.page.locator('#caseCommentsEdit').count(), 0);
    assert.match(await other.page.locator('#app').innerText(), /Background/);
    await other.context.close();

    // 管理员在 Edit Case 打开时改 Case Comments：单独保存，编辑页里没保存的会议讨论还在
    const admin = await fixture({user:'admin', api});
    seeded = await seed(admin.page, {submitterComments:'Old'});
    asked.length = 0;
    await admin.page.evaluate(()=>goToDetail('SWAT-TEST'));
    await admin.page.locator('#editCaseBtn').click();
    await admin.page.locator('#editDiscussion').fill('Typed but not saved');
    await admin.page.locator('#caseCommentsEdit').click();
    assert.equal(await admin.page.locator('#caseCommentsIn').inputValue(), 'Old');
    await admin.page.locator('#caseCommentsIn').fill('New background');
    await admin.page.locator('#caseCommentsSave').click();
    await admin.page.waitForFunction(()=>!document.getElementById('caseCommentsIn'));
    assert.equal(sent.body.comments, 'New background');
    assert.equal(await admin.page.locator('#editDiscussion').inputValue(), 'Typed but not saved');
    assert.equal(await admin.page.evaluate(()=>state.detailEditMode), true);
    assert.deepEqual(asked, []);
    await admin.context.close();
  });

  // ===== v3 Phase-40：领导 2026-10-29 "follow up actions 可不可以更突出 task，也表格化一下"，"大部分都是显示邮箱地址去了" =====
  await test('Case detail lists follow-ups as a compact table in minutes order; a row expands to the reminder, notes and feedback', async()=>{
    const fb = {id:'FB-1', when:'Oct 28, 9:00 AM', by:'Test owner', text:'QAF received for EU and NA', files:[], status:'pending', notify:{to:'npi@zf.com', result:'sent'}, decision:null};
    const {page, context} = await fixture({user:'manager'});
    await seed(page,{meetingDecision:'CONDITIONAL APPROVAL', actionStatus:'Overdue', followUps:[
      {id:'FU-1', task:'1. Check PPAP samples', responsible:'SP ABC', ownerFunction:'Purchasing', dueDate:'2026-10-09', status:'Closed', tags:[], notifyEmail:'sp@example.com',
        closure:{when:'Oct 9, 9:05 AM', by:'NPI Person', feedbackId:'FB-0'}, feedback:[{...fb, id:'FB-0', status:'approved'}]},
      {id:'FU-2', task:'2. Get QAF and CAPA from the supplier', responsible:'Q Lee', dueDate:'2026-10-20', status:'Overdue', tags:['Quality'], notes:'All three locations',
        notifyEmail:'q.lee@example.com', cc:'cc.one@example.com, cc.two@example.com', channel:'Email', feedback:[fb]},
      {id:'FU-3', task:'3. Negotiate the price', responsible:'R Wu', dueDate:'2027-01-15', status:'Open', tags:[], notifyEmail:''}]});
    await page.evaluate(()=>goToDetail('SWAT-TEST'));
    // 一行一条、按纪要编号顺序；收起时不显示任何邮箱
    assert.deepEqual(await page.locator('tr.task-row .task-title').allTextContents(), ['1. Check PPAP samples','2. Get QAF and CAPA from the supplier','3. Negotiate the price']);
    assert.equal(await page.locator('tr.task-detail').count(), 0);
    assert.ok(!(await page.locator('#app').innerText()).includes('@example.com'));
    const row = id => page.locator(`tr[data-task-expand="${id}"]`);
    assert.equal(await row('FU-1').locator('.task-owner').innerText(), 'SP ABC\nPurchasing');
    assert.deepEqual(await row('FU-1').locator('.task-chips > *').allTextContents(), ['CQA','1 update']);
    assert.deepEqual(await row('FU-2').locator('.task-chips > *').allTextContents(), ['CQA','1 to approve']);
    assert.deepEqual(await row('FU-3').locator('.task-chips > *').allTextContents(), ['Saving']);
    assert.equal(await row('FU-2').locator('td.task-due.due-overdue').innerText(), '2026-10-20');
    assert.deepEqual(await page.locator('tr.task-row .task-status').allInnerTexts(), ['Closed','Overdue','Open']);
    // 点行展开：收件人、抄送、通道、标签、备注、反馈审批都在里面；可以同时展开几行
    await row('FU-2').locator('.task-owner').click();
    const detail2 = await page.locator('#taskDetail_FU-2').innerText();
    assert.ok(detail2.includes('Reminder to\nq.lee@example.com · CC cc.one@example.com, cc.two@example.com · Email'), detail2);
    assert.ok(detail2.includes('Tags\nQuality') && detail2.includes('Notes\nAll three locations') && detail2.includes('Awaiting approval'), detail2);
    assert.equal(await page.locator('#taskDetail_FU-2 [data-decision-open="FB-1"]').count(), 1);
    assert.equal(await page.locator('[data-task-toggle="FU-2"]').getAttribute('aria-expanded'), 'true');
    await page.locator('[data-task-toggle="FU-3"]').click();
    assert.equal(await page.locator('tr.task-detail').count(), 2);
    assert.ok((await page.locator('#taskDetail_FU-3').innerText()).includes('no email on file'));
    // 展开区里的按钮不会把行收起来；用键盘收起时一并关掉打开的汇报表单，焦点留在箭头上
    await page.locator('[data-feedback-open="FU-3"]').click();
    assert.equal(await page.locator('#taskDetail_FU-3 #fbText_FU-3').count(), 1);
    await page.locator('[data-task-toggle="FU-3"]').focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('#taskDetail_FU-3').count(), 0);
    assert.equal(await page.evaluate(()=>state.feedbackOpenId), null);
    assert.equal(await page.evaluate(()=>document.activeElement?.dataset.taskToggle), 'FU-3');
    assert.equal(await page.locator('[data-task-toggle="FU-3"]').getAttribute('aria-expanded'), 'false');
    // 手机宽度：不左右滑，负责人 / 截止日 / 状态排在任务下面
    await page.setViewportSize({width:390, height:800});
    const fit = await page.evaluate(()=>{
      const wrap = document.querySelector('.task-table-wrap');
      const title = document.querySelector('tr[data-task-expand="FU-2"] .task-title').getBoundingClientRect();
      const due = document.querySelector('tr[data-task-expand="FU-2"] .task-due').getBoundingClientRect();
      return {inner: wrap.scrollWidth<=wrap.clientWidth, page: document.documentElement.scrollWidth<=window.innerWidth, below: due.top>=title.bottom};
    });
    assert.deepEqual(fit, {inner:true, page:true, below:true});
    await context.close();
  });

  console.log(`${passed} frontend regression checks passed.`);
}finally{
  await browser.close();
}
