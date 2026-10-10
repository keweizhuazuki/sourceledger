// Browser verification for the actual static demo report, with no web server.
const { chromium } = require('playwright');
const { pathToFileURL } = require('node:url');
const { resolve } = require('node:path');
const { mkdir } = require('node:fs/promises');
const assert = require('node:assert/strict');
(async () => {
  await mkdir('screenshots', { recursive: true });
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const requests = [];
    page.on('request', request => requests.push(request.url()));
    await page.goto(pathToFileURL(resolve('docs/example-report.html')).href);
    await page.getByRole('heading', { name: 'SourceLedger', exact: true }).waitFor();
    assert.equal(await page.locator('article').count(), 2);
    assert.match(await page.locator('article').first().innerText(), /14 days/);
    assert.match(await page.locator('article').first().innerText(), /30 days/);
    assert.equal(await page.locator('script').count(), 0);
    assert.deepEqual(errors, []);
    assert.ok(requests.every(url => url.startsWith('file:')), 'Report made a network request');
    await page.screenshot({ path: 'screenshots/report-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Mobile horizontal overflow');
    await page.screenshot({ path: 'screenshots/report-mobile.png', fullPage: true });
    await page.goto(pathToFileURL(resolve('docs/baseline-report.html')).href);
    assert.equal(await page.locator('article').count(), 2);
    assert.match(await page.locator('footer').innerText(), /no local acceptance token/);
    assert.doesNotMatch(await page.locator('footer').innerText(), /Review token:/);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Snapshot mobile overflow');
    assert.equal(await page.locator('script').count(), 0);
    assert.ok(requests.every(url => url.startsWith('file:')), 'Snapshot report made a network request');
    assert.deepEqual(errors, []);
    console.log('Verified actual HTML report: desktop/mobile layout, source diffs, no scripts or external requests.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
