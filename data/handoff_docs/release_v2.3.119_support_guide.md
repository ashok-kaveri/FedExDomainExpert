# Support Guide — From SL: FDX-108 — Chile domestic FedEx services not mapped in app [#383123]

## Release Details
- Feature Reference: `FDX-108`
- Trello: https://trello.com/c/9RyBQrjC/4284-from-sl-fdx-108-chile-domestic-fedex-services-not-mapped-in-app-383123
- App Release: `v2.3.119`
- Approved: Unknown
- Developed by: Unknown
- Tested by: QA Team

## Feature Summary
This change restores the correct FedEx domestic service mapping for Chile-based merchants. Before this fix, Chile domestic shipments could miss valid FedEx domestic services in the app, or the store could fall back to incorrect region defaults instead of using Chile-specific service mappings.

With this release, Chile domestic rate requests are expected to return the correct service list for Chile, including `FEDEX_ECONOMY_FREIGHT` where applicable. Support should also see the service displayed with the expected app label rather than a blank or undefined value in rate-related views.

## Toggles & Prerequisites
- No feature toggle is required.
- This is relevant for Chile (`CL`) merchants using FedEx domestic services.
- The migration `20260430060000-add_fedex_economy_freight_service.js` must be applied for shops that need the Chile service backfill.
- The store must already have a valid Chile FedEx account and a Chile domestic order available for testing.

## Where to Find This in the App
- Shopify checkout or order-rate flow for Chile domestic shipments
- FedEx app rate-related views for returned services
- Rates Log / rate history view where service names are shown

## Step-by-Step Walkthrough (Support / Demo)
### Scenario A - Chile domestic order returns the expected service
1. Open a Chile-based store that has the PluginHive FedEx app configured.
2. Use or create a test order with a Chile domestic destination.
3. Trigger a shipping rate request.
4. Confirm the service list includes the expected Chile domestic options.
5. Confirm `FEDEX_ECONOMY_FREIGHT` appears where applicable and is shown with the expected service label.

### Scenario B - Rate log shows the service cleanly
1. Open the FedEx app and go to the rate history or Rates Log view.
2. Search for a recent Chile domestic request that returned `FEDEX_ECONOMY_FREIGHT`.
3. Confirm the entry displays a readable service name such as `FedEx Economy Freight`.
4. Confirm support does not see blank labels or `undefined` values for that service.

### Scenario C - Label generation still works with the mapped Chile service
1. Open an order that already has the Chile domestic service assigned.
2. Generate the label as usual.
3. Confirm the label is created successfully and the shipment continues normally after service selection.

## Expected Behaviour - What Support Should Observe
- Chile domestic shipments return Chile-appropriate services instead of falling back to the wrong region behavior.
- `FEDEX_ECONOMY_FREIGHT` is available when expected.
- The service name is displayed properly in the UI and rates log.
- Label generation continues successfully for orders using the mapped service.

## Business-Safe Explanation (For Merchant-Facing Communication)
> We corrected the service mapping for Chile domestic shipments so the app now returns the right FedEx options for Chile-based orders. Merchants should see the expected domestic services again without needing to change their day-to-day workflow.

## References
- Trello card: https://trello.com/c/9RyBQrjC/4284-from-sl-fdx-108-chile-domestic-fedex-services-not-mapped-in-app-383123
- Release: `v2.3.119`

---

# Support Guide — From SL: FDX-008 — SLGP account selection follows ship-to country [#361816]

## Release Details
- Feature Reference: `FDX-008`
- Trello: https://trello.com/c/Sld6AH9F/4291-from-sl-fdx-008-slgp-account-selection-follows-ship-to-country-361816
- App Release: `v2.3.119`
- Approved: Unknown
- Developed by: Unknown
- Tested by: QA Team

## Feature Summary
This change improves how the Shipping Label Generation Page (SLGP) chooses the FedEx account that is pre-selected for an order. Instead of using a less reliable default, the app now follows the ship-to country when account conditions are configured.

For support teams, this means the initial account shown on the label page should usually match the destination-country rules the merchant configured in `Settings > Accounts`. Merchants can still manually change the account before label generation when needed.

## Toggles & Prerequisites
- No feature toggle is required.
- Multiple FedEx accounts must be configured for the store to see the main benefit.
- Country-based account conditions must be set in `Settings > Accounts` if the merchant wants different accounts for different destinations.
- If only one account exists, the single account should continue to behave as before.

## Where to Find This in the App
- Orders list
- Order Details / SLGP
- FedEx Account Selector dropdown on the label-generation flow

## Step-by-Step Walkthrough (Support / Demo)
### Scenario A - UK order pre-selects the secondary account
1. Open a store with more than one FedEx account configured.
2. Confirm country conditions are set so UK orders should use the secondary account.
3. Open an order where the ship-to country is `UK`.
4. On SLGP, inspect the FedEx Account Selector.
5. Confirm the secondary account is already selected before label generation.

### Scenario B - Merchant overrides the suggested account
1. Stay on the same order after the correct account is pre-selected.
2. Open the FedEx Account Selector dropdown.
3. Change the selection from the suggested account to another available account.
4. Generate the label.
5. Confirm the label uses the manually selected account, not the original pre-selected value.

### Scenario C - Unmapped country falls back cleanly
1. Open an order whose ship-to country does not have a country rule.
2. Inspect the FedEx Account Selector.
3. Confirm the app falls back to the primary/default account.
4. Confirm the order can still proceed without an account-selection error.

## Expected Behaviour - What Support Should Observe
- The pre-selected account should match the ship-to country rule when one exists.
- Manual override should still work.
- Unmapped, invalid, or unsupported country conditions should fall back gracefully to the primary account.
- Account selection should resolve independently for each order rather than carrying over from a previous order.

## Business-Safe Explanation (For Merchant-Facing Communication)
> We improved account selection during label generation so the app now chooses the most appropriate FedEx account based on the destination country when country rules are configured. Merchants can still change the account manually before generating a label if they need to make a one-off adjustment.

## References
- Trello card: https://trello.com/c/Sld6AH9F/4291-from-sl-fdx-008-slgp-account-selection-follows-ship-to-country-361816
- Release: `v2.3.119`

---

# Support Guide — From SL: FDX-007 — Commercial invoice letterhead/signature missing for secondary account

## Release Details
- Feature Reference: `FDX-007`
- Trello: https://trello.com/c/fxhDuYXW/4286-from-sl-fdx-007-commercial-invoice-letterhead-signature-missing-for-secondary-account
- App Release: `v2.3.119`
- Approved: Unknown
- Developed by: Unknown
- Tested by: QA Team

## Feature Summary
This release fixes a branding gap on commercial invoices generated with a secondary FedEx account. Before this change, merchants using a secondary account could end up with a commercial invoice that did not show the expected letterhead or signature for that selected account.

With the fix in place, commercial invoices generated with a secondary account should use that account's own branding assets when those assets are configured. The release also preserves graceful behavior when a secondary account does not yet have one or both assets uploaded.

## Toggles & Prerequisites
- No feature toggle is required.
- This applies to international shipments that produce a commercial invoice.
- The store must have more than one FedEx account configured to validate the secondary-account behavior.
- To see the full effect, the relevant letterhead and signature files must be uploaded for the secondary account.

## Where to Find This in the App
- `Settings > Accounts` for per-account setup and persistence checks
- International shipping label workflow
- Commercial Invoice PDF downloaded after label generation

## Step-by-Step Walkthrough (Support / Demo)
### Scenario A - Secondary account commercial invoice shows the correct branding
1. Confirm the store has both primary and secondary FedEx accounts configured.
2. Confirm the secondary account has its own letterhead and signature files uploaded.
3. Open an international order that requires a commercial invoice.
4. Generate the label and explicitly select the secondary account.
5. Download the commercial invoice PDF.
6. Confirm the invoice shows the secondary account's branding, not the primary account's branding.

### Scenario B - Primary account remains unchanged
1. Generate a commercial invoice using the secondary account and verify its branding.
2. Then generate another international label using the primary account.
3. Download the second commercial invoice PDF.
4. Confirm the primary account's commercial invoice still shows the primary account's own branding.
5. Confirm there is no cross-account branding mix-up.

### Scenario C - Missing assets degrade gracefully
1. Use a secondary account that does not have one or both branding assets uploaded.
2. Generate an international label that produces a commercial invoice.
3. Download the invoice PDF.
4. Confirm the invoice still generates successfully.
5. Confirm the missing asset is simply absent rather than breaking the invoice layout or blocking the workflow.

## Expected Behaviour - What Support Should Observe
- Commercial invoices generated with the secondary account show the secondary account's configured letterhead and signature.
- Primary-account invoices continue to show primary-account branding.
- If a secondary account is missing one or both assets, invoice generation still succeeds and the layout remains usable.
- Upload persistence and validation should behave normally when account-level upload controls are available.

## Business-Safe Explanation (For Merchant-Facing Communication)
> We fixed commercial invoice branding for stores that use more than one FedEx account. When a merchant generates an international shipment with a secondary account, the invoice should now reflect that selected account's branding more reliably, while still generating cleanly if optional branding files are missing.

## References
- Trello card: https://trello.com/c/fxhDuYXW/4286-from-sl-fdx-007-commercial-invoice-letterhead-signature-missing-for-secondary-account
- Release: `v2.3.119`
