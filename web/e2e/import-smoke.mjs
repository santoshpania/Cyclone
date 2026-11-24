/**
 * Browser smoke test of the Phase 1 import flow (dev auth mode).
 * Needs the API (AUTH_DEV_BYPASS=true), a queue worker and the web app (NEXT_PUBLIC_AUTH_MODE=dev) running:
 *   make api & make worker & (cd web && pnpm build && pnpm start) &
 *   node web/e2e/import-smoke.mjs [screenshot-dir]
 * Requires the `playwright` package (npm i -D playwright) and its Chromium. Uses a fresh dev user each run. Not wired into CI yet (see PLAN.md, carried over).
 */
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.resolve(__dirname, '../../backend/tests/fixtures/imports');
const SHOTS = process.argv[2] ?? path.resolve(__dirname, 'screenshots');
const BASE = process.env.BASE_URL ?? 'http://localhost:3000';
mkdirSync(SHOTS, { recursive: true });
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  const step = async (name) => { await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true }); console.log('✓', name, page.url()); };

  await page.goto(`${BASE}/workspaces`);
  await page.waitForURL(/\/login/);
  await page.getByRole('button', { name: 'Continue as dev user' }).click();
  await page.waitForURL(/\/workspaces$/);
  await page.getByText("You don't have a workspace yet.").waitFor();
  await step('01-empty-workspaces');

  await page.getByRole('link', { name: 'New workspace' }).click();
  await page.getByLabel('Company name').fill('Gulf Supplies Trading');
  await page.getByLabel('Products or services you sell (one per line)').fill('Office equipment\nMaintenance contracts');
  await page.getByLabel('Value proposition').fill('Next-day delivery across the UAE');
  await step('02-new-workspace');
  await page.getByRole('button', { name: 'Create workspace' }).click();
  await page.waitForURL(/\/w\/[^/]+\/imports$/);
  const wsUrl = page.url().replace(/\/imports$/, '');

  async function importFile(file, kindLabel, shotPrefix) {
    await page.goto(`${wsUrl}/imports`);
    await page.getByLabel("What's in the file?").selectOption({ label: kindLabel });
    await page.setInputFiles('#file', path.join(FIX, file));
    await page.getByRole('button', { name: 'Upload' }).click();
    await page.waitForURL(/\/imports\/[0-9a-f-]{36}$/);
    await page.getByText('Preview (first rows after mapping)').waitFor();
    await page.waitForTimeout(800);
    await step(`${shotPrefix}-mapping`);
    await page.getByRole('button', { name: 'Confirm mapping and import' }).click();
    await page.getByText(/Rows in file/).waitFor({ timeout: 60000 });
    await step(`${shotPrefix}-result`);
    const stats = await page.locator('.tabular-nums').allInnerTexts();
    console.log('  stats:', stats.join(' | '));
  }

  await importFile('tally_customers.csv', 'Customer list', '03-tally');
  await importFile('zoho_invoices.csv', 'Orders / invoices', '04-invoices');

  await page.goto(`${wsUrl}/accounts`);
  await page.getByText(/accounts$/).first().waitFor();
  await page.waitForTimeout(500);
  await step('05-accounts');
  await page.goto(`${wsUrl}/reviews`);
  await page.waitForTimeout(1000);
  await step('06-reviews');
  await page.goto(`${wsUrl}/imports`);
  await page.waitForTimeout(800);
  await step('07-imports-list');
  console.log('browser errors:', errors.length ? errors : 'none');
  await browser.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
