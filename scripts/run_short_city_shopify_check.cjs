const fs = require('fs');
const path = require('path');

const { chromium, expect } = require('/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation/node_modules/playwright');
const axios = require('/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation/node_modules/axios').default;
const AdmZip = require('/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation/node_modules/adm-zip');

const AUTOMATION_ROOT = '/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation';
const AUTH_PATH = path.join(AUTOMATION_ROOT, 'auth.json');
const ENV_PATH = path.join(AUTOMATION_ROOT, '.env');
const PRODUCTS_PATH = path.join(AUTOMATION_ROOT, 'testData/products/productsconfig.json');
const STORE_URL = 'https://admin.shopify.com/store/kee-fedex-qa';
const APP_URL = `${STORE_URL}/apps/testing-553`;
const APP_NAME = 'QA ship Rate and track for FedEx';
const SHIPPING_SHORT_CITY = 'Qz';
const BILLING_SHORT_CITY = 'Vx';

function readEnv(envPath) {
  const env = {};
  for (const line of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#') || !trimmed.includes('=')) continue;
    const idx = trimmed.indexOf('=');
    const key = trimmed.slice(0, idx).trim();
    const value = trimmed.slice(idx + 1).trim().replace(/^['"]|['"]$/g, '');
    env[key] = value;
  }
  return env;
}

function loadFirstSimpleProduct(storeName) {
  const products = JSON.parse(fs.readFileSync(PRODUCTS_PATH, 'utf8'));
  const storeProducts = products[storeName];
  if (!storeProducts?.simple?.length) {
    throw new Error(`No simple products configured for store ${storeName}`);
  }
  return storeProducts.simple[0];
}

async function createOrderWithShortCities(env) {
  const product = loadFirstSimpleProduct(env.STORE);
  const apiUrl = `https://${env.STORE}.myshopify.com/admin/api/${env.SHOPIFY_API_VERSION}/orders.json`;
  const payload = {
    order: {
      email: 'test.user@example.com',
      line_items: [
        {
          product_id: product.product_id,
          variant_id: product.variant_id,
          quantity: 1,
        },
      ],
      customer: {
        first_name: 'Test',
        last_name: 'User',
        email: 'test.user@example.com',
      },
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
  };

  const response = await axios.post(apiUrl, payload, {
    headers: {
      'X-Shopify-Access-Token': env.SHOPIFY_ACCESS_TOKEN,
      'Content-Type': 'application/json',
    },
    timeout: 30000,
  });

  if (!response?.data?.order?.name) {
    throw new Error('Order creation succeeded without an order name in the response');
  }

  return response.data.order;
}

async function waitForUnique(locator, label) {
  await locator.waitFor({ state: 'visible', timeout: 30000 });
  const count = await locator.count();
  if (count !== 1) {
    throw new Error(`${label} expected 1 match, found ${count}`);
  }
}

async function clickUnique(locator, label) {
  await waitForUnique(locator, label);
  await locator.click();
}

async function tryResolveShopifyIntermediates(page, env) {
  const bodyText = await page.locator('body').innerText().catch(() => '');

  if (page.url().includes('accounts.shopify.com/select') || bodyText.includes('Choose an account')) {
    const accountCard = page.locator('a.choose-account-card').filter({ hasText: env.USER_EMAIL });
    if ((await accountCard.count()) > 0) {
      console.log(`Selecting Shopify account for ${env.USER_EMAIL}`);
      await accountCard.first().click();
      return true;
    }
  }

  const storeLink = page.locator('a').filter({ hasText: env.STORE });
  if ((await storeLink.count()) > 0 && (page.url().includes('admin.shopify.com/select') || bodyText.includes(env.STORE))) {
    console.log(`Selecting Shopify store ${env.STORE}`);
    await storeLink.first().click();
    return true;
  }

  return false;
}

async function waitForShopifyReady(page, env, expectedUrlPart = '/store/kee-fedex-qa', timeoutMs = 180000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await tryResolveShopifyIntermediates(page, env);
    const url = page.url();
    const title = await page.title().catch(() => '');
    const bodyText = await page.locator('body').innerText().catch(() => '');

    if (url.includes(expectedUrlPart) && !title.includes('Just a moment') && !bodyText.includes('connection needs to be verified')) {
      return;
    }

    console.log(`Waiting for Shopify verification to clear... url=${url} title=${title}`);
    await page.waitForTimeout(5000);
  }

  throw new Error('Shopify verification gate did not clear in time');
}

function findCityValuePaths(node, targetValue, currentPath = '$', hits = []) {
  if (Array.isArray(node)) {
    node.forEach((item, index) => findCityValuePaths(item, targetValue, `${currentPath}[${index}]`, hits));
    return hits;
  }

  if (!node || typeof node !== 'object') {
    return hits;
  }

  for (const [key, value] of Object.entries(node)) {
    const nextPath = `${currentPath}.${key}`;
    if (key === 'city' && value === targetValue) {
      hits.push(nextPath);
    }
    findCityValuePaths(value, targetValue, nextPath, hits);
  }

  return hits;
}

function assertShortCitiesPreserved(requestObject, phase) {
  const shippingPaths = findCityValuePaths(requestObject, SHIPPING_SHORT_CITY);
  const billingPaths = findCityValuePaths(requestObject, BILLING_SHORT_CITY);

  if (!shippingPaths.length || !billingPaths.length) {
    throw new Error(
      `${phase}: short city values were not present in the request.\n` +
        `shippingPaths=${JSON.stringify(shippingPaths)} billingPaths=${JSON.stringify(billingPaths)}`
    );
  }
}

async function searchAndOpenOrder(page, orderName, orderId, env) {
  await waitForShopifyReady(page, env);
  try {
    const searchButton = page.getByRole('button', { name: 'Search' });
    await clickUnique(searchButton, 'Shopify Search button');

    const ordersButton = page.locator('#search-container').getByRole('button', { name: 'Orders' });
    await clickUnique(ordersButton, 'Orders filter button');

    const searchInput = page.getByRole('combobox', { name: 'Search' });
    await searchInput.waitFor({ state: 'visible', timeout: 10000 });
    await searchInput.fill(orderName);

    const orderLink = page.locator('ul#search-results a[role="option"][href*="/orders/"]').filter({ hasText: orderName });
    await orderLink.waitFor({ state: 'visible', timeout: 30000 });
    await orderLink.click();
    await page.waitForURL(/\/orders\//, { timeout: 30000 });
    return;
  } catch (error) {
    console.log(`Shopify search flow failed, falling back to direct order URL for ${orderId}`);
  }

  await page.goto(`${STORE_URL}/orders/${orderId}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForURL(/\/orders\//, { timeout: 30000 });
}

async function openManualLabelPage(page, env) {
  await waitForShopifyReady(page, env);
  const moreActions = page.getByRole('button', { name: 'More actions' }).first();
  await clickUnique(moreActions, 'Shopify order More actions');

  const candidates = [
    page.locator('.Polaris-Popover').getByText('Generate Label', { exact: true }),
    page.getByRole('menuitem', { name: 'Generate Label', exact: true }),
    page.getByRole('link', { name: 'Generate Label', exact: true }),
    page.getByRole('button', { name: 'Generate Label', exact: true }),
    page.getByText('Generate Label', { exact: true }),
    page.getByRole('button', { name: 'Create shipping label', exact: true }),
  ];

  for (const candidate of candidates) {
    if ((await candidate.count()) > 0) {
      await candidate.first().click();
      return;
    }
  }

  const failPath = path.join('/private/tmp', `generate-label-missing-${Date.now()}.png`);
  await page.screenshot({ path: failPath, fullPage: false });
  throw new Error(`Generate Label action not found on order page. Screenshot saved to ${failPath}`);
}

async function openManualLabelFromFedExApp(page, orderName) {
  await page.goto(`${APP_URL}/shopify`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  const iframe = page.locator('iframe[name="app-iframe"]');
  try {
    await iframe.waitFor({ state: 'visible', timeout: 60000 });
  } catch (error) {
    const failPath = path.join('/private/tmp', `fedex-app-iframe-missing-${Date.now()}.png`);
    await page.screenshot({ path: failPath, fullPage: false });
    throw new Error(`FedEx app iframe did not become visible on /shopify. Screenshot saved to ${failPath}. Current URL: ${page.url()}`);
  }

  const frame = page.frameLocator('iframe[name="app-iframe"]');
  const searchAndFilterButton = frame.getByRole('button', { name: 'Search and filter results' });
  const shippingNav = frame.getByText('Shipping', { exact: true });

  if ((await searchAndFilterButton.count()) === 0) {
    await shippingNav.waitFor({ state: 'visible', timeout: 60000 });
    await shippingNav.click();
  } else {
    await searchAndFilterButton.waitFor({ state: 'visible', timeout: 60000 });
  }

  await searchAndFilterButton.click();

  const cleanOrderId = orderName.replace(/^#/, '');
  const searchInput = frame.getByRole('textbox');
  await searchInput.waitFor({ state: 'visible', timeout: 30000 });
  await searchInput.fill(cleanOrderId);
  await searchInput.press('Enter');

  const row = frame.locator('tbody tr:visible').filter({ hasText: orderName }).first();
  await row.waitFor({ state: 'visible', timeout: 30000 });

  const rowMoreActions = frame.getByRole('button', { name: 'More actions' }).first();
  await rowMoreActions.click();

  const generateLabelInApp = frame.getByRole('menuitem', { name: 'Generate Label' }).first();
  if ((await generateLabelInApp.count()) > 0) {
    await generateLabelInApp.click();
    return;
  }

  const fallbackGenerateLabel = frame.locator('.Polaris-ActionList button').filter({ hasText: 'Generate Label' }).first();
  await fallbackGenerateLabel.waitFor({ state: 'visible', timeout: 10000 });
  await fallbackGenerateLabel.click();
}

async function openAppViaSidebar(page, env) {
  await page.goto(STORE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await waitForShopifyReady(page, env);
  const sidebarAppByHref = page.locator('a[href*="/apps/testing-553"]').first();
  if ((await sidebarAppByHref.count()) > 0) {
    await sidebarAppByHref.click();
  } else {
    const appsSection = page.getByText('Apps', { exact: true });
    if ((await appsSection.count()) > 0) {
      await appsSection.first().click().catch(() => {});
      await page.waitForTimeout(1000);
    }

    const sidebarAppByName = page.getByRole('link', { name: 'QA Ship Rate & Track for FedEx' }).first();
    if ((await sidebarAppByName.count()) > 0) {
      await sidebarAppByName.click();
    } else {
      console.log('Sidebar app link was not directly available, falling back to the app URL');
      await page.goto(APP_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
      await waitForShopifyReady(page, env, '/store/kee-fedex-qa/apps/testing-553');
      return;
    }
  }

  for (let attempt = 1; attempt <= 8; attempt += 1) {
    if (page.url().includes('/apps/testing-553')) {
      return;
    }

    if ((await page.locator('iframe[name="app-iframe"]').count()) > 0) {
      return;
    }

    await page.waitForTimeout(2000);
    console.log(`Waiting for app navigation after search click... attempt ${attempt}`);
  }

  console.log('Sidebar app click did not open the app directly, falling back to the app URL');
  await page.goto(APP_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await waitForShopifyReady(page, env, '/store/kee-fedex-qa/apps/testing-553');
}

async function downloadFromClick(page, trigger) {
  const downloadDir = path.join('/private/tmp', `fedex-short-city-${Date.now()}`);
  fs.mkdirSync(downloadDir, { recursive: true });
  const [download] = await Promise.all([page.waitForEvent('download'), trigger()]);
  const downloadPath = path.join(downloadDir, await download.suggestedFilename());
  await download.saveAs(downloadPath);
  return downloadPath;
}

function getRequestLogFromZip(zipPath) {
  const zip = new AdmZip(zipPath);
  const entry = zip.getEntries().find((item) => item.entryName.includes('Request'));
  if (!entry) {
    throw new Error(`No Request entry found in ${zipPath}`);
  }
  return JSON.parse(entry.getData().toString('utf8'));
}

async function main() {
  if (!fs.existsSync(AUTH_PATH)) {
    throw new Error(`Missing auth session file at ${AUTH_PATH}`);
  }

  const env = readEnv(ENV_PATH);
  const createdOrder = await createOrderWithShortCities(env);
  console.log(`Created Shopify order ${createdOrder.name} (${createdOrder.id})`);

  const browser = await chromium.launch({
    channel: 'chrome',
    headless: false,
    args: ['--disable-blink-features=AutomationControlled'],
  });

  const context = await browser.newContext({
    storageState: AUTH_PATH,
    acceptDownloads: true,
    viewport: { width: 1400, height: 1000 },
  });

  const page = await context.newPage();
  const frame = page.frameLocator('iframe[name="app-iframe"]');
  let rateLogZipPath = '';

  try {
    await openAppViaSidebar(page, env);
    console.log(`Opened app from Shopify sidebar: ${await page.url()}`);

    await openManualLabelFromFedExApp(page, createdOrder.name);

    const generatePackagesButton = frame.getByRole('button', { name: 'Generate Packages' });
    try {
      await generatePackagesButton.waitFor({ state: 'visible', timeout: 30000 });
    } catch (error) {
      const failPath = path.join('/private/tmp', `manual-label-entry-missing-${Date.now()}.png`);
      await page.screenshot({ path: failPath, fullPage: false });
      throw new Error(`Manual label page did not open after Shopify handoff. Screenshot saved to ${failPath}. Current URL: ${page.url()}`);
    }

    await generatePackagesButton.click();
    await frame.getByRole('button', { name: 'Get shipping rates' }).click();
    await frame.locator('input[type="radio"][name]').first().waitFor({ state: 'visible', timeout: 60000 });

    const ratesMenu = frame
      .locator('.Polaris-Box')
      .filter({ hasText: 'Shipping rates from account' })
      .locator('button[aria-controls]');
    await ratesMenu.first().click();
    await frame.locator('button[role="menuitem"]').filter({ hasText: 'View Logs' }).first().click();
    await frame.getByRole('dialog').getByRole('heading', { name: 'Rates Log' }).waitFor({ state: 'visible', timeout: 15000 });

    const requestText = await frame.getByRole('dialog').locator('pre').first().innerText();
    const rateLogJson = JSON.parse(requestText.trim());
    const rateRequest = rateLogJson?.requestObject ?? rateLogJson;
    assertShortCitiesPreserved(rateRequest, 'Rate log request');

    const preBlocks = await frame.getByRole('dialog').locator('pre').allTextContents();
    const responseText = preBlocks[preBlocks.length - 1] || '';
    if (responseText.includes('CITY.TOO.SHORT')) {
      throw new Error('Rate log response still contained CITY.TOO.SHORT');
    }

    await frame.locator('div[role="dialog"][aria-modal="true"]').locator('button[aria-label="Close"]').click();

    const firstService = frame.locator('input[type="radio"][name]').first();
    const radioId = await firstService.getAttribute('id');
    if (!radioId) {
      throw new Error('Unable to resolve the first shipping service radio id');
    }
    await frame.locator(`label[for="${radioId}"]`).click();

    await frame.getByRole('button', { name: 'Generate Label' }).click();
    await frame.locator('text=label generated').waitFor({ state: 'visible', timeout: 90000 });
    console.log('Label generated successfully');

    await frame.getByRole('button', { name: 'More Actions' }).last().click();
    await frame.locator('.Polaris-Popover').first().waitFor({ state: 'attached', timeout: 10000 });
    await frame.locator('.Polaris-ActionList__Item').filter({ hasText: 'How To' }).click();
    await frame.locator('div[role="dialog"]').getByRole('heading', { name: 'How To' }).waitFor({ state: 'visible', timeout: 10000 });

    rateLogZipPath = await downloadFromClick(page, async () => {
      const clickHere = frame
        .locator('div')
        .filter({ hasText: 'Need request/response Logs to contact FedEx?' })
        .getByRole('button', { name: 'Click Here' })
        .last();
      await clickHere.click();
    });
    console.log(`Downloaded label request zip to ${rateLogZipPath}`);

    const labelLogJson = getRequestLogFromZip(rateLogZipPath);
    const labelRequest = labelLogJson?.requestObject ?? labelLogJson;
    assertShortCitiesPreserved(labelRequest, 'Label request zip');

    console.log('Verification passed: short shipping and billing city values were preserved in both requests');
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error?.stack || error);
  process.exit(1);
});
