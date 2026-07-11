import axios from '/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation/node_modules/axios/index.js';
import productConfigJson from '/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation/testData/products/productsconfig.json';
import { test, expect } from '/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation/src/setup/fixtures';
import * as fs from 'fs';

type StoreProducts = Record<string, { simple?: Array<{ product_id: number; variant_id: number }> }>;

const PRODUCT_CONFIG = productConfigJson as StoreProducts;
const SHIPPING_SHORT_CITY = 'Qz';
const BILLING_SHORT_CITY = 'Vx';

function readAutomationEnv() {
  const envPath = '/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation/.env';
  const env: Record<string, string> = {};
  for (const line of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#') || !trimmed.includes('=')) continue;
    const idx = trimmed.indexOf('=');
    env[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1).trim().replace(/^['"]|['"]$/g, '');
  }
  return env;
}

function findCityValuePaths(node: unknown, targetValue: string, currentPath = '$', hits: string[] = []): string[] {
  if (Array.isArray(node)) {
    node.forEach((item, index) => findCityValuePaths(item, targetValue, `${currentPath}[${index}]`, hits));
    return hits;
  }
  if (!node || typeof node !== 'object') return hits;
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    const nextPath = `${currentPath}.${key}`;
    if (key === 'city' && value === targetValue) hits.push(nextPath);
    findCityValuePaths(value, targetValue, nextPath, hits);
  }
  return hits;
}

function assertShortCitiesPreserved(requestObject: unknown, phase: string) {
  const shippingPaths = findCityValuePaths(requestObject, SHIPPING_SHORT_CITY);
  const billingPaths = findCityValuePaths(requestObject, BILLING_SHORT_CITY);
  expect(
    { shippingPaths, billingPaths },
    `${phase}: short city values should still be present in the request payload`,
  ).toEqual({
    shippingPaths: expect.arrayContaining([expect.stringMatching(/city$/)]),
    billingPaths: expect.arrayContaining([expect.stringMatching(/city$/)]),
  });
}

async function createShortCityOrder() {
  const env = readAutomationEnv();
  const store = env.STORE;
  const token = env.SHOPIFY_ACCESS_TOKEN;
  const version = env.SHOPIFY_API_VERSION;
  if (!store || !token || !version) throw new Error('Missing STORE/SHOPIFY_ACCESS_TOKEN/SHOPIFY_API_VERSION in automation .env');

  const product = PRODUCT_CONFIG[store]?.simple?.[0];
  if (!product) throw new Error(`No simple product config found for ${store}`);

  const response = await axios.post(
    `https://${store}.myshopify.com/admin/api/${version}/orders.json`,
    {
      order: {
        email: 'test.user@example.com',
        line_items: [{ product_id: product.product_id, variant_id: product.variant_id, quantity: 1 }],
        customer: { first_name: 'Test', last_name: 'User', email: 'test.user@example.com' },
        billing_address: {
          first_name: 'Bill',
          last_name: 'User',
          phone: '1234567890',
          address1: '23 Billing Street',
          city: BILLING_SHORT_CITY,
          province: 'CA',
          country: 'US',
          zip: '90001',
        },
        shipping_address: {
          first_name: 'Ship',
          last_name: 'User',
          phone: '1234567890',
          address1: '89 Shipping Ave',
          city: SHIPPING_SHORT_CITY,
          province: 'CA',
          country: 'US',
          zip: '90001',
        },
      },
    },
    {
      headers: {
        'X-Shopify-Access-Token': token,
        'Content-Type': 'application/json',
      },
      timeout: 30000,
    },
  );
  return response.data.order as { id: number; name: string };
}

async function ensureShopifyAppSession(pages: Parameters<typeof test>[0] extends never ? never : any) {
  const email = process.env.USER_EMAIL || 'ashok@pluginhive.com';
  const password = process.env.USER_PASSWORD || '';
  const store = process.env.STORE || 'kee-fedex-qa';

  const emailInputVisible = await pages.sharedPage.locator('#account_email').isVisible().catch(() => false);
  if (emailInputVisible) {
    await pages.sharedPage.locator('#account_email').fill(email);
    await pages.sharedPage.locator('button:has-text("Continue with email")').click();
    await pages.sharedPage.waitForLoadState('domcontentloaded');

    const passwordInput = pages.sharedPage.locator('#account_password');
    const passwordVisible = await passwordInput.isVisible().catch(() => false);
    if (passwordVisible && password) {
      await passwordInput.fill(password);
      await pages.sharedPage.locator('button[type="submit"]:has-text("Log in")').click();
      await pages.sharedPage.waitForLoadState('domcontentloaded');
    }
  }

  if (await pages.shopifyAccountSelectorPage.isAccountSelectionPageVisible()) {
    const accountCard = pages.shopifyAccountSelectorPage.getAccountCardByEmail(email);
    await accountCard.waitFor({ state: 'visible', timeout: 10000 });
    await accountCard.click();
    await pages.sharedPage.waitForLoadState('domcontentloaded');
  }

  const storePageVisible = await pages.shopifyStoreSelectionPage.storeSearchInput.isVisible().catch(() => false);
  if (storePageVisible) {
    await pages.shopifyStoreSelectionPage.selectStoreAndProceed(store);
  }

  await pages.sharedPage.waitForLoadState('domcontentloaded');
}

test.describe.configure({ mode: 'serial' });

test.describe('Short city preserved in FedEx requests', () => {
  let order: { id: number; name: string };

  test.beforeAll(async () => {
    order = await createShortCityOrder();
    expect(order?.name).toBeTruthy();
    console.log(`Created Shopify order ${order.name} (${order.id})`);
  });

  test('verifies rate log, label generation, and label request zip', async ({ pages }) => {
    test.setTimeout(240000);

    await pages.sharedPage.goto(`https://admin.shopify.com/store/${process.env.STORE}/apps/testing-553/shopify`);
    await ensureShopifyAppSession(pages);

    await pages.shippingPage.searchButton.waitFor({ state: 'visible', timeout: 60000 });
    await pages.shippingPage.searchButton.click();
    await pages.shippingPage.searchInput.waitFor({ state: 'visible', timeout: 30000 });
    await pages.shippingPage.searchInput.fill(order.name.replace(/^#/, ''));
    await pages.shippingPage.searchInput.press('Enter');

    const row = pages.shippingPage.getRowByOrderId(order.name);
    await row.waitFor({ state: 'visible', timeout: 30000 });

    await pages.shippingPage.clickMoreActionsItem('Generate Label');

    await pages.manualLabelPage.openRateRequestLog();
    const rateLogData = await pages.manualLabelPage.getParsedDataFromRequestLog();
    const rateRequest = rateLogData?.requestObject ?? rateLogData;
    assertShortCitiesPreserved(rateRequest, 'Rate log request');

    const rateResponse = await pages.manualLabelPage.LogModalResponseSection.innerText();
    expect(rateResponse).not.toContain('CITY.TOO.SHORT');
    await pages.manualLabelPage.closeModal();

    await pages.manualLabelPage.clickGenerateLabelButtonInManualLabelGenerationPage();
    await pages.orderSummaryPage.verifyLabelGenerated();

    await pages.manualLabelPage.clickMoreActionsButton();
    await pages.manualLabelPage.clickHowToSubActions();
    await pages.manualLabelPage.howToHeading.waitFor({ state: 'visible', timeout: 10000 });

    const logPath = await pages.manualLabelPage.downloadLabelLogs();
    const labelLog = await pages.manualLabelPage.getLabelRequestLog(logPath);
    assertShortCitiesPreserved(labelLog?.requestObject ?? labelLog, 'Label request zip');
    await pages.manualLabelPage.cleanupLogs(logPath);
  });
});
