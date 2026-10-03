/* Browser regression suite. Call verifyEditorSafety(page, renderedEditorHtml)
 * with a fresh Playwright page and the editor rendered with this fixture:
 * id=101, device_id=TEST0001, updated_at=base-1, image=original, 4400x2560,
 * title=Safety test, one box, device_ids=[TEST0001,TEST0002].
 * All requests are intercepted; no application data is read or written.
 */
export async function verifyEditorSafety(page, html) {
  const results = [], requests = [], errors = [];
  let mode = 'ok';
  const check = (name, ok) => {
    results.push({name, ok});
    if (!ok) throw new Error(name);
  };
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    window.confirm = () => true;
    // Reloads simulate an interrupted tab; flush explicitly in each test.
    window.addEventListener('beforeunload', event => event.stopImmediatePropagation(), true);
  });
  await page.route('**/*', async route => {
    const request = route.request(), url = request.url();
    if (url.startsWith('https://editor-safety.invalid/') && request.resourceType() === 'document')
      return route.fulfill({contentType: 'text/html', body: html});
    if (url.includes('/configs/controllers/'))
      return route.fulfill({contentType: 'image/svg+xml', body:
        '<svg xmlns="http://www.w3.org/2000/svg" width="4400" height="2560"><rect width="4400" height="2560" fill="white"/></svg>'});
    if (url.endsWith('/admin/mapping-editor/save')) {
      requests.push(JSON.parse(request.postData()));
      if (mode === 'offline') return route.abort('internetdisconnected');
      if (mode === 'conflict') return route.fulfill({status: 409, contentType: 'application/json',
        body: JSON.stringify({error: 'A newer revision exists. Download JSON before reloading.'})});
      return route.fulfill({contentType: 'application/json', body: JSON.stringify({ok: true,
        id: 101, status: 'draft', public_status: 'published', updated_at: 'base-2',
        device_ids: ['TEST0001', 'TEST0002']})});
    }
    return route.abort();
  });
  await page.goto('https://editor-safety.invalid/?device=TEST0001');
  await page.evaluate(() => { localStorage.clear(); });
  await page.reload();
  await page.setViewportSize({width: 1440, height: 1000});
  check('editor loaded', await page.title() === 'Mapping editor - EDRefCard admin');
  await page.locator('#title').fill('Edited title');
  await page.locator('#btnsave').click();
  await page.waitForFunction(() => !saveInFlight);
  check('all aliases are submitted', requests[0].mapping.device_ids.length === 2);
  check('successful save clears only this draft', await page.evaluate(() => !dirty && localStorage.getItem(LS_KEY) === null));
  await page.locator('#btnundo').click();
  check('undo restores title and marks unsaved', await page.evaluate(() => $('#title').value === 'Safety test' && dirty));
  await page.locator('#btnredo').click();
  check('redo restores title', await page.evaluate(() => $('#title').value === 'Edited title'));
  await page.evaluate(() => {
    const files = new DataTransfer();
    files.items.add(new File([JSON.stringify({title: 'Imported', image: 'imported',
      width: 2000, height: 1000, device_ids: ['TEST0003'], boxes: []})], 'test.json', {type: 'application/json'}));
    $('#jsonfile').files = files.files;
    $('#jsonfile').dispatchEvent(new Event('change'));
  });
  await page.waitForFunction(() => state.width === 2000 && !saveInFlight);
  await page.locator('#btnundo').click();
  check('undo import restores full document', await page.evaluate(() => state.width === 4400 &&
    state.height === 2560 && state.image === 'original' && state.boxes.length === 1 && $('#title').value === 'Edited title'));
  mode = 'offline';
  await page.locator('#btnsave').click();
  await page.waitForFunction(() => !saveInFlight);
  check('network failure preserves work and enables retry', await page.evaluate(() => dirty &&
    !!localStorage.getItem(LS_KEY) && !$('#btnsave').disabled && $('#status').textContent.includes('Network')));
  mode = 'conflict';
  await page.locator('#btnsave').click();
  await page.waitForFunction(() => !saveInFlight);
  check('conflict preserves original base', await page.evaluate(() => dirty && baseUpdatedAt === 'base-2' &&
    $('#status').textContent.includes('newer revision')));
  const fingerprint = value => {
    const {document, base_updated_at, mapping_id} = JSON.parse(value);
    return JSON.stringify({document, base_updated_at, mapping_id});
  };
  const stored = fingerprint(await page.evaluate(() => { flushDraft(); return localStorage.getItem(LS_KEY); }));
  for (let i = 0; i < 2; i++) {
    await page.reload();
    await page.locator('#btnrestore').waitFor({state: 'visible'});
    await page.evaluate(() => { renderStage(); flushDraft(); });
    check('recovery survives reload ' + (i + 1), stored === fingerprint(await page.evaluate(() => localStorage.getItem(LS_KEY))));
  }
  await page.locator('#btnrestore').click();
  check('restore retains stale base for conflict detection', await page.evaluate(() => baseUpdatedAt === 'base-2' &&
    $('#title').value === 'Edited title' && dirty && !$('#btnsave').disabled));
  mode = 'ok';
  const count = requests.length;
  await page.evaluate(() => { $('#btnsave').click(); $('#btnsave').click(); });
  await page.waitForFunction(() => !saveInFlight);
  check('double click submits only once', requests.length === count + 1);
  check('no JavaScript errors', errors.length === 0);
  return results;
}
