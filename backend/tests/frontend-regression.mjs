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
const empty = {cases:[], submissions:[], autoLog:[], serverTimezone:'America/New_York'};
// v3 Phase-6 个人账号：bootstrap 的 currentUser 决定页面权限（服务端另行强制）
const USER = {email:'test.user@zf.com', name:'Test owner', role:'user', roleLabel:'User', disabled:false, mustChangePassword:false, createdAt:'Sep 24, 9:00 AM', lastLoginAt:'Sep 24, 9:05 AM'};
const MANAGER = {...USER, email:'npi@zf.com', name:'NPI Person', role:'npi_manager', roleLabel:'Manager'};
const ADMIN = {...USER, email:'admin@zf.com', name:'Sourcing Admin', role:'admin', roleLabel:'Sourcing admin'};
const USERS = {user:USER, manager:MANAGER, admin:ADMIN};
const errors = [];
let passed = 0;

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
  for(const timezoneId of ['Asia/Taipei','America/New_York','Europe/Berlin']){
    await test('Wednesday calendar values and next-year labels in '+timezoneId, async()=>{
      const {page, context} = await fixture({timezoneId, user:'user'});
      await page.locator('[data-nav="submit"]').click();
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
    await page.locator('[data-nav="submit"]').click();
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
    await page.locator('[data-nav="submit"]').click();
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
    await page.locator('[data-nav="submit"]').click();
    assert.equal(await page.locator('#fCurrency').inputValue(),'EUR');
    await page.locator('#fCurrency').selectOption('USD');
    const curLabels = await page.locator('.cur-label').allTextContents();
    assert.ok(curLabels.length>=2 && curLabels.every(t=>t==='USD'), curLabels);  // 支出行与商务字段的币种标签一起切换
    assert.match(await page.locator('#fxHint').textContent(),/1 EUR = 1\.25 USD \(OP 2026\)/);
    for(const [id,value] of Object.entries({fExistingSwat:'SWAT-1002',pnSupplier_0:'Test supplier',pnProject_0:'MBEAL',pnPartNumber_0:'1234',pnPartDescription_0:'Test part',
      fBundlePeak:'139000',fBundleLife:'873000'})){
      await page.locator('#'+id).fill(value);
    }
    assert.equal(await page.locator('#totalPeakDisplay').textContent(),'$139,000 ≈ €111,200');  // 1 EUR = 1.25 USD，按除法
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
    await page.locator('[data-nav="dashboard"]').click();
    const card = await page.locator('#app').innerText();
    assert.ok(card.includes('1 EUR = ? USD') && card.includes('1 EUR = ? CNY'), card);
    await page.locator('#fxBasis').fill('OP 2025 plan rates 2026');
    await page.locator('#fxRateUSD').fill('1.17');
    await page.locator('#fxSave').click();
    await page.waitForFunction(()=>document.getElementById('fxMsg')?.textContent.includes('Saved'));
    assert.deepEqual(saved,{basis:'OP 2025 plan rates 2026', perEur:{USD:'1.17', CNY:null}});
    assert.equal(await page.locator('#fxRateUSD').inputValue(),'1.17');
    // 提交页提示与预览按除法：117 USD ≈ €100
    await page.locator('[data-nav="submit"]').click();
    await page.locator('#fCurrency').selectOption('USD');
    assert.match(await page.locator('#fxHint').textContent(),/1 EUR = 1\.17 USD \(OP 2025 plan rates 2026\)/);
    await page.locator('#fBundlePeak').fill('117');
    assert.equal(await page.locator('#totalPeakDisplay').textContent(),'$117 ≈ €100');
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
    await page.locator('[data-nav="submit"]').click();
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
    await page.locator('[data-nav="submit"]').click();
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
    await page.locator('#submitCaseBtn').click();
    await banner('SUB-TEST');
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

  await test('Registration deadline follows admin settings and late registrations need an exception with a reason', async()=>{
    // 固定时间 2026-12-20（周日）12:00Z。默认规则：周一 23:59 —— 本周三 12/23 仍开放，没有例外入口
    const plain = await fixture({user:'user'});
    await plain.page.locator('[data-nav="submit"]').click();
    assert.equal(await plain.page.locator('#fMeetingDate option').first().getAttribute('value'),'2026-12-23');
    assert.equal(await plain.page.locator('#fLateException').count(),0);
    assert.ok((await plain.page.locator('#app').innerText()).includes('Registrations close Monday 23:59 (America/New_York)'));
    await plain.context.close();

    // 管理员规则：会前 5 天 18:00 柏林时间 = 周五 12/18 18:00，已过 → 最早只能选 12/30，可申请例外登记 12/23
    let submitted, savedSettings;
    const registrationSettings = {daysBefore:5, cutoffTime:'18:00', timezone:'Europe/Berlin', updatedAt:'Dec 1, 9:00 AM'};
    const {page, context} = await fixture({api:async(route,path)=>{
      if(path==='/api/bootstrap'){ await route.fulfill({json:{...empty, registrationSettings, currentUser:ADMIN}}); return true; }
      if(path==='/api/registration-settings'){ savedSettings = route.request().postDataJSON(); await route.fulfill({json:{ok:true, snapshot:{...empty, registrationSettings:{...savedSettings, updatedAt:'now'}}}}); return true; }
      if(path!=='/api/submissions') return false;
      submitted = route.request().postDataJSON();
      await route.fulfill({json:{subId:'SUB-LATE',snapshot:empty}});
      return true;
    }});
    await page.locator('[data-nav="submit"]').click();
    assert.equal(await page.locator('#fMeetingDate option').first().getAttribute('value'),'2026-12-30');
    assert.ok((await page.locator('#app').innerText()).includes('Registrations close Friday 18:00 (Europe/Berlin)'));
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
    await page.evaluate(()=>{ applySnapshot({submissions:[{subId:'SUB-LATE', status:'Waiting for Registration Confirmation', submitterName:'Test owner', submitterEmail:'t@example.com',
      submittedAt:'Dec 20, 2026 7:00 AM', partNumber:'1234', partDescription:'Test part', caseId:'SWAT-1004', region:'EU', meetingDateLabel:'Wed, Dec 23, 2026',
      lateRegistration:{reason:'Customer escalation', deadline:'Fri, Dec 18, 2026 18:00 (Europe/Berlin)'}}]}); });
    await page.locator('[data-nav="approvals"]').click();
    const approvals = await page.locator('#app').innerText();
    assert.ok(approvals.includes('Late registration — exception requested'), approvals);
    assert.ok(approvals.includes('Customer escalation'));
    await page.locator('[data-nav="dashboard"]').click();
    assert.ok((await page.locator('#app').innerText()).includes('Friday 18:00 (Europe/Berlin)'));
    await page.locator('#regDaysBefore').selectOption('1');
    await page.locator('#regCutoffTime').fill('17:30');
    await page.locator('#regTimezone').fill('');
    await page.locator('#regSave').click();
    await page.waitForFunction(()=>document.getElementById('regMsg')?.textContent.includes('Saved'));
    assert.deepEqual(savedSettings,{daysBefore:1, cutoffTime:'17:30', timezone:''});
    assert.ok((await page.locator('#app').innerText()).includes('Tuesday 17:30 (America/New_York)'));
    await context.close();
  });

  await test('Follow-up categories are a fixed set of eight, legacy tags stay visible, and the filter lists every category', async()=>{
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
    assert.ok((await page.locator('#app').innerText()).includes('Categories\nCost'));
    await page.locator('#editCaseBtn').click();
    const labels = await page.locator('#editFuCat_0 label').allTextContents();
    assert.deepEqual(labels.map(l=>l.trim()), ['CQA','Volume','Technical','Timing','Supplier strategy','BPG','Saving','Further VAVE','Cost (legacy)']);
    assert.ok(await page.locator('#editFuCat_0 input[value="Cost"]').isChecked());
    await page.locator('#editFuCat_0 input[value="Saving"]').check();
    await page.locator('#editFuCat_0 input[value="Further VAVE"]').check();
    await page.locator('#saveCaseBtn').click();
    await page.waitForFunction(()=>!state.detailEditMode);
    assert.deepEqual(saved.followUps[0].tags, ['Saving','Further VAVE','Cost']);
    // Follow-ups 页：八个分类始终在筛选里，旧标签跟在后面
    await seed(page,{meetingDecision:'APPROVED', actionStatus:'Open',
      followUps:[{id:'FU-T1', task:'Negotiate consignment', responsible:'SP ABC', dueDate:'2027-02-18', status:'Open', tags:['Cost'], notifyEmail:'sp@example.com'}]});
    await page.locator('[data-nav="followups"]').click();
    const options = await page.locator('#fFollowupTag option').allTextContents();
    assert.deepEqual(options, ['Category: All','CQA','Volume','Technical','Timing','Supplier strategy','BPG','Saving','Further VAVE','Cost']);
    await page.locator('#fFollowupTag').selectOption('Saving');
    assert.ok((await page.locator('#app').innerText()).includes('0 open tasks'));
    await page.locator('#fFollowupTag').selectOption('Cost');
    assert.ok((await page.locator('#app').innerText()).includes('1 open task'));
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
    await page.locator('[data-nav="dashboard"]').click();
    const bars = await page.evaluate(()=>{
      const card=[...document.querySelectorAll('.breakdown-card')].find(el=>el.textContent.includes('by Region'));
      return {rows:[...card.querySelectorAll('.bar-row')].map(r=>r.querySelector('.blabel').textContent+'='+r.querySelector('.bar-num').textContent),
        note:!!card.querySelector('.breakdown-note')};
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
    await page.locator('[data-nav="database"]').click();
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

  await test('Wrong login password leaves a usable error panel', async()=>{
    const {page,context} = await fixture({api:async(route,path)=>{
      if(path!=='/api/auth/login') return false;
      await route.fulfill({status:401,json:{detail:'Wrong email or password.'}});
      return true;
    }});
    await page.locator('#adminToggle').click();
    await page.locator('#adminEmailInput').fill('test.user@zf.com');
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
    await page.locator('#adminPasswordInput').fill('test');
    await page.locator('#adminPasswordInput').press('Enter');
    await page.locator('#adminPasswordInput').press('Enter');
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
      if(path==='/api/auth/login'){ await route.fulfill({json:{ok:true, token:'memory-token', user:USER}}); return true; }
      if(path==='/api/auth/password'){ await route.fulfill({json:{ok:true, user:USER}}); return true; }
      return false;
    }});
    await page.locator('[data-nav="submit"]').click();
    await page.locator('#submitLoginBtn').click();  // 提交页的登录门槛打开登录面板
    await page.locator('#adminEmailInput').fill('test.user@zf.com');
    await page.locator('#adminPasswordInput').fill('user-pass-123');
    await page.locator('#adminLoginBtn').click();
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
    await page.locator('[data-nav="submit"]').click();
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
    await page.locator('#regNameInput').fill('New Buyer');
    await page.locator('#adminEmailInput').fill('New.Buyer@zf-lifetec.com');
    await page.locator('#adminPasswordInput').fill('good-pass-123');
    await page.locator('#adminLoginBtn').click();
    await page.locator('#submitCaseBtn').waitFor();
    assert.deepEqual(registered,{body:{name:'New Buyer', email:'New.Buyer@zf-lifetec.com', password:'good-pass-123'}, token:undefined});
    assert.equal(await page.locator('#adminLoginPanel').count(),0);
    assert.equal(await page.locator('#adminToggle').textContent(),'New Buyer · User');
    assert.equal(await page.evaluate(()=>localStorage.getItem('sc_session_token')),'new-token');
    assert.deepEqual(await page.evaluate(()=>[document.getElementById('fSubmitter').value, document.getElementById('fSubmitterEmail').value]),['New Buyer','new.buyer@zf-lifetec.com']);
    // 普通用户没有 Accounts 页，也进不去
    assert.equal(await page.locator('[data-nav="accounts"]').count(),0);
    assert.equal(await page.evaluate(()=>{ state.view='accounts'; render(); return state.view; }),'home');
    // 登出回到登录门槛
    await page.locator('#adminToggle').click();
    const loggedOut = page.waitForRequest('**/api/auth/logout');
    await page.route('**/api/auth/logout', route=>route.fulfill({json:{ok:true}}));
    await page.locator('#adminLogoutBtn').click();
    await loggedOut;
    await page.locator('[data-nav="submit"]').click();
    assert.equal(await page.locator('#submitLoginGate').count(),1);
    await context.close();
  });

  await test('Accounts page lets the Sourcing admin change roles, disable accounts and reset a password that is shown once', async()=>{
    const calls=[];
    let users=[ADMIN, USER];
    const {page,context} = await fixture({user:'admin', api:async(route,path)=>{
      const method=route.request().method(), p=decodeURIComponent(path);
      if(p==='/api/users' && method==='GET'){ calls.push({p, token:route.request().headers()['x-session-token']}); await route.fulfill({json:{ok:true, users}}); return true; }
      if(p==='/api/users/test.user@zf.com' && method==='PUT'){
        const body=route.request().postDataJSON(); calls.push({p, body});
        users=users.map(u=>u.email==='test.user@zf.com'?{...u,...body, roleLabel:body.role==='npi_manager'?'Manager':u.roleLabel}:u);
        await route.fulfill({json:{ok:true, users}}); return true;
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
    await page.locator('[data-user-disable="test.user@zf.com"]').click();
    await page.waitForFunction(()=>document.querySelector('[data-user-disable="test.user@zf.com"]')?.textContent==='Enable');
    assert.deepEqual(calls[2],{p:'/api/users/test.user@zf.com', body:{disabled:true}});
    assert.ok((await page.locator('#app').innerText()).includes('Disabled'));
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
    await page.locator('[data-nav="submit"]').click();
    assert.equal(await page.locator('#submitLoginGate').count(),1);
    await context.close();
  });

  await test('Delete resets detail selection after the server removes the row', async()=>{
    const {page,context} = await fixture({api:async(route,path)=>{
      if(!path.startsWith('/api/cases/')) return false;
      await route.fulfill({json:{snapshot:empty}});
      return true;
    }});
    await seed(page);
    await page.evaluate(()=>{state.isAdmin=true; API.setSessionToken('test'); goToDetail('SWAT-TEST');});
    await page.locator('[data-delete-ask]').click();
    await page.locator('[data-delete-confirm]').click();
    await page.waitForFunction(()=>state.view==='database');
    assert.deepEqual(await page.evaluate(()=>[state.pendingDeleteId,state.selectedSwatId,state.detailEditMode]),[null,null,false]);
    assert.equal(new URL(page.url()).hash,'');
    await context.close();
  });

  await test('Legacy upload prevents duplicate requests and permits retry after failure', async()=>{
    let requests=0;
    const {page,context} = await fixture({user:'admin', api:async(route,path)=>{
      if(path!=='/api/legacy-upload') return false;
      requests++;
      await route.fulfill({status:500,json:{detail:'Test upload failure'}});
      return true;
    }});
    await page.locator('#dropzone').dblclick();
    await page.waitForFunction(()=>!state.uploading);
    assert.equal(requests,1);
    assert.equal(await page.evaluate(()=>state.uploaded),false);
    assert.equal(await page.locator('#uploadSuccess').isVisible(),false);
    await page.locator('#dropzone').click();
    await page.waitForFunction(()=>!state.uploading);
    assert.equal(requests,2);
    await context.close();
  });

  await test('Navigating away cancels the upload animation safely', async()=>{
    const {page,context} = await fixture({user:'admin'});
    await page.locator('#dropzone').click();
    await page.locator('[data-nav="database"]').click();
    await page.waitForFunction(()=>!state.uploading);
    assert.equal(await page.evaluate(()=>state.view),'database');
    await context.close();
  });

  await test('Exports block formulas hidden behind whitespace and preserve numeric cells', async()=>{
    const {page,context} = await fixture();
    assert.deepEqual(await page.evaluate(()=>[
      formulaGuard('=SUM(A1)'),formulaGuard('  =SUM(A1)'),formulaGuard('\n=SUM(A1)'),
      formulaGuard('\t12'),formulaGuard(-123),formulaGuard('normal')
    ]),["'=SUM(A1)","'  =SUM(A1)","'\n=SUM(A1)","'\t12",'-123','normal']);
    await page.locator('[data-nav="dashboard"]').click();
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
      await route.fulfill({status:200, headers:{'content-disposition':'attachment; filename="Sourcing_Committee_Agenda_2026-KW40.xlsx"'},
        contentType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', body:Buffer.from('PK-fake')});
      return true;
    }});
    await seed(page,{weekNum:40});
    await page.evaluate(()=>{ window.__saved = []; saveBlobFile = async (blob, filename)=>{ window.__saved.push({filename, type:blob.type, size:blob.size}); }; });
    await page.locator('[data-nav="dashboard"]').click();
    await page.locator('[data-period="week"]').click();
    await page.locator('#dashAgendaBtn').click();
    await page.waitForFunction(()=>window.__saved.length===1);
    assert.deepEqual(requested,['/api/exports/agenda?week=40']);
    assert.deepEqual(await page.evaluate(()=>window.__saved),[{filename:'Sourcing_Committee_Agenda_2026-KW40.xlsx', type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', size:7}]);
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
      await route.fulfill({status:200, headers:{'content-disposition':'attachment; filename="Sourcing_Committee_Minutes_Database_2026-12-20.xlsx"'},
        contentType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', body:Buffer.from('PK-fake')});
      return true;
    }});
    await page.evaluate(()=>{
      applySnapshot({cases:[mkCase({id:'C-A', swatId:'SWAT-A', partNumber:'1', partDescription:'A', weekNum:40, caseNumber:1, region:'EU', meetingDecision:'PENDING'}),
                           mkCase({id:'C-B', swatId:'SWAT-B', partNumber:'2', partDescription:'B', weekNum:40, caseNumber:2, region:'NA', meetingDecision:'APPROVED'})]});
      window.__saved = []; saveBlobFile = async (blob, filename)=>{ window.__saved.push({filename}); };
    });
    await page.locator('[data-nav="database"]').click();
    await page.locator('#fRegion').selectOption('NA');
    await page.locator('#dbMinutesBtn').click();
    await page.waitForFunction(()=>window.__saved.length===1);
    assert.deepEqual(posted,[{path:'/api/exports/minutes', method:'POST', body:{ids:['C-B']}}]);
    assert.deepEqual(await page.evaluate(()=>window.__saved),[{filename:'Sourcing_Committee_Minutes_Database_2026-12-20.xlsx'}]);
    await page.locator('#fRegion').selectOption('');
    await page.locator('#dbAgendaBtn').click();
    await page.waitForFunction(()=>window.__saved.length===2);
    assert.deepEqual(posted[1],{path:'/api/exports/agenda', method:'POST', body:{ids:['C-B','C-A']}});  // 表按案例号倒序
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
    await page.locator('[data-nav="followups"]').click();
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
    await viewer.page.locator('[data-nav="followups"]').click();
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
    await page.locator('[data-nav="submit"]').click();
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
    await page.locator('[data-nav="followups"]').click();
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
    await page.locator('[data-nav="submit"]').click();
    await page.locator('#pnSupplier_0').fill('Keep this');
    await page.evaluate(()=>window.testRefresh());
    assert.equal(bootstrapCalls,1);
    assert.equal(await page.locator('#pnSupplier_0').inputValue(),'Keep this');
    await page.locator('[data-nav="database"]').click();
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
        await page.locator(`[data-nav="${view}"]`).click();
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
  console.log(`${passed} frontend regression checks passed.`);
}finally{
  await browser.close();
}
