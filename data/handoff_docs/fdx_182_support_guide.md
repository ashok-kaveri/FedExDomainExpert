# Support Guide — From SL: FDX-182 — Fix null postalCode for postal-code-optional countries (rate + label paths) [#373546, #387822, #387886]

## Release Details
- Feature Reference: FDX-182
- Trello: https://trello.com/c/c7uHEny2
- App Release: Patch deploy required
- Approved: Not stated on the card
- Developed by: Unknown
- Tested by: QA Team

## Feature Summary
This fix addresses a FedEx REST shipping failure for countries where postal codes are optional or not normally used. Before this change, the app could pass a `null` or empty postal code into FedEx requests, which caused rate requests and label requests to fail.

The update covers both major paths called out on the card: checkout rate requests and label generation requests. The implementation note on the card also confirms that the country coverage was expanded significantly, including GCC, AMEA, sub-Saharan Africa, and Hong Kong.

From a support perspective, the key outcome is simple: merchants shipping to affected countries should now be able to see FedEx rates and generate labels without being blocked by a postal-code validation error.

## Toggles & Prerequisites
- No merchant-facing toggle is expected for this fix. The card notes that the previous feature-flag gate was removed in the implementation.
- This is a patch-deploy change, so the fix depends on the patched build being deployed to the merchant's store.
- Scope specifically includes postal-code-optional countries mentioned on the card and in QA verification, including QA, KW, OM, BH, SA, HK, JO, IQ, UAE, and similar supported countries in the expanded config list.
- Hong Kong is a special case in the implementation: the payload should use `000000`.
- UAE has a separate fallback path that can use mapped state-based values when needed.

## Where to Find This in the App
- Merchant storefront checkout → review FedEx rates for a shipping address in an affected postal-code-optional country.
- Shopify admin → Orders → click order → More Actions → "Generate Label"
- Shopify admin → Orders → click order → More Actions → "Auto-Generate Label"
- After label generation, FedEx app → Order Summary page

## Step-by-Step Walkthrough (Support / Demo)
### Scenario A — Confirm rates now load for an affected country
1. Use a store where FedEx rates are enabled at checkout.
2. Create or use a shipping address in one of the affected countries such as Hong Kong, Qatar, Kuwait, Oman, Bahrain, Saudi Arabia, Jordan, Iraq, or UAE.
3. Go through the storefront checkout flow and enter the shipping address.
4. Confirm that FedEx rates are returned instead of failing because of a missing or null postal code.
5. If needed, compare with the old failure pattern described on the card: FedEx rejected requests when `postalCode` was sent as `null`.

### Scenario B — Confirm manual label generation works
1. In Shopify admin, open Orders.
2. Click the target order.
3. Click More Actions → "Generate Label".
4. On the FedEx manual label page, use the normal package and rate-selection flow.
5. Click "Generate Label".
6. Confirm the app reaches the Order Summary page and shows the generated label flow instead of failing on postal-code validation.

### Scenario C — Confirm auto label generation works
1. In Shopify admin, open Orders.
2. Click the target order.
3. Click More Actions → "Auto-Generate Label".
4. Confirm the app completes label generation automatically and lands on the Order Summary page.
5. Verify that the order does not fail because of a postal-code-related validation issue.

## Expected Behaviour — What Support Should Observe
- FedEx rates should load successfully for supported postal-code-optional countries.
- Manual label generation should complete successfully for affected destinations.
- Auto label generation should complete successfully for affected destinations.
- The failure pattern "postalCode cannot be null" should no longer appear for the covered countries after the patch is deployed.
- Hong Kong shipments should succeed even though Shopify does not expose a postal-code field in the address form.
- The card's implementation note indicates the backend now avoids sending invalid null or empty postal-code values in these scenarios.

## Business-Safe Explanation (For Merchant-Facing Communication)
This update improves FedEx shipping reliability for countries where postal codes are optional or commonly unavailable. Merchants should now be able to retrieve FedEx rates and generate labels more consistently for those destinations without needing a workaround.

For Hong Kong in particular, this resolves a painful case where Shopify may not show a postal-code field at all. The merchant should experience a smoother checkout and shipping workflow rather than a FedEx validation failure.

## Common Questions & Troubleshooting
**Q: What problem does this fix solve?**
A: It fixes shipping failures caused by invalid postal-code handling for countries where postal codes are optional or not normally used.

**Q: Is this only a checkout-rates fix?**
A: No. The card explicitly scopes this to both rate requests and label-generation requests.

**Q: Does the merchant need to enable anything?**
A: The implementation note says the previous feature-flag gate was removed, so support should treat this as a deployed product fix rather than a merchant-side toggle.

**Q: What should support check first if a merchant still reports failure?**
A: Confirm the store is on the patched deployment, confirm the destination country is in scope, and capture whether the issue happens at checkout rates, manual label generation, auto label generation, or all three.

**Q: What is special about Hong Kong?**
A: The card notes that Shopify can hide the postal-code field for Hong Kong addresses, so the fix includes a specific Hong Kong handling path.

**Q: What should support collect before escalating?**
A: Collect the store URL, destination country, the exact flow that failed, the order number if label generation was involved, and the visible error message or screenshots.

## Known Limitations / Rollout Notes
- This document is based on the Trello card, implementation note, and QA verification comment.
- The card calls this a patch deploy, so merchants will not benefit until the patched version is live.
- The card mentions expanded country coverage in config, but support should still verify exact country-specific reports against the deployed build if a new country is reported.
- QA verification on the card explicitly lists PASS coverage for checkout rates, auto label generation, and manual label generation across multiple countries.

## References
- [Trello card](https://trello.com/c/c7uHEny2)
- [PluginHive FedEx docs](https://www.pluginhive.com/product/fedex-shipping-plugin-for-shopify/)
