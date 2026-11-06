const { test, expect, ready, noOverflow, snapshot } = require('./fixtures.cjs');

for (const width of [390, 1440]) {
  for (const lang of ['fr', 'en']) {
    test.describe(`panier ${width}px ${lang}`, () => {
      test.use({ viewport: { width, height: 900 }, locale: lang === 'fr' ? 'fr-FR' : 'en-GB' });

      test('restaure, nomme les indisponibles et fait accepter le prix avant envoi', async ({ page, fixtureData }, info) => {
        const home = lang === 'en' ? '/en/' : '/';
        await page.goto(home);
        await ready(page, 3);
        await page.evaluate(id => localStorage.setItem('lilydex-basket', JSON.stringify([
          { id, label: 'Carte conservée', price_cents: 50, card_count: 1 },
          { id: 'disparu', label: 'Carte disparue', price_cents: 100, card_count: 1 },
        ])), fixtureData.single);
        await page.reload();
        await ready(page, 3);
        await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('lilydex-basket')).length)).toBe(1);
        await page.locator('#basket-open').click();
        await expect(page.locator('#basket-updates')).toContainText('Carte disparue');
        await expect(page.locator('#basket-items .price')).toContainText(/1[,.]20/);
        await expect(page.locator('#basket-items')).toContainText(/0[,.]50/);
        await page.locator('#basket-form [name=email]').fill('invite@example.org');
        await page.locator('#basket-form [name=display_name]').fill('Invité');
        await page.locator('#basket-form [name=consent]').check();
        await page.locator('#basket-form [name=delivery][value=hand]').check();

        // Only read-only local quotes reach the server. The submit is a browser stub.
        await page.route('**/api/public/quote', async route => {
          const response = await route.fetch();
          const quote = await response.json();
          for (const item of quote.items) item.price_cents = 220;
          quote.subtotal_cents = 220;
          quote.total_cents = 220 + quote.shipping_cents;
          await route.fulfill({ response, json: quote });
        });
        const sent = [];
        await page.route('**/api/public/requests', async route => {
          sent.push(route.request().postDataJSON());
          await route.fulfill({ status: 202, contentType: 'application/json', body: '{"detail":"Demande factice reçue"}' });
        });
        const submit = page.locator('#basket-form button[type=submit], #basket-form button:not([type])').first();
        await submit.click();
        await expect(page.locator('#basket-form')).not.toHaveAttribute('aria-busy', 'true');
        await expect(page.locator('#basket-items .price')).toContainText(/2[,.]20/);
        await expect(page.locator('#basket-items .price')).toBeInViewport();
        await expect(page.locator('#basket-updates')).toBeFocused();
        expect(sent).toHaveLength(0);
        await noOverflow(page);
        await snapshot(page, info, 'basket-price-change');
        await submit.click();
        await expect.poll(() => sent.length).toBe(1);
        expect(sent[0].expected_prices).toEqual({ [fixtureData.single]: 220 });
        await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('lilydex-basket')).length)).toBe(0);
      });
    });
  }
}
