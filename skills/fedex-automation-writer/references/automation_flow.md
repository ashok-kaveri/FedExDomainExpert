# Automation Flow

This reference mirrors `pipeline/automation_writer.py` and `pipeline/chrome_agent.py`.

## Dashboard Flow

1. Find existing POM via registry/keyword matching.
2. Navigate to real page with stored auth/session and capture live elements.
3. Existing POM:
   - append new locators/methods
   - create separate new spec file
4. New page:
   - create new POM
   - update fixtures
   - create new spec
5. Review generated code.
6. Optional run/fix loop.
7. Commit/push only when requested.

## Existing POM Priority

Always search before creating:

- POM registry in `pipeline/automation_writer.py`
- automation repo page objects
- matching specs
- helper files
- fixture names

Use `rg` first.

## Common POM Areas

- Additional Services: dry ice, duties, tax, signature, saturday delivery, one rate, alcohol, dangerous goods, hold at location
- Packaging Settings: packaging, boxes, dimensions, weight based packing
- Manual Label Page: single/manual label generation
- Pickup Page: pickup scheduling/details
- Return Label Page: return labels/settings
- Shipping Page: rate settings, carrier services, checkout rates
- Products Page: product special services / Shopify product setup
- Order Summary Page: label generated, fulfillment, order grid

## Automatable Case Filter

Prefer:

- Positive cases
- UI-safe Edge cases
- stable browser paths
- meaningful business assertions

Usually skip:

- backend-only failures
- API mocking
- server timeout/error injection
- unstable negative paths requiring external failures
- cases already fully covered by existing tests unless the AC requires an explicit regression spec

## Assertions

Prefer final-state assertions:

- label generated status
- success toast
- saved setting persisted after reopen
- printed/downloaded documents visible
- pickup confirmation/status
- order row status/filter result
- request/log row present when helper exists
- specific warning/error text

Avoid:

- page is visible only
- button exists only
- arbitrary sleeps
- invented helper calls

## Critical Spec Contracts

Use the repo's fixture import path. Do not import `test`/`expect` from `@playwright/test` in spec files when the repo uses setup fixtures.

Store declaration:

```ts
const store = process.env.STORE;
if (!store) {
  throw new Error('STORE environment variable is required');
}
```

Order creation must be a dedicated test block:

```ts
test('Create an order from API', async () => {
  orderUploader = new ShopifyOrderUploader();
  const orderID = await orderUploader.uploadOrder();
  if (!orderID) {
    throw new Error('Failed to create Shopify order');
  }
  sharedOrderID = orderID;
  expect(orderID).toBeTruthy();
});
```

