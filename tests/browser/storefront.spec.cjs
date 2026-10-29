const assert = require('node:assert/strict');
const { test, expect, BASE, tabTo, ready, imageReady, noOverflow, snapshot } = require('./fixtures.cjs');

for (const [width, height] of [[320, 568], [390, 844], [1440, 900]]) {
  for (const lang of ['fr', 'en']) {
    const mobile = width < 700;
    test.describe(`${width}px ${lang}`, () => {
      test.use({
        viewport: { width, height }, screen: { width, height },
        deviceScaleFactor: mobile ? 2 : 1, hasTouch: mobile,
        locale: lang === 'fr' ? 'fr-FR' : 'en-GB',
      });

      test('filtres, zoom, toucher et clavier', async ({ page, fixtureData, audit }, info) => {
        const home = lang === 'en' ? '/en/' : '/';
        const activate = selector => mobile ? page.locator(selector).tap() : page.locator(selector).click();

        await test.step('état choisi au clavier, puce et adresse', async () => {
          await page.goto(home);
          await ready(page, 3);
          await noOverflow(page);
          if (mobile) {
            expect(await page.evaluate(() => matchMedia('(pointer:coarse)').matches)).toBe(true);
            await activate('#filter-open');
            await expect(page.locator('#filter-open')).toHaveAttribute('aria-expanded', 'true');
            await expect(page.locator('#extension')).toBeFocused();
          } else await page.locator('#extension').focus();
          await tabTo(page, '#condition');
          await page.keyboard.press('End');
          await page.keyboard.press('Enter');
          await page.keyboard.press('Tab');
          await ready(page, 1);
          await expect(page.locator('#condition')).toHaveValue('unknown');
          expect(page.url()).toContain('condition=unknown');
          expect((await page.locator('.filter-chip').allTextContents()).join(' ')).toMatch(/Non renseigné|Not specified/);
          if (mobile) {
            await activate('#filter-apply');
            await expect(page.locator('#filter-open')).toBeFocused();
            await expect(page.locator('#filter-open')).toHaveAttribute('aria-expanded', 'false');
          }
          await noOverflow(page);
          await snapshot(page, info, 'filters');
        });

        await test.step('persistance, changement de langue et intersection des critères', async () => {
          await page.reload();
          await ready(page, 1);
          await expect(page.locator('#condition')).toHaveValue('unknown');
          await Promise.all([
            page.waitForURL(url => url.pathname === (lang === 'fr' ? '/en/' : '/')),
            page.locator('#language-switch').click(),
          ]);
          await ready(page, 1);
          await expect(page.locator('#condition')).toHaveValue('unknown');
          expect(page.url()).toContain('condition=unknown');
          await expect(page.locator('html')).toHaveAttribute('lang', lang === 'fr' ? /^en/ : /^fr/);
          await page.goto(`${home}#condition=unknown`);
          await ready(page, 1);
          if (mobile) await activate('#filter-open');
          await page.locator('#language').selectOption('fr');
          await ready(page, 0); // The unknown state and French belong to different lot members.
          expect(await page.locator('#results-empty').isVisible()).toBe(!mobile);
          await page.locator('#language').selectOption('');
          await ready(page, 1);
          await page.locator('#condition').selectOption('NM/EX');
          await ready(page, 1);
          expect(new URL(await page.locator('.tile-open').getAttribute('href'), BASE).pathname).toBe(`${home}carte/${fixtureData.square}`);
          await page.locator('#condition').selectOption('NM');
          await ready(page, 1);
          expect(new URL(await page.locator('.tile-open').getAttribute('href'), BASE).pathname).toBe(`${home}carte/${fixtureData.single}`);
          await activate(mobile ? '#filter-reset' : '#filters-clear');
          await ready(page, 3);
          if (mobile) {
            await page.keyboard.press('Escape');
            await expect(page.locator('#filter-open')).toBeFocused();
            await expect(page.locator('#filter-open')).toHaveAttribute('aria-expanded', 'false');
          }
        });

        const tile = page.locator(`.tile-open[href$="/${fixtureData.single}"]`);
        await test.step('fiche au clavier, photo contenue et zoom à la demande', async () => {
          await tile.focus();
          await page.keyboard.press('Enter');
          await imageReady(page);
          await expect(page.locator('#detail')).toHaveJSProperty('open', true);
          const normal = await page.locator('#detail-stage').evaluate(stage => {
            const bounds = node => {
              const { top, bottom } = node.getBoundingClientRect();
              return { top, bottom };
            };
            const image = stage.querySelector('img');
            return { frame: bounds(stage), image: bounds(image),
              caption: bounds(document.querySelector('#detail-caption')), fit: getComputedStyle(image).objectFit };
          });
          expect(normal.fit).toBe('contain');
          expect(normal.image.top).toBeGreaterThanOrEqual(normal.frame.top - 1);
          expect(normal.image.bottom).toBeLessThanOrEqual(normal.frame.bottom + 1);
          expect(normal.caption.top).toBeGreaterThanOrEqual(normal.frame.bottom - 1);
          expect(audit.photos.some(url => url.includes('size=full'))).toBe(false);
          expect(await page.evaluate(() => {
            document.querySelector('#q').focus();
            return document.activeElement !== document.querySelector('#q');
          })).toBe(true);
          await tabTo(page, '#detail-zoom-open');
          if (mobile) await activate('#detail-zoom-open');
          else await page.keyboard.press('Enter');
          await imageReady(page);
          await expect(page.locator('#detail-stage')).toBeFocused();
          await expect(page.locator('#detail')).toHaveClass(/photo-mode/);
          expect(await page.locator('#detail-stage img').evaluate(image => image.naturalWidth)).toBe(fixtureData.source_dimensions[0]);
        });

        await test.step('curseur au clavier, quatre bords et déplacement de la photo', async () => {
          await tabTo(page, '#detail-zoom-range');
          await page.keyboard.press('End');
          await expect(page.locator('#detail-zoom-range')).toHaveValue('4');
          await page.keyboard.press('ArrowLeft');
          await expect(page.locator('#detail-zoom-range')).toHaveValue('3.75');
          await page.keyboard.press('ArrowRight');
          await expect(page.locator('#detail-zoom-range')).toHaveValue('4');
          expect(await page.locator('#detail-zoom-range').getAttribute('aria-valuetext')).toBeTruthy();
          await expect(page.locator('#detail-zoom-value')).toHaveAttribute('role', 'status');
          await page.locator('#detail-stage').focus();
          const address = page.url();
          await page.keyboard.press('Home');
          await page.keyboard.press('ArrowRight');
          await page.keyboard.press('ArrowDown');
          await page.waitForFunction(() => {
            const stage = document.querySelector('#detail-stage');
            return stage.scrollLeft > 0 && stage.scrollTop > 0;
          });
          await page.keyboard.press('End');
          await page.waitForFunction(() => {
            const stage = document.querySelector('#detail-stage');
            return stage.scrollLeft + stage.clientWidth >= stage.scrollWidth - 1
              && stage.scrollTop + stage.clientHeight >= stage.scrollHeight - 1;
          });
          const edge = await page.locator('#detail-stage').evaluate(stage => ({
            left: stage.scrollLeft, touchAction: getComputedStyle(stage).touchAction,
          }));
          for (const action of ['pan-x', 'pan-y', 'pinch-zoom']) expect(edge.touchAction).toContain(action);
          expect(page.url()).toBe(address);
          await snapshot(page, info, 'zoom');
          if (!mobile) {
            const box = await page.locator('#detail-stage').boundingBox();
            const x = box.x + box.width / 2, y = box.y + box.height / 2;
            await page.mouse.move(x, y);
            await page.mouse.down();
            await page.mouse.move(x + 60, y + 60, { steps: 8 });
            await page.mouse.up();
            await page.waitForFunction(before => document.querySelector('#detail-stage').scrollLeft < before, edge.left);
            await expect(page.locator('#detail-stage')).not.toHaveClass(/is-panning/);
          } else {
            // Synthetic pointer events check non-interception, not native inertia or pinch.
            expect(await page.locator('#detail-stage').evaluate(frame => {
              for (const [type, x] of [['pointerdown', 180], ['pointermove', 80], ['pointerup', 80]]) {
                const event = new PointerEvent(type, { bubbles: true, cancelable: true,
                  pointerId: 42, pointerType: 'touch', isPrimary: true, button: 0,
                  buttons: type === 'pointerup' ? 0 : 1, clientX: x, clientY: 120 });
                frame.dispatchEvent(event);
                if (event.defaultPrevented) return false;
              }
              return !frame.classList.contains('is-panning');
            })).toBe(true);
            expect(page.url()).toBe(address);
          }
        });

        await test.step('commandes tactiles ou souris, Échap, recto/verso et retour du focus', async () => {
          await activate('#detail-zoom-reset');
          await expect(page.locator('#detail-zoom-range')).toHaveValue('1');
          expect(await page.locator('#detail-stage').evaluate(node => node.scrollLeft === 0 && node.scrollTop === 0)).toBe(true);
          await activate('#detail-zoom-plus');
          await activate('#detail-zoom-plus');
          await expect(page.locator('#detail-zoom-range')).toHaveValue('1.5');
          await activate('#detail-zoom-minus');
          await expect(page.locator('#detail-zoom-range')).toHaveValue('1.25');
          await page.keyboard.press('Escape');
          await expect(page.locator('#detail')).toHaveJSProperty('open', true);
          await expect(page.locator('#detail')).not.toHaveClass(/photo-mode/);
          await expect(page.locator('#detail-zoom-open')).toBeFocused();
          await activate('#detail-zoom-open');
          await imageReady(page);
          await activate('#detail-zoom-exit');
          await expect(page.locator('#detail-zoom-open')).toBeFocused();
          await page.keyboard.press('r');
          await expect(page.locator('#detail-caption')).toContainText(lang === 'fr' ? 'Verso' : 'Back');
          await page.keyboard.press('r');
          await imageReady(page);
          expect(audit.views).toHaveLength(1);
          await page.keyboard.press('Escape');
          await expect(page.locator('#detail')).toHaveJSProperty('open', false);
          await expect(tile).toBeFocused();
          await page.waitForFunction(() => !location.pathname.includes('/carte/'));
        });

        await test.step('lot paysage en adresse directe et filtre conservé', async () => {
          await page.goto(`${home}carte/${fixtureData.lot}#condition=unknown`);
          await imageReady(page);
          await expect(page.locator('#condition')).toHaveValue('unknown');
          expect(await page.locator('#language-switch').getAttribute('href')).toMatch(/#condition=unknown$/);
          expect(await page.title()).toContain('Lot synthetique <test> & public');
          await activate('#detail-zoom-open');
          await imageReady(page);
          await activate('#detail-zoom-plus');
          await activate('#detail-zoom-exit');
          await imageReady(page);
          await snapshot(page, info, 'lot');
          await noOverflow(page);
          if (mobile) assert.ok(await page.evaluate(() => window.qaTouches.some(event => event.type === 'touchstart' && event.trusted)));
        });
      });
    });
  }
}
