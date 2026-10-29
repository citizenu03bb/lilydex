const assert = require('node:assert/strict');
const { test: base, expect } = require('@playwright/test');

const BASE = 'http://127.0.0.1:8796';

const test = base.extend({
  // Firefox supports hasTouch and a small viewport, but not isMobile.
  isMobile: async ({ browserName, viewport }, use) => {
    await use(browserName === 'webkit' && viewport.width < 700);
  },
  fixtureData: async ({ request }, use) => {
    const response = await request.get(`${BASE}/__test__/fixture`);
    expect(response.ok()).toBeTruthy();
    const fixture = await response.json();
    expect(fixture.synthetic_only).toBe(true);
    await use(fixture);
  },
  audit: [async ({ context, page }, use, info) => {
    const audit = { external: [], writes: [], pageErrors: [], photos: [], views: [] };
    await context.addInitScript(() => {
      window.qaTouches = [];
      for (const type of ['pointerdown', 'touchstart', 'touchend']) {
        document.addEventListener(type, event => window.qaTouches.push({
          type, trusted: event.isTrusted, pointer: event.pointerType || null,
        }), true);
      }
    });
    await context.route('**/*', route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== BASE) {
        audit.external.push(request.url());
        return route.abort();
      }
      if (!['GET', 'HEAD'].includes(request.method())) {
        audit.writes.push(`${request.method()} ${url.pathname}`);
        return route.abort();
      }
      if (url.pathname.endsWith('/photo')) audit.photos.push(url.pathname + url.search);
      if (url.searchParams.get('view') === '1') audit.views.push(url.pathname);
      return route.continue();
    });
    page.on('pageerror', error => audit.pageErrors.push(error.message));
    try {
      await use(audit);
    } finally {
      await info.attach('network-audit', {
        body: JSON.stringify(audit, null, 2), contentType: 'application/json',
      });
      expect(audit.external, 'No external request is allowed').toEqual([]);
      expect(audit.writes, 'No HTTP write is allowed').toEqual([]);
      expect(audit.pageErrors, 'No uncaught JavaScript error is allowed').toEqual([]);
    }
  }, { auto: true }],
});

async function tabTo(page, selector, max = 30) {
  // Native headless dialogs differ at the browser-chrome boundary. Both
  // directions must work without adding an application-specific focus trap.
  for (const key of ['Tab', 'Shift+Tab']) {
    let last = '', stalled = 0;
    for (let index = 0; index < max; index++) {
      if (await page.locator(selector).evaluate(node => node === document.activeElement)) return;
      const current = await page.evaluate(() => document.activeElement.outerHTML);
      stalled = current === last ? stalled + 1 : 0;
      last = current;
      if (stalled >= 3) break;
      await page.keyboard.press(key);
    }
  }
  assert.fail(`Keyboard cannot reach ${selector}`);
}

async function ready(page, count) {
  await page.waitForFunction(expected => (
    document.querySelector('#grid')?.getAttribute('aria-busy') === 'false'
    && document.querySelector('#filter-apply')?.disabled === false
    && document.querySelectorAll('.tile').length === expected
  ), count);
}

async function imageReady(page) {
  await page.waitForFunction(() => {
    const image = document.querySelector('#detail-stage img');
    return image && !image.hidden && image.complete && image.naturalWidth > 0;
  });
  await page.locator('#detail-stage img').evaluate(image => image.decode());
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(
    () => requestAnimationFrame(resolve),
  )));
}

async function noOverflow(page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
}

async function snapshot(page, info, name) {
  const filename = info.outputPath(`${name}.png`);
  await page.screenshot({ path: filename });
  await info.attach(name, { path: filename, contentType: 'image/png' });
}

module.exports = { test, expect, BASE, tabTo, ready, imageReady, noOverflow, snapshot };
