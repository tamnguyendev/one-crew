// Host-owned acceptance checks. Product workers cannot edit this file.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.ONECREW_PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.ONECREW_BROWSER_CHANNEL || (process.platform==='win32'?'msedge':undefined)});
  try {
    if (process.argv[2]==='--probe') { console.log(JSON.stringify({passed:true,probe:'browser-ready'})); return; }
    const origin=process.argv[2], report=process.argv[3];
    assert.match(origin,/^http:\/\/127\.0\.0\.1:\d+$/);
    const context=await browser.newContext({viewport:{width:1280,height:900}});
    await context.route('**/*', route => new URL(route.request().url()).origin===origin ? route.continue() : route.abort());
    const page=await context.newPage();page.setDefaultTimeout(8000);
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.goto(origin);
    await page.locator('#mode-banner').filter({hasText:/demo/i}).waitFor();
    await page.screenshot({path:path.join(report,'ui-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),true,'Mobile layout overflows');
    await page.screenshot({path:path.join(report,'ui-mobile.png'),fullPage:true});
    await page.locator('#name').fill('Ứng viên kiểm thử');
    await page.locator('#email').fill('ui-test@example.com');
    await page.locator('#role').selectOption({label:'Kỹ sư phần mềm'});
    await page.locator('#consent').check();
    const pdf=Buffer.from('%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n');
    await page.locator('#cv-file').setInputFiles({name:'sample.pdf',mimeType:'application/pdf',buffer:pdf});
    await page.locator('#review-button').click();
    await page.locator('#preview').waitFor({state:'visible'});
    assert.match(await page.locator('#preview-content').innerText(),/ui-test@example.com/);
    await page.locator('#edit-button').click();
    await page.locator('#cv-form').waitFor({state:'visible'});
    assert.equal(await page.locator('#name').inputValue(),'Ứng viên kiểm thử');
    assert.equal(await page.locator('#cv-file').evaluate(el=>el.files.length),1,'Edit discarded selected PDF');
    await page.locator('#name').fill('Ứng viên đã chỉnh sửa');
    await page.locator('#review-button').click();
    await page.locator('#preview').waitFor({state:'visible'});
    assert.match(await page.locator('#preview-content').innerText(),/đã chỉnh sửa/);
    await page.locator('#demo-confirm').check();
    await page.screenshot({path:path.join(report,'ui-preview.png'),fullPage:true});
    const committed=page.waitForResponse(r=>r.url()===origin+'/api/commit' && r.request().method()==='POST');
    await page.locator('#submit-button').click();
    const response=await committed; assert.equal(response.status(),201,'Browser submission failed');
    const body=await response.json(); assert.equal(body.status,'quarantined_unscanned');
    await page.locator('#receipt').waitFor({state:'visible'});
    assert.ok((await page.locator('#receipt').innerText()).includes(body.receipt),'UI receipt differs from server receipt');
    await page.screenshot({path:path.join(report,'ui-receipt.png'),fullPage:true});
    assert.deepEqual(errors,[],'Browser runtime errors');
    console.log(JSON.stringify({passed:true,checks:['responsive layout','preview/edit preserves file','real browser API submission','receipt matches server','no page errors']}));
  } finally { await browser.close(); }
})().catch(error=>{console.log(JSON.stringify({passed:false,error:String(error.message).slice(0,2500)}));process.exitCode=1;});
