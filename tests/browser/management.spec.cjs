const { test, expect } = require('./fixtures.cjs');

// The management app, from its first run to the intake dialog: every script of
// the page loads and runs without an uncaught error (the audit fixture fails
// the spec on any page error). The fixture server is loopback only, so the
// first-run setup creates the admin; the other engine's run then logs in.
const ADMIN = { username: 'recette', password: 'Recette-synthetique-2026!' };

test.use({
  viewport: { width: 1440, height: 900 },
  locale: 'fr-FR',
  allowedWrites: ['POST /api/setup', 'POST /api/login', 'POST /api/intake/drafts', 'DELETE /api/intake/[^/]+'],
});

test('gestion : premier accès, liste, fiche et saisie', async ({ page }) => {
  await test.step('premier accès ou connexion', async () => {
    await page.goto('/gestion');
    const form = page.locator('#login-form');
    await expect(form).toBeVisible();
    // Every management script defined its globals.
    expect(await page.evaluate(() => [typeof t, typeof CardMedia, typeof Workflows, typeof Gallery, typeof openDetail]))
      .toEqual(['function', 'object', 'object', 'object', 'function']);
    await form.locator('input[name="username"]').fill(ADMIN.username);
    await form.locator('input[name="password"]').fill(ADMIN.password);
    await page.locator('#login-submit').click();
    await expect(page.locator('#workspace')).toBeVisible();
  });

  await test.step('liste de la collection', async () => {
    await expect(page.locator('#cards')).not.toHaveAttribute('aria-busy', 'true');
    await expect(page.locator('#cards article.card').first()).toBeVisible();
  });

  await test.step('fiche d’un exemplaire', async () => {
    await page.locator('#cards article.card button.card-open').first().click();
    await expect(page.locator('#detail-dialog')).toBeVisible();
    await expect(page.locator('#detail-body form.detail-fields')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('#detail-dialog')).toBeHidden();
  });

  await test.step('saisie d’une carte', async () => {
    await page.locator('#add-card').click();
    await expect(page.locator('#add-dialog')).toBeVisible();
    await expect(page.locator('#intake-read')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('#add-dialog')).toBeHidden();
  });
});
