async page => {
  const errors = [], origins = [];
  const origin = 'http://127.0.0.1:8029';
  const check = (ok, reason) => { if (!ok) throw new Error(reason); };
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => origins.push(new URL(r.url()).origin));
  await page.goto(origin + '/operations');
  const body = await page.locator('body').textContent();
  check(body.includes('LIVE_NOT_AUTHORIZED') && body.includes('EXTERNAL_VALIDATION_PENDING'), 'authority/evidence label lost');
  check((await page.locator('fieldset[disabled] button:disabled').count()) === 3, 'actual control exposed');
  const api = await (await page.request.get(origin + '/api/v1/operations')).json();
  check(api.closeouts[0].phase === 'FLAT' && !api.actual_dispatch_allowed, 'fixture/dispatch isolation lost');
  const alien = await (await page.request.get(origin + '/api/v1/operations?run_id=alien')).json();
  check(alien.closeouts.length === 0 && alien.mail.length === 0, 'run isolation lost');
  for (const action of ['activate', 'send-email', 'closeout', 'resume']) {
    check((await page.request.post(origin + '/api/v1/operations/' + action)).status() === 403, 'mutation permitted');
  }
  check((await page.request.get(origin + '/api/v1/operations', {headers: {Origin: 'https://foreign.invalid'}})).status() === 403, 'foreign origin permitted');
  for (const [label, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
    await page.setViewportSize({width, height});
    await page.screenshot({path: 'output/playwright/operations-' + label + '.png', fullPage: true});
    check(await page.locator('body').evaluate(el => el.scrollWidth <= innerWidth), 'horizontal overflow');
  }
  check(errors.length === 0 && origins.every(x => x === origin), 'browser error or external request');
  return {result: 'CODE_PASS', authority: api.authority, closeout: api.closeouts[0].phase,
    disabledControls: 3, deniedWrites: 4, crossRunEmpty: true, pageErrors: errors.length, externalRequests: 0};
}
