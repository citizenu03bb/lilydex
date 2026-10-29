const { test, expect, imageReady, ready, snapshot } = require('./fixtures.cjs');

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, locale: 'fr-FR' });

test('reprises après panne de photo et de filtre', async ({ page, context, fixtureData }, info) => {
  let photos = 'webp', api = 'healthy';
  const retriedPhotos = [];
  // This route is evaluated before the general network guard. Only the known
  // local paths are fulfilled; every other request falls through to the guard.
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://127.0.0.1:8796') return route.fallback();
    if (!['GET', 'HEAD'].includes(route.request().method())) return route.fallback();
    if (url.pathname === '/api/public/listings' && api === 'failed') {
      return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Synthetic unavailable"}' });
    }
    if (url.pathname.endsWith('/photo') && url.searchParams.get('size')?.startsWith('view')) {
      if (photos === 'all' || photos === 'webp' && url.searchParams.get('format') === 'webp') {
        return route.fulfill({ status: 503, body: 'Synthetic unavailable' });
      }
      if (photos === 'healthy' && url.searchParams.has('_retry')) retriedPhotos.push(url.href);
    }
    return route.fallback();
  });

  await test.step('repli WebP vers JPEG', async () => {
    await page.goto(`/carte/${fixtureData.single}`);
    await imageReady(page);
    expect(await page.locator('#detail-stage img').evaluate(image => image.currentSrc)).toContain('format=jpeg');
  });

  await test.step('nouvelle requête et reprise tactile après échec des variantes', async () => {
    photos = 'all';
    await page.reload();
    await expect(page.locator('#detail-stage .photo-retry')).toBeVisible();
    await expect(page.locator('#detail-stage img')).toHaveJSProperty('hidden', true);
    photos = 'healthy';
    await page.locator('#detail-stage .photo-retry').tap();
    await imageReady(page);
    expect(retriedPhotos.length).toBeGreaterThan(0);
    await info.attach('successful-photo-retry', {
      body: JSON.stringify(retriedPhotos, null, 2), contentType: 'application/json',
    });
  });

  await test.step('erreur de filtre, résultats conservés et reprise au clavier', async () => {
    await page.keyboard.press('Escape');
    await expect(page.locator('#detail')).toHaveJSProperty('open', false);
    await page.locator('#filter-open').tap();
    api = 'failed';
    await page.locator('#condition').selectOption('NM');
    await expect(page.locator('#filter-error')).toBeVisible();
    await expect(page.locator('.tile')).toHaveCount(3);
    await page.keyboard.press('Escape');
    await expect(page.locator('#results-retry')).toBeVisible();
    await page.locator('#results-retry').focus();
    api = 'healthy';
    await page.keyboard.press('Enter');
    await ready(page, 1);
    await expect(page.locator('#results')).toBeFocused();
    await expect(page.locator('#condition')).toHaveValue('NM');
    await expect(page.locator('#error')).toHaveJSProperty('hidden', true);
    await snapshot(page, info, 'retry');
  });
});
