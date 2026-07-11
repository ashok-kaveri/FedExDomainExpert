import ShopifyOrderUploader from '/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation/src/helpers/createOrder';
import { test, expect } from '/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation/src/setup/fixtures';

const store = process.env.STORE;

if (!store) {
  throw new Error('STORE environment variable is required');
}

async function ensureShopifySession(pages: Parameters<typeof test>[0] extends never ? never : any) {
  const email = process.env.USER_EMAIL || 'ashok@pluginhive.com';
  const password = process.env.USER_PASSWORD || '';

  const emailInput = pages.sharedPage.locator('#account_email');
  if (await emailInput.isVisible().catch(() => false)) {
    await emailInput.fill(email);
    await pages.sharedPage.locator('button:has-text("Continue with email")').click();
    await pages.sharedPage.waitForLoadState('domcontentloaded');

    const passwordInput = pages.sharedPage.locator('#account_password');
    if (await passwordInput.isVisible().catch(() => false)) {
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

  const storeSearchVisible = await pages.shopifyStoreSelectionPage.storeSearchInput.isVisible().catch(() => false);
  if (storeSearchVisible) {
    await pages.shopifyStoreSelectionPage.selectStoreAndProceed(store);
    await pages.sharedPage.waitForLoadState('domcontentloaded');
  }
}

test.describe.configure({ mode: 'serial' });

test.describe('Auto Label Generation Flow Repo Native', () => {
  let sharedOrderID: string;
  let orderUploader: ShopifyOrderUploader;

  test.beforeAll(async () => {
    orderUploader = new ShopifyOrderUploader();
    const orderID = await orderUploader.uploadOrderWithMultipleProducts([{ productType: 'simple', productIndexes: [1], quantities: [1] }]);
    if (!orderID) throw new Error('Failed to create Shopify order');
    sharedOrderID = orderID;
    console.log(`Order created: ${sharedOrderID}`);
  });

  test('auto label generation updates grid to label generated', async ({ pages }) => {
    test.setTimeout(180000);

    await pages.sharedPage.goto(`https://admin.shopify.com/store/${store}`);
    await ensureShopifySession(pages);

    await pages.shopifyAdmin.searchButton.waitFor({ state: 'visible', timeout: 60000 });
    await pages.shopifyAdmin.searchAndOpenOrder(sharedOrderID, 5);
    await pages.shopifyAdmin.openMoreActions();
    await pages.shopifyAdmin.clickOnAutoLabelGeneration();
    await pages.shippingPage.orderGridColumnValidation(sharedOrderID, 'Label status', 'label generated');
    await expect(pages.shippingPage.ordersTable).toContainText('label generated', { timeout: 10000 });
  });
});
