# Support Guide — SL v2.3.120 FedexApp: Iteration backlog

## Release Overview
- **Lane:** `SL v2.3.120 FedexApp: Iteration backlog`
- **Board:** `pH WIP`
- **App Release:** `v2.3.120`
- **Cards:** `6`

## Trello Card Index
- [From SL: FDX-178 — AMEA null postal code regression — no rates for postal-code-optional countries [#373546]](https://trello.com/c/55MjKcHg/4383-from-sl-fdx-178-amea-null-postal-code-regression-no-rates-for-postal-code-optional-countries-373546)
- [From SL: FDX-177 — TotalDeclaredValue wrong on first label pass with insurance [#387875]](https://trello.com/c/eUuEoTUf/4384-from-sl-fdx-177-totaldeclaredvalue-wrong-on-first-label-pass-with-insurance-387875)
- [From SL: FDX-009 — Account-wise International settings [#361816]](https://trello.com/c/RWcypBSa/4385-from-sl-fdx-009-account-wise-international-settings-361816)
- [From SL: FDX-003 — Misleading fulfillment address dropdown [#284130]](https://trello.com/c/Sk0nPN3F/4386-from-sl-fdx-003-misleading-fulfillment-address-dropdown-284130)
- [From SL: FDX-179 — FedEx REST Dangerous Goods (DG) / Hazmat Integration [#389072]](https://trello.com/c/totZWi5o/4426-from-sl-fdx-179-fedex-rest-dangerous-goods-dg-hazmat-integration-389072)
- [From SL: FDX-193 — Zendesk Messaging Feature Flag — Switch webWidget to Messenger API](https://trello.com/c/HYXxSa0U/4523-from-sl-fdx-193-zendesk-messaging-feature-flag-switch-webwidget-to-messenger-api)

---


# From SL: FDX-178 — AMEA null postal code regression — no rates for postal-code-optional countries [#373546]

**Trello:** [From SL: FDX-178 — AMEA null postal code regression — no rates for postal-code-optional countries [#373546]](https://trello.com/c/55MjKcHg/4383-from-sl-fdx-178-amea-null-postal-code-regression-no-rates-for-postal-code-optional-countries-373546)

---

> ⚠️ **QA NOTE — Navigation Confirmation Needed**
> The following navigation steps could not be determined from available sources
> (AI QA evidence, frontend/backend code, AC text).
> Please confirm the exact steps before sharing this document:
>
> - [ ] **Where to find (Rates Log)**: Confirm the exact label/path for the Rates Log section in the app sidebar and whether rate request/response JSON is accessible per-order or only as a global log.
> - [ ] **Step 6 (Log inspection)**: Confirm the exact UI steps to locate a rate request log entry and verify the `postalCode` field value for an AMEA destination order.
>
> Once confirmed, update the Walkthrough section with the actual steps.

---

# FDX-178 — AMEA Null Postal Code Regression Fix
### Support & Demo Guide | SL v2.3.120 | FedEx Shopify App

---

## Feature Summary

Merchants shipping to countries in the **AMEA region** (Africa, Middle East, and Asia) where a postal code is **not required** — such as the UAE, Qatar, Kuwait, Bahrain, Oman, Saudi Arabia, Nigeria, and 40+ others — were receiving **no shipping rates at checkout** after a prior code change introduced a regression.

**What went wrong:** A previous update changed how the app checked for an empty postal code. Instead of sending the accepted placeholder value `'--'` to FedEx, the app began sending `null`. FedEx's REST API rejects `null` as a postal code value and returns no rates in response.

**What was fixed:** The app now correctly sends `'--'` as a placeholder for all 46+ AMEA countries where a postal code is not required. UAE addresses with unrecognised state codes also fall back safely to `'--'`. Countries that *do* require a postal code (US, UK, Canada, Australia, Germany, etc.) are completely unaffected.

**Customer impact before fix:** Merchants with buyers in postal-code-optional AMEA countries saw $0 / no rates at Shopify checkout, blocking sales entirely for those destinations.

---

## Developed By
Unknown *(see Trello card for PR author — PR #824 / #835)*

## Tested By
Madan Kumar AS, Basavaraj

---

## Toggle / Prerequisites

| Item | Detail |
|---|---|
| **Feature toggle** | `isEmptyPostalCodeFeatureEnabled` in `featureToggles.json` — must remain **enabled** |
| **Co-change risk** | `fedexRestRequestBuilder.js` has **40 co-change partners**; this is a high-traffic path |
| **App version** | Fix shipped in **SL v2.3.120** (commit `cc12a15f`, branch `bug/fdx-178-amea-null-postal-code`) |
| **Prior partial fix** | Qatar and Kuwait were partially fixed in v2.3.115; this release extends coverage to 46+ AMEA countries |
| **Shopify prerequisite** | PluginHive calculated rates must be enabled in the merchant's Shopify shipping profile for the relevant location |
| **No merchant action required** | This is a backend fix — merchants do not need to change any settings |

---

## Where to Find This Feature in the App

This fix operates silently in the **rate request pipeline** — there is no new UI element or toggle visible to merchants or support agents. The relevant areas to observe or verify the fix are:

**To observe rate behaviour at checkout:**
> Shopify storefront checkout → shipping address for an AMEA country → shipping rate options displayed

**To inspect rate request/response logs:**
> App sidebar (inside iframe) → **Rates Log**
> *(Confirm exact log access steps with QA — see note at top of document)*

**To verify the feature toggle is active:**
> App sidebar → **Settings** → *(confirm exact sub-section with QA)*

---

## Step-by-Step Walkthrough (Support / Demo)

Use this walkthrough to **verify the fix is working** for a merchant reporting missing rates for an AMEA destination.

### Step 1 — Confirm the destination country is in the AMEA list

Check whether the buyer's shipping country is one of the 46+ postal-code-optional AMEA countries now covered by the fix. Key countries include:

- **Middle East:** UAE, Qatar, Kuwait, Bahrain, Oman, Saudi Arabia, Jordan, Iraq, Yemen, Syria
- **Africa:** Nigeria, Ethiopia, Ghana, Tanzania, Uganda, Zambia, Zimbabwe, + 32 additional African countries

If the country is **not** in this list (e.g. US, UK, Canada, Australia, Germany), the fix does not apply — the actual postal code should be passing correctly and rates should work as before.

### Step 2 — Reproduce or confirm the rate request

Ask the merchant to:
1. Go to their **Shopify storefront**
2. Add a product to cart and proceed to checkout
3. Enter a shipping address in the affected AMEA country (postal code field left blank or not applicable)
4. Observe whether **FedEx shipping rates appear**

**Expected result after fix:** FedEx rates are displayed at checkout for the AMEA destination.
**Result before fix / if regression returns:** No rates shown, or a blank/zero-rate result.

### Step 3 — Check the Rates Log for the request

1. Open the FedEx app inside Shopify admin
2. Navigate to **Rates Log** in the app sidebar
3. Locate the rate request corresponding to the merchant's test order
4. Inspect the request JSON — confirm the `postalCode` field shows `'--'` (not `null` and not an empty string) for the AMEA destination
5. Inspect the response JSON — confirm FedEx returned valid rate options

> ⚠️ *Exact UI steps for Rates Log inspection to be confirmed by QA — see note at top of document.*

### Step 4 — Confirm postal-code-required countries are unaffected

If the merchant also ships to the US, UK, Canada, Australia, or Germany, run a quick checkout test for one of those destinations and confirm:
- The actual postal code is still being sent correctly
- Rates are returned as expected

---

## Expected Behaviour — What Support Should Observe

| Scenario | Expected Result |
|---|---|
| Buyer in UAE, Qatar, Kuwait, Bahrain, Oman, Saudi Arabia, or other AMEA postal-code-optional country | FedEx rates appear at Shopify checkout |
| UAE address with an unrecognised state/emirate code | App falls back to `'--'` placeholder; rates still returned |
| Buyer in US, UK, Canada, Australia, Germany (postal code required) | Actual postal code sent; rates returned as normal — no change |
| Qatar / Kuwait (fixed in v2.3.115) | Still working; not regressed by this release |
| `postalCode: null` in rate request log | **Should not occur** — if seen, escalate as a regression |

---

## Business-Safe Explanation (For Merchant Conversations)

> "FedEx's system requires a specific placeholder value when a shipping destination doesn't use postal codes — for example, the UAE or Nigeria. A recent update accidentally caused our app to send a blank value instead of that placeholder, which FedEx rejected, resulting in no shipping rates being shown at checkout. We've corrected this so the right value is sent automatically. No action is needed on your end — the fix is live and rates should now appear correctly for all affected countries."

---

## Common Questions & Troubleshooting

**Q: A merchant says they still see no rates for an AMEA country after v2.3.120. What should I check?**
- Confirm the destination country is in the expanded 46+ AMEA list. If it is not yet included, escalate for a `localConfig.json` addition.
- Check the Rates Log to see if `postalCode: null` is still appearing in the request — if so, the toggle `isEmptyPostalCodeFeatureEnabled` may be disabled. Confirm it is set to `true`.
- Verify that PluginHive's calculated rates are enabled in the merchant's Shopify shipping profile for the relevant location (Settings → Locations in the app).
- Confirm the merchant's FedEx account has the relevant services enabled for that destination.

**Q: Qatar and Kuwait were supposedly fixed before — are they still working?**
- Yes. Qatar and Kuwait received a partial fix in v2.3.115. This release does not remove that fix; it extends the same logic to 46+ countries. Both should still work. If a merchant reports otherwise, treat it as a regression and escalate.

**Q: Does the merchant need to re-enter or update any addresses?**
- No. The fix is entirely on the app's backend rate request logic. No address changes are needed by the merchant or their customers.

**Q: Will this affect how labels are generated, or only checkout rates?**
- This fix specifically addresses the **rate request** path (checkout rates). Label generation uses a related but separate flow. If a merchant reports label generation issues for AMEA countries, investigate separately.

**Q: The merchant's buyer entered a postal code for a country like UAE — will that cause problems?**
- If a valid UAE postal code is entered, the UAE state-code mapper will attempt to use it. If the state code is unrecognised, the app now falls back to `'--'` safely. Rates should still be returned.

---

## Known Limitations & Rollout Notes

- **No automated test coverage exists** for `getPostalCodeFrom()` postal code logic. All verification for this fix is manual QA. A unit test suite has been flagged as needed.
- **46+ AMEA countries** are now covered, but the list is not exhaustive of every country in the world that does not use postal codes. If a merchant reports a missing country, it can be added to `localConfig.json` in a future patch.
- **Medium risk release** — `fedexRestRequestBuilder.js` is a central, high-traffic file with 40 co-change partners. Regression testing on US/UK/CA/AU/DE destinations is important after any future


---


# From SL: FDX-177 — TotalDeclaredValue wrong on first label pass with insurance [#387875]

**Trello:** [From SL: FDX-177 — TotalDeclaredValue wrong on first label pass with insurance [#387875]](https://trello.com/c/eUuEoTUf/4384-from-sl-fdx-177-totaldeclaredvalue-wrong-on-first-label-pass-with-insurance-387875)

# FedEx App — Support Guide
## FDX-177: TotalDeclaredValue Incorrect on First Label Pass with Insurance

---

> ⚠️ **QA NOTE — Navigation Confirmation Needed**
> The following navigation steps could not be determined from available sources
> (AI QA evidence, frontend/backend code, AC text).
> Please confirm the exact steps before sharing this document:
>
> - [ ] **Where to find**: _Exact location of the Insurance checkbox and declared value entry within the SideDock — confirm the pencil icon / modal flow is live and matches the navigation structure description_
> - [ ] **Step 6 (Walkthrough)**: _Confirm whether the declared value modal shows a pre-populated value on first open, and whether it reflects the corrected (live) price post-fix_
> - [ ] **Step 8 (Walkthrough)**: _Confirm the exact field label shown in the FedEx request log (Rates Log) for TotalDeclaredValue, and whether it is visible to support without backend access_
>
> Once confirmed, update the Walkthrough section with the actual steps.

---

## Feature Summary

Prior to this fix, when a merchant generated a FedEx shipping label for an **insured order on the first attempt**, the `TotalDeclaredValue` sent to FedEx was calculated using a **stale product price stored in the app's database** (set at the time of last product sync), rather than the **current Shopify order line item price**.

This caused:
- Incorrect (under- or over-declared) insured values on first-pass label generation
- FedEx API errors such as *"Carriage value exceeds customs value"* on international shipments
- A frustrating workaround where merchants had to open the package editor, make no changes, and click **Save** — which triggered a client-side recalculation using the correct live price

This fix ensures the **live Shopify order price** is always used when calculating declared value on first pass, making the workaround unnecessary.

---

## Developed By

Unknown *(see Trello card for PR details)*

## Tested By

- Keerthanaa Elangovan
- Anuja B

---

## Toggles / Prerequisites

| Item | Detail |
|---|---|
| Feature toggle | None — fix is applied automatically for all merchants |
| Insurance must be enabled | Merchant must have Insurance enabled on the label (SideDock → Insurance checkbox) |
| Affected insurance modes | **Declared Value** mode (primary); **Percentage of Product Price** mode (regression-verified) |
| Affected label types | Manual label generation, Auto-label generation, Bulk label generation |
| Not affected | Non-insured domestic labels, Freight labels (guarded separately) |
| App version | SL v2.3.120 |
| Release iteration | FedEx App — Iteration Backlog |

---

## Where to Find This Feature

This fix operates silently in the background during label generation. There is no new UI element. The corrected behaviour is observed during the standard **Manual Label Generation** flow with Insurance enabled.

**Path:**

```
Shopify Admin → Orders → [select order] → More Actions → Generate Label
→ SideDock (right panel) → Insurance (checkbox + pencil icon → declared value modal)
→ Generate Label button
```

To verify the fix via logs:

```
FedEx App sidebar → Rates Log → locate the relevant order → inspect TotalDeclaredValue in request JSON
```

---

## Step-by-Step Walkthrough (Support / Demo)

Use this walkthrough to demonstrate or verify the fix for a merchant.

### Preparation

Before starting, ensure:
- The test order contains at least one line item where the **current Shopify product price differs from the price at the time of last product sync** in the app (this is the scenario that previously triggered the bug)
- Insurance is configured on the order

---

### Steps

**Step 1 — Open the order in Shopify Admin**

Navigate to **Shopify Admin → Orders** and click the relevant order row.

---

**Step 2 — Open the label generation page**

Click **More Actions** (top-right of the order page) → click **Generate Label**.

The FedEx app label page opens inside the iframe.

---

**Step 3 — Locate the Insurance option in the SideDock**

On the **right panel (SideDock)**, scroll to the **Insurance** section.

- Tick the **Insurance** checkbox
- Click the **pencil icon** next to Insurance
- The declared value modal opens

---

**Step 4 — Note the declared value shown**

Observe the declared value displayed in the modal.

> ✅ **Post-fix expected behaviour:** The value should reflect `line item price × quantity` for all line items in the order, using the **current Shopify order price** — not a historical synced price.

Close the modal.

---

**Step 5 — Generate the label (first pass)**

On the **left panel**, click **Get Rates** → select a rate using the radio button → click **Generate Label**.

The app redirects to the **Order Summary** page.

---

**Step 6 — Confirm label generated without error**

On the Order Summary page, confirm:
- Label was generated successfully (no FedEx API error displayed)
- No *"Carriage value exceeds customs value"* error (previously common on international insured orders)

---

**Step 7 — (Optional) Verify via Rates Log**

Navigate to **FedEx App sidebar → Rates Log**.

Locate the request for this order and inspect the `TotalDeclaredValue` field in the outbound JSON.

> ✅ **Expected:** `TotalDeclaredValue` = sum of (`lineItem.price × lineItem.quantity`) for all insured line items — matching the current Shopify order values.

---

## Expected Behaviour — What Support Should Observe

| Scenario | Before Fix | After Fix |
|---|---|---|
| First-pass label with insurance (Declared Value mode) | `TotalDeclaredValue` used stale DB price; may be wrong | `TotalDeclaredValue` uses current Shopify order price ✅ |
| First-pass label with insurance (% of product price mode) | % applied to stale price | % applied to current order price ✅ |
| Edit package → Save (no changes) → Generate Label | Workaround that forced correct recalculation | No longer needed; first pass is now correct ✅ |
| Non-insured domestic label | Unaffected | Unaffected ✅ |
| Return label with insurance | Unaffected (separate flow) | Regression-verified ✅ |
| Freight label with insurance | Unaffected (guarded separately) | Regression-verified ✅ |
| FedEx API error: "Carriage value exceeds customs value" | Could occur on first pass for international insured orders | Should no longer occur due to correct declared value ✅ |

---

## Business-Safe Explanation (For Merchant-Facing Communication)

> When you enable insurance on a FedEx label, the app needs to tell FedEx the total declared value of the shipment — this is the amount FedEx will insure the package for.
>
> Previously, on the **first time** you generated a label for an order, the app was using an older saved price for your products (from the last time the app synced your product catalogue), rather than the actual price on the order. This could result in the wrong insured amount being sent to FedEx, and in some cases caused an error that prevented the label from being created at all.
>
> A workaround existed — opening the package editor and clicking Save without making any changes — but this was inconvenient and easy to miss.
>
> **This fix ensures the app always uses the actual price from your order when calculating the insured value**, so labels generate correctly on the first attempt.

---

## Common Questions & Troubleshooting

**Q: A merchant says they are still seeing the wrong declared value on first pass after the update. What should I check?**

- Confirm the merchant is on app version **SL v2.3.120 or later**. If not, escalate for update.
- Ask the merchant to check the **Rates Log** for the failed label request and share the `TotalDeclaredValue` and the expected value (order price × qty). This helps confirm whether the fix is applied.
- Check whether the merchant is using **Declared Value** or **Percentage of Product Price** insurance mode — both should be fixed, but confirm which mode is active.

---

**Q: A merchant says the "edit and save" workaround no longer works. Is that expected?**

Yes — the workaround is no longer needed. The first-pass label generation now produces the correct declared value. If a merchant reports the workaround is broken, reassure them it is intentionally superseded by the fix.

---

**Q: Will this affect merchants who do not use insurance?**

No. The fix only changes how `TotalDeclaredValue` is calculated when insurance is enabled. Non-insured labels are unaffected.

---

**Q: A merchant is getting a "Carriage value exceeds customs value" error on an international insured label. Is this related?**

This error was a known symptom of the bug — the stale declared value could exceed the customs value declared on the commercial invoice. After this fix, the declared value should align with the actual order price, resolving this error. If it persists post-fix, escalate — there may be a separate configuration issue with the merchant's customs value settings.

---

**Q: Does this affect the rates shown at Shopify checkout?**

No. Checkout rates are a separate flow. This fix only affects the declared value sent in the **label generation** request to FedEx.

---

**Q: Does the merchant need to re-sync their products for this fix to take effect?**

No. The fix bypasses the stale product database value entirely for label generation, using the live order price instead. No product re-sync is required.

---

## Known Limitations & Rollout Notes

| Item | Detail |
|---|---|
| **Risk level** | ⚠


---


# From SL: FDX-009 — Account-wise International settings [#361816]

**Trello:** [From SL: FDX-009 — Account-wise International settings [#361816]](https://trello.com/c/RWcypBSa/4385-from-sl-fdx-009-account-wise-international-settings-361816)

---

> ⚠️ **QA NOTE — Navigation Confirmation Needed**
> The following navigation steps could not be determined from available sources
> (AI QA evidence, frontend/backend code, AC text).
> Please confirm the exact steps before sharing this document:
>
> - [x] **Where to find** *(confirmed)*: The per-account fields live under **Settings → Account → (select account) → Duties & Payments section → newly added fields: "Terms of Sale" and "Purpose of Shipment"**.
> - [ ] **Step 4 / Step 5 (Walkthrough)**: _Exact label/name of the "Purpose of Shipment" and "Terms of Sale" dropdowns as rendered in the per-account form (i.e. whether they are labelled "Purpose of Shipment (Account Override)", "Use Global Setting", or similar)._
> - [ ] **Step 6 (Walkthrough)**: _Exact button name used to save account settings (e.g. "Save", "Update", "Save Settings") — not confirmed from available code snippets._
>
> Once confirmed, update the Walkthrough section with the actual steps.

---

# FDX-009 — Account-wise International Settings

**Internal Support & Demo Guide**
**Release:** SL v2.3.120
**Trello:** [https://trello.com/c/RWcypBSa](https://trello.com/c/RWcypBSa) | [Related card: https://trello.com/c/K5f0KVvh](https://trello.com/c/K5f0KVvh)

---

## Feature Summary

This feature allows merchants who have **multiple FedEx accounts** configured in the app to set **per-account overrides** for two international shipment fields:

- **Purpose of Shipment** (e.g. Sold, Gift, Not Sold, Personal Effects)
- **Terms of Sale** (e.g. DDP, DAP, EXW)

Previously, these values were only configurable at the **global level** (under International Shipping settings), and every account used the same values. With this feature, each account can now have its own override. If no override is set for an account, the app falls back to the global setting automatically.

> **In plain terms:** A merchant shipping commercial goods from Account A and personal gifts from Account B can now configure each account independently, without changing the global default.

---

## Developed By

Unknown *(not recorded on card)*

## Tested By

Preethi, Arshiya

---

## Toggles / Prerequisites

| Item | Detail |
|---|---|
| Feature toggle | None — feature is available to all merchants on v2.3.120+ |
| Minimum accounts required | **2 or more FedEx accounts** configured in the app to observe per-account override behaviour. Single-account merchants are unaffected (global settings continue to apply as before). |
| Shipment type | Per-account overrides apply to **international shipments only**. Domestic labels are not affected. |
| App version | SL v2.3.120 or later |

---

## Where to Find This Feature

**Path (confirmed):**

```
App Sidebar → Settings → Account → [select or open an individual account] → Duties & Payments section
```

The newly added **Terms of Sale** and **Purpose of Shipment** fields appear within the **Duties & Payments** section of the individual account's edit/detail view, separate from the global International Shipping settings.

**Global fallback settings remain at:**

```
App Sidebar → Settings → International Shipping
```

---

## Step-by-Step Walkthrough (Support / Demo)

### Scenario: Set a per-account Purpose of Shipment override

**Goal:** Demonstrate that Account B uses "Gift" while the global setting is "Sold."

1. Open the FedEx app inside Shopify admin.
2. In the app sidebar, click **Settings**.
3. Click **Account** (or the Accounts sub-section) and open the account you want to configure.
4. Within the account's detail/edit view, open the **Duties & Payments** section.
5. Find the **Purpose of Shipment** dropdown (newly added field in this section).
   - Select the desired value (e.g. **Gift**).
   - To revert to global behaviour, select **"Use Global Setting"** (or leave the field blank/unset).
6. Find the **Terms of Sale** dropdown in the same **Duties & Payments** section.
   - Select the desired value, or leave as **"Use Global Setting"** to inherit the global value.
7. Click **Save**.
8. To verify the override is working, generate an international label using this account:
   - Go to **Shopify Orders** → click an international order → **More Actions** → **Generate Label**.
   - Select the relevant FedEx account, get rates, and generate the label.
9. After label generation, navigate to **App Sidebar → Rates Log** and inspect the outbound request JSON.
   - Confirm that `purposeOfShipment` in the request reflects the **account-level value** (e.g. `GIFT`), not the global value.

---

## Expected Behaviour — What Support Should Observe

| Scenario | Expected Result |
|---|---|
| Account has a specific Purpose of Shipment set (e.g. Gift) | International label for that account uses **Gift**, regardless of global setting |
| Account has a specific Terms of Sale set | International label for that account uses the **account-level Terms of Sale** |
| Account has no override set / "Use Global Setting" selected | Label falls back to the **global International Shipping** values |
| Single-account merchant | No change — global settings apply as before |
| Domestic label generated via any account | Per-account international fields have **no effect** — domestic label unaffected |
| dutiesPaymentType (existing per-account field) | Continues to work as before — this feature does not change that behaviour |

---

## Business-Safe Explanation (For Merchant-Facing Use)

> *"If you ship internationally using more than one FedEx account — for example, one account for commercial sales and another for personal shipments — you can now set the Purpose of Shipment and Terms of Sale separately for each account. This means the correct customs information is automatically applied to each shipment without you having to change your global settings each time. If you only have one FedEx account, nothing changes for you."*

---

## Common Questions & Troubleshooting

### Q: I set a per-account Purpose of Shipment, but the label still uses the global value. Why?

**A (known issue — see Known Limitations):** There is a confirmed bug in v2.3.120 where opening an account's settings and saving without explicitly selecting a per-account value can cause the system to silently write a blank value, which then falls back to global. This makes the override appear non-functional.

**Workaround:** Ask the merchant to:
1. Open the account settings.
2. **Explicitly select** the desired Purpose of Shipment value from the dropdown (do not leave it at the default/blank state).
3. Save.
4. Generate a new international label and check the Rates Log to confirm the value.

If the issue persists after an explicit selection and save, escalate to the development team with the account ID and a Rates Log export.

---

### Q: Does this affect domestic shipments?

**A:** No. Per-account international settings only apply to international (cross-border) shipments. Domestic labels are not affected.

---

### Q: The merchant only has one FedEx account. Do they need to do anything?

**A:** No action needed. Single-account merchants are unaffected. Their global International Shipping settings continue to apply exactly as before.

---

### Q: Where can I verify which Purpose of Shipment value was actually sent on a label?

**A:** Navigate to **App Sidebar → Rates Log**, find the relevant shipment, and inspect the request JSON. Look for the `purposeOfShipment` field in the outbound payload.

---

### Q: Can the merchant set Terms of Sale per account as well?

**A:** Yes. Both **Purpose of Shipment** and **Terms of Sale** support per-account overrides. The behaviour is identical — set the value at account level to override global; leave it unset (or select "Use Global Setting") to inherit global.

---

### Q: What about Duties Payment Type — is that also per-account?

**A:** Duties Payment Type per-account was an existing feature and is **not changed** by this release. It should continue to work as before.

---

## Known Limitations & Rollout Notes

> ⚠️ **Active Bug — High Priority**

| Item | Detail |
|---|---|
| **Bug: Per-account override not taking effect on first save** | When an account is opened and saved without explicitly choosing a per-account value, the system saves a blank (`''`) value to the database. The label generation logic then sees `'' OR global` and correctly falls back to global — but this means the override appears broken even after the merchant sets a value, if the account was ever saved in this blank state. **Affected:** Multi-account merchants only. Single-account merchants unaffected. |
| **Root cause** | The server-side save handler does not treat empty string as "no override set." A targeted fix is pending (convert `''` → `undefined` in the account PUT handler for these two fields). |
| **Workaround** | Merchant must explicitly select the desired value and save. If the account was previously saved with a blank state, the fix will need to be deployed before the override reliably persists. |
| **


---


# From SL: FDX-003 — Misleading fulfillment address dropdown [#284130]

**Trello:** [From SL: FDX-003 — Misleading fulfillment address dropdown [#284130]](https://trello.com/c/Sk0nPN3F/4386-from-sl-fdx-003-misleading-fulfillment-address-dropdown-284130)

# FDX-003 — Misleading Fulfillment Address Dropdown: Clearer Warning on Invalid Location Selection

---

> ⚠️ **QA NOTE — Navigation Confirmation Needed**
> The following navigation steps could not be fully confirmed from AI QA evidence or live test runs.
> Please confirm the exact steps before sharing this document:
>
> - [ ] **Where to find**: Confirm the exact trigger point for the fulfillment address / origin location dropdown — specifically whether it appears in the **SideDock** of the Manual Label page, as a standalone modal, or elsewhere in the label generation flow.
> - [ ] **Step 4**: Confirm the exact label of the dropdown or selector that opens the location picker (e.g. "Select Fulfillment Location", "Origin Location", or similar).
> - [ ] **Step 5**: Confirm the exact wording of the updated warning banner as it appears in the live build (the code analysis suggests a message referencing "label will be automatically cancelled" — verify this matches the shipped copy).
>
> Once confirmed, update the Walkthrough section with the actual steps.

---

## Feature Summary

When generating a FedEx shipping label for a multi-location Shopify store, merchants can select which fulfillment location the shipment originates from. Previously, if a merchant selected a location where the ordered products are **not stocked**, a warning banner appeared — but the message was vague. It said products were unavailable at the selected location without explaining the real consequence: **the FedEx label will be automatically cancelled if the merchant proceeds**.

This fix updates the warning banner text to explicitly state that proceeding with an invalid location will cause fulfillment to fail and the label to be auto-cancelled. The merchant remains free to confirm and continue — this is an informational improvement, not a blocking change.

---

## Developed By

Unknown *(see Trello card for assignment)*

## Tested By

**Anuja B**

---

## Toggle / Prerequisites

| Item | Detail |
|---|---|
| Feature toggle | None — no flag required |
| Store type | Multi-location Shopify store (store must have more than one fulfillment location configured in Shopify admin) |
| App version | SL v2.3.120 |
| Single-location stores | Not affected — the warning never fires when only one location exists |

---

## Where to Find This Feature

This warning appears during the **Manual Label Generation** flow, specifically inside the **origin/fulfillment location selector** that is presented when a merchant chooses which location to ship from.

**Path:**

```
Shopify Admin → Orders → [click an order row]
→ More Actions → "Generate Label"
→ Label page opens in the FedEx app (iframe)
→ Origin / fulfillment location selector (dropdown or modal)
→ Select a location where the ordered products are NOT stocked
→ Warning banner appears
```

> ⚠️ See QA NOTE above — confirm the exact UI element name and placement of the location selector before using this path in a live demo.

---

## Step-by-Step Walkthrough (Support / Demo Team)

Use this walkthrough to demonstrate or reproduce the feature. You will need a **multi-location store** with at least one location that does **not** stock the product on the test order.

### Setup
1. Ensure the Shopify store has **two or more fulfillment locations** configured.
2. Ensure the test order contains a product that is stocked at **Location A** but **not** at **Location B**.

### Walkthrough

**Step 1 — Open the order**
In Shopify Admin, go to **Orders** and click the relevant test order row.

**Step 2 — Open the FedEx label page**
Click **More Actions** (top-right of the order page), then click **"Generate Label"**.
The FedEx app label page opens inside the iframe.

**Step 3 — Locate the origin/fulfillment location selector**
> ⚠️ Confirm exact UI element name — see QA NOTE above.

Find the fulfillment location dropdown or selector on the label page.

**Step 4 — Select an invalid location**
From the location selector, choose **Location B** (the location where the product is *not* stocked).

**Step 5 — Observe the warning banner**
A warning banner should appear. Confirm the banner text **explicitly mentions**:
- That products are not available at the selected location, **and**
- That if the merchant proceeds, **the FedEx label will be automatically cancelled**

> ✅ **Expected new text (approximate):** *"Products are not available at the selected location. If you continue, this order will fail fulfillment and the FedEx label will be automatically cancelled."*
> Confirm exact copy matches the shipped build.

**Step 6 — Confirm the flow is not blocked**
The **Confirm** button (or equivalent) should remain **enabled**. The merchant can still choose to proceed — the warning is informational only.

**Step 7 — Verify the happy path (regression check)**
Go back and select **Location A** (the valid location where the product *is* stocked).
Confirm that **no warning banner appears** and the label generation flow proceeds normally.

---

## Expected Behaviour — What Support Should Observe

| Scenario | Expected Result |
|---|---|
| Merchant selects a location where products **are not stocked** | Warning banner appears with updated text that mentions fulfillment failure **and** label auto-cancellation |
| Merchant selects a location where products **are stocked** | No warning banner; flow proceeds normally |
| Merchant sees the warning and clicks Confirm anyway | Flow continues — label generation proceeds; label will be auto-cancelled server-side if fulfillment fails |
| Single-location store | No change; warning never fires |
| International location selected (non-US warehouse) | Same warning logic applies — confirm banner renders correctly for non-US locations |

---

## Business-Safe Explanation

**Why this matters for merchants:**
Before this fix, merchants could accidentally pick the wrong shipping location, see a vague warning, and click through without realising their label would disappear. They would then contact support confused about why a label they generated was cancelled.

**What changed:**
The warning message now clearly tells the merchant: *"your label will be automatically cancelled if you proceed."* Nothing else in the flow changed — the merchant can still confirm and continue if they choose. The goal is simply to make sure they understand the consequence before they click.

**What support should tell a merchant who asks:**
> *"If you select a fulfillment location that doesn't have the product in stock, FedEx can't complete the shipment from that location, so the label is automatically cancelled. The app now shows you a clear warning before you confirm, so you can switch to the correct location first."*

---

## Common Questions & Troubleshooting

**Q: The merchant says they don't see the warning at all.**
- Confirm the store has **more than one fulfillment location** set up in Shopify.
- Confirm the product on the order is genuinely **not stocked** at the selected location in Shopify's inventory settings.
- Confirm the store is on app version **v2.3.120 or later**.
- Single-location stores will never see this warning — this is expected behaviour.

**Q: The merchant sees the old warning text (no mention of label cancellation).**
- The store may be on an older app version. Confirm the installed version is **v2.3.120**.
- If on the correct version, escalate with a screenshot — the i18n key `labels.manualLabels.Banner.Products_are_not` may not have updated correctly.

**Q: The merchant proceeded through the warning and their label was cancelled — what do they do?**
- This is expected behaviour when an invalid location is selected. Ask the merchant to regenerate the label and select the correct fulfillment location (the one where the product is actually stocked).

**Q: The Confirm button is greyed out / disabled after the warning appears.**
- This would be a regression. The Confirm button should remain **enabled** — the warning is not a blocker. Escalate with a screen recording.

**Q: Does this affect international shipments?**
- The same warning logic applies to international locations. If a non-US warehouse is selected and the product is not stocked there, the same updated warning should appear. If it does not, escalate.

---

## Known Limitations & Rollout Notes

| Item | Detail |
|---|---|
| Scope | String/copy change only — no logic, flow, or server-side changes were made |
| Single-location stores | Completely unaffected |
| Auto-label / Bulk label flows | This warning only appears in the **Manual Label Generation** flow where the merchant interacts with the location selector. Auto-generate and bulk flows are not affected |
| Label auto-cancellation behaviour | The server-side auto-cancellation logic (`fulfillmentOrderUpdatingListener`) was **not changed** — only the warning message was updated to reflect what was already happening |
| i18n | The i18n key `labels.manualLabels.Banner.Products_are_not` must be updated alongside the constant — if localised builds are in use, confirm translations are updated |
| Test coverage | No automated spec file exists for `OriginLocationSelector` at time of release — manual QA is the primary verification method |
| Developer | Listed as Unknown on the Trello card — confirm before escalating code questions |

---

## References

| Resource | Link |
|---|---|
| Trello Card (FDX-003) | https://trello.com/c/Sk0nPN3F/4386-from-sl-fdx-003-misleading-fulfillment-address-dropdown-284130 |
| PR (Frontend) | https://bitbucket.org/xadapter-cyd/shopify-fedex-web-client/pull-requests/163 |
| Release | SL v2.3.120 — FedEx App Iteration Backlog |
| Tested By | Anuja B |


---


# From SL: FDX-179 — FedEx REST Dangerous Goods (DG) / Hazmat Integration [#389072]

**Trello:** [From SL: FDX-179 — FedEx REST Dangerous Goods (DG) / Hazmat Integration [#389072]](https://trello.com/c/totZWi5o/4426-from-sl-fdx-179-fedex-rest-dangerous-goods-dg-hazmat-integration-389072)

# FedEx REST Dangerous Goods (DG) / Hazmat Integration — Support & Demo Guide

---

> ⚠️ **QA NOTE — Navigation Confirmation Needed**
> The following navigation steps could not be determined from available sources
> (AI QA evidence, frontend/backend code, AC text).
> Please confirm the exact steps before sharing this document:
>
> - [ ] **Where to find (Products section)**: Exact path and UI element names to reach the Dangerous Goods configuration panel for a product in the FedEx app (e.g., `Products` → specific tab or sub-section name, exact field/dropdown label for DG options).
> - [ ] **Step 4 (Walkthrough)**: Exact label/name of the Dangerous Goods dropdown or field shown in the product mapping screen for a REST account — confirm whether it reads "Dangerous Goods", "Hazmat", or another label.
> - [ ] **Step 6 (Walkthrough)**: Confirm the exact button name used to save DG product settings on the product configuration screen.
> - [ ] **Label Generation — DG routing confirmation**: Confirm whether any visible UI indicator (e.g., a badge, warning, or service note) is shown to the merchant during label generation when a DG shipment is routed to `ship/v1/dghazshipments`.
>
> Once confirmed, update the Walkthrough section with the actual steps.

---

## FedEx REST Dangerous Goods (DG) / Hazmat Integration

**Release:** SL v2.3.120 — FedEx App Iteration Backlog
**Trello Card:** [FDX-179 — FedEx REST DG / Hazmat Integration](https://trello.com/c/totZWi5o/4426-from-sl-fdx-179-fedex-rest-dangerous-goods-dg-hazmat-integration-389072)
**StoryLab Reference:** [https://trello.com/c/BqJlD5I7](https://trello.com/c/BqJlD5I7)
**Ticket:** #389072
**PRs:** [Server PR #828](https://bitbucket.org/xadapter-cyd/shopifyfedexapp/pull-requests/828) | [Client PR #164](https://bitbucket.org/xadapter-cyd/shopify-fedex-web-client/pull-requests/164)
**Developed by:** Unknown
**Tested by:** Anuja B, Keerthanaa Elangovan, Arshiya

---

## Feature Summary

Merchants who ship regulated products — such as lithium batteries, fragrances, cleaning chemicals, e-bike kits, or alcohol — can now generate FedEx-compliant hazmat/Dangerous Goods (DG) labels directly through the Shopify FedEx app, without needing to fall back to FedEx Ship Manager.

Previously, the app had a DG settings UI and a payload builder, but the DG data was never actually sent to FedEx — all DG shipments silently used the standard shipping endpoint. This release fixes that by:

- Attaching the correct `dangerousGoodsDetail` data to the shipment request
- Adding the `DANGEROUS_GOODS` special service type to the payload
- Routing DG shipments to FedEx's dedicated hazmat endpoint (`ship/v1/dghazshipments`) instead of the standard endpoint (`ship/v1/shipments`)

This fix applies to **FedEx REST accounts only**. Legacy SOAP-based accounts are not affected.

---

## Developed By / Tested By

| Role | Name |
|---|---|
| Developed by | Unknown |
| Tested by | Anuja B, Keerthanaa Elangovan, Arshiya |

---

## Feature Toggles & Prerequisites

This feature is **flag-controlled** and will not be active for all stores immediately after deployment. Support must be aware of the toggle state before troubleshooting or demoing.

### Prerequisites

| Requirement | Detail |
|---|---|
| FedEx Account Type | Must be **FedEx REST** (`FEDEX_REST`). DG options are not available for legacy SOAP accounts. |
| Proxy dependency | The `DGHazShipmentProvider` (ship-rate-track proxy PR #2) **must be deployed before** the app server and client PRs. |
| Products configured | At least one Shopify product must have Dangerous Goods settings mapped in the FedEx app's Products section. |

### Server-Side Feature Flags

These flags live in `featuresLoader.js` on the server and are managed by the engineering/ops team.

| Flag | Type | What It Does |
|---|---|---|
| `fedex.rest.dg.enabled.after.store.createdAt.greater.than` | Date gate | Enables DG for **all stores** created after a configured date. This is the global rollout dial. |
| `{shop}.fedex.rest.dg.enabled` | Per-shop opt-in | Enables DG for a **specific shop**, regardless of the date gate. Used for pilot testing. |
| `{shop}.fedex.rest.dg.disabled` | Per-shop kill switch | Forces DG **off** for a specific shop, even if the date gate or opt-in flag is active. Emergency use. |

**How the flags interact (plain English):**
- DG is **on** for a shop if: the shop was created after the date gate threshold, **OR** the per-shop opt-in flag is set.
- DG is **off** for a shop if: the per-shop kill switch is set — this overrides everything else.

### Client-Side Flag

| Condition | Effect |
|---|---|
| Account type = `FEDEX_REST` | The DG options dropdown in the Products section switches to the REST-compatible list, and the DG settings section becomes visible. |

If a merchant's account is not recognised as `FEDEX_REST`, the DG configuration UI will not appear — this is expected behaviour, not a bug.

### Rollout Sequence (for reference)

1. Deploy proxy (`DGHazShipmentProvider`) first
2. Deploy server PR #828 + client PR #164
3. Enable `{shop}.fedex.rest.dg.enabled` for pilot shops to validate
4. Set the date gate for general availability
5. Use `{shop}.fedex.rest.dg.disabled` as an emergency per-shop kill switch if issues arise

---

## Where to Find This Feature in the App

The Dangerous Goods feature spans two areas of the FedEx app:

### 1. Product Configuration (map products as DG)
**Path:** FedEx App (inside Shopify admin) → **Products** (sidebar)

This is where merchants tag their Shopify products as Dangerous Goods and configure the relevant DG details (e.g., hazmat class, packing group, etc.).

> ⚠️ Exact sub-section name and field labels within the Products screen require QA confirmation — see QA NOTE at the top of this document.

### 2. Label Generation (DG label created automatically)
**Path:** Shopify Admin → **Orders** → click an order row → **More Actions** → **Generate Label**

Once a product is correctly configured as DG and the feature flag is active, the DG payload is attached automatically during label generation. No additional steps are required from the merchant at the label generation stage.

---

## Step-by-Step Walkthrough (Support / Demo)

> ⚠️ Steps 3–6 (product DG configuration screen details) require QA confirmation of exact field/button names before this walkthrough is used in a live demo. See QA NOTE at the top.

### Part A — Configure a Product as Dangerous Goods

1. Open the **FedEx app** inside Shopify admin.
2. In the app sidebar, click **Products**.
3. Locate the product you want to configure (e.g., a lithium battery product) and click on it.
4. In the product settings, find the **Dangerous Goods** section. *(Confirm exact section/field label — see QA NOTE)*
   - This section is **only visible if the store's FedEx account type is `FEDEX_REST`**.
   - If the DG section is not visible, the account is either not REST-type or the feature flag is not yet enabled for this shop.
5. Select the appropriate DG option from the dropdown (e.g., hazmat class, regulated material type). *(Confirm exact dropdown label and available options — see QA NOTE)*
6. Save the product settings. *(Confirm exact save button label — see QA NOTE)*

### Part B — Generate a Dangerous Goods Label

1. In Shopify admin, go to **Orders**.
2. Click the order row containing a DG-configured product.
3. Click **More Actions** → **Generate Label**.
4. The app label page opens. In the **left panel**, click **Generate Packages**, then **Get Rates**.
5. Select the desired rate using the radio button.
6. Click **Generate Label**.
7. The app will automatically detect the DG product configuration, attach the hazmat payload, and route the request to FedEx's DG endpoint.
8. On success, you are redirected to the **Order Summary** page where the label is available for printing/downloading.

---

## Expected Behaviour — What Support Should Observe

| Scenario | Expected Result |
|---|---|
| Store is REST account + DG flag enabled + product configured as DG | Label generated via `ship/v1/dghazshipments`; hazmat label produced |
| Store is REST account + DG flag **not** enabled | DG section may be visible in Products, but DG payload will not be attached at label generation |
| Store is **not** a REST account (legacy SOAP) | DG configuration section not visible in Products; no change to label generation behaviour |
| Per-shop kill switch (`{shop}.fedex.rest.dg.disabled`) is active | DG payload not attached even if product is configured; shipment routes to standard endpoint |
| DG product


---


# From SL: FDX-193 — Zendesk Messaging Feature Flag — Switch webWidget to Messenger API

**Trello:** [From SL: FDX-193 — Zendesk Messaging Feature Flag — Switch webWidget to Messenger API](https://trello.com/c/HYXxSa0U/4523-from-sl-fdx-193-zendesk-messaging-feature-flag-switch-webwidget-to-messenger-api)

# Zendesk Messaging API — Feature Flag Switch (webWidget → Messenger)

**Release:** SL v2.3.120 | **Trello:** [FDX-193](https://trello.com/c/HYXxSa0U/4523-from-sl-fdx-193-zendesk-messaging-feature-flag-switch-webwidget-to-messenger-api)

---

> ⚠️ **QA NOTE — Navigation Confirmation Needed**
> The following navigation steps could not be determined from available sources
> (AI QA evidence, frontend/backend code, AC text).
> Please confirm the exact steps before sharing this document:
>
> - [ ] **Where to find**: _Exact location in the app UI where the Zendesk chat widget is visible/accessible for demo purposes (e.g. which page/section surfaces the widget trigger button)_
> - [ ] **Step 3 (Walkthrough — Flag Enabled path)**: _Confirm the exact Zendesk custom field ID for customer email in the FedEx Zendesk account before enabling — AU Post uses `58546981197465` but this has NOT been verified for the FedEx account_
> - [ ] **AC items incomplete**: _Two of five acceptance criteria were not checked off at card close — confirm QA sign-off status for: "Flag disabled: behaviour unchanged" and "Flag enabled: messenger namespace + conversation tag + custom field"_
>
> Once confirmed, update the Walkthrough section with the actual steps.

---

## Feature Summary

The in-app Zendesk support widget previously used the **legacy webWidget (Classic) API**, which Zendesk is deprecating. This change migrates the FedEx app to the **Zendesk Messaging API**, bringing it to parity with the AU Post app (ported in v1.0.34).

When the feature flag is enabled, the widget will:
- Pass the **merchant's shop name** as a conversation tag in Zendesk
- Pass the **customer's email address** via a Zendesk custom field

This gives the support team richer context when a merchant opens a chat — no more manually asking for shop details.

The migration is controlled by a **server-side feature flag** (`zendesk.messaging.enabled`), so it can be enabled globally or per-shop without a code deployment.

---

## Developed By

Unknown *(not recorded on Trello card — confirm with engineering if needed)*

## Tested By

Inderbir Singh

---

## Toggle / Prerequisites

| Item | Detail |
|---|---|
| **Feature flag key** | `zendesk.messaging.enabled` |
| **Config file** | `featureToggles.json` (server root, loaded via `TOGGLES_FILE` environment variable) |
| **Default state** | `false` (disabled — legacy webWidget behaviour preserved) |
| **Flag returned via** | `GET /api/v1/shop/initialData` → `featureFlags.isZendeskMessagingEnabled` |
| **Prerequisite ⚠️** | Zendesk custom field ID for customer email **must be verified** against the FedEx Zendesk account before enabling. AU Post uses field ID `58546981197465` — assumed shared but **not confirmed** for FedEx. |

### Enabling the flag

**Globally (all shops):**
```json
"zendesk.messaging.enabled": true
```

**Per shop (for targeted testing or staged rollout):**
```json
"<shop-domain>.myshopify.com.zendesk.messaging.enabled": true
```

> ℹ️ A server restart or config reload may be required after editing `featureToggles.json`. Confirm the deployment process with the engineering team.

---

## Where to Find This Feature in the App

This feature affects the **Zendesk chat widget** that is available throughout the embedded FedEx app (inside the Shopify admin iframe). The widget is not tied to a specific page — it is a persistent UI element accessible from any section of the app, including:

- **Shipping** (Orders grid)
- **Settings**
- **FAQ**

> ⚠️ The exact widget trigger button location and appearance in the Messaging API mode has not been confirmed via AI QA evidence or frontend code snippets. See QA NOTE at the top of this document.

---

## Step-by-Step Walkthrough (Support / Demo Team)

This feature has **two observable states** depending on the flag value. Use the steps below to verify or demo each.

---

### State A — Flag Disabled (Default / Legacy Behaviour)

> This is the current live state for all merchants until the flag is explicitly enabled.

1. Open any page inside the FedEx app (e.g. **Shipping** tab).
2. Locate the Zendesk chat widget trigger (bottom corner of the app).
3. Click the widget to open it.
4. **Observe:** The widget opens using the legacy **webWidget** interface — standard Zendesk Classic chat experience.
5. No shop name tag or customer email is pre-populated in the Zendesk agent view.

---

### State B — Flag Enabled (Messaging API)

> Only applicable after the flag has been enabled globally or for a specific shop. **Do not enable on production until the Zendesk custom field ID is verified.**

1. Confirm with engineering that `zendesk.messaging.enabled` has been set to `true` in `featureToggles.json` for the target shop or globally.
2. Open the FedEx app for the target shop in Shopify admin.
3. Locate the Zendesk chat widget trigger on any app page.
4. Click the widget to open it.
5. **Observe:** The widget opens using the **Zendesk Messaging** interface (visually may differ from Classic).
6. In the Zendesk agent dashboard, verify:
   - The merchant's **shop name** appears as a **conversation tag**.
   - The merchant's **customer email** is pre-populated via the custom field.

---

## Expected Behaviour — What Support Should Observe

| Scenario | Expected Result |
|---|---|
| Flag is `false` (default) | Widget behaves exactly as before — no change visible to merchant or support agent |
| Flag is `true` | Widget uses Messaging API; agent sees shop name as tag and customer email in custom field |
| Flag toggled mid-session | Behaviour reflects flag state at page load; a full page refresh may be needed |
| Flag enabled but custom field ID is wrong | Email may not populate in Zendesk agent view — no visible error to merchant |
| Any widget action (show/hide, open, close) | Should work correctly in both flag states with no JavaScript errors |

---

## Business-Safe Explanation (For Merchant-Facing Comms)

> *"We've upgraded the in-app chat support widget to use Zendesk's latest Messaging platform. This means when you open a support chat inside the FedEx app, our support team will automatically see your store name and contact details — so you won't need to repeat that information every time. The change is being rolled out gradually and you may not notice any visual difference."*

---

## Common Questions / Troubleshooting

**Q: A merchant says the chat widget isn't opening or looks broken.**
- Check whether the flag was recently enabled for their shop.
- Ask them to do a hard refresh (`Ctrl+Shift+R` / `Cmd+Shift+R`) — the widget namespace is set at page load.
- If the issue persists with the flag enabled, escalate to engineering to check for JavaScript console errors related to `zd()` or `setZendeskNamespace()`.

**Q: The Zendesk agent isn't seeing the shop name or customer email.**
- Confirm the flag is actually enabled for that shop (check `featureToggles.json` or ask engineering to confirm `featureFlags.isZendeskMessagingEnabled` in the `/api/v1/shop/initialData` response).
- Confirm the Zendesk custom field ID is correct for the FedEx Zendesk account. ⚠️ This is an open verification item — see Prerequisites above.

**Q: Can this be enabled for just one shop for testing?**
- Yes. Use the per-shop flag format: `"<shop-domain>.myshopify.com.zendesk.messaging.enabled": true` in `featureToggles.json`.

**Q: Will this affect merchants who don't use the chat widget?**
- No. The change only affects the widget initialisation. Merchants who never open the chat widget will see no difference.

**Q: Is there a way to roll back if something goes wrong?**
- Yes. Set the flag back to `false` in `featureToggles.json` and reload the config. The app will revert to the legacy webWidget behaviour.

---

## Known Limitations / Rollout Notes

| Item | Detail |
|---|---|
| **Flag default is OFF** | No merchants are affected until the flag is explicitly enabled |
| **Custom field ID unverified** | Zendesk custom field `58546981197465` is taken from the AU Post app — must be confirmed against the FedEx Zendesk account before production enablement |
| **Two AC items open at card close** | "Flag disabled: behaviour unchanged" and "Flag enabled: full messenger behaviour" were not checked off — confirm QA completion with Inderbir Singh before enabling on production |
| **Developer not recorded** | Engineering contact for this change is unknown — confirm via PR history (Server PR #838, Client PR #170) |
| **No UI toggle** | This is a server-side config change only — there is no toggle visible in the app's Settings UI |
| **Session behaviour** | Flag state is read at page load via `initialData`; changes to the flag require a page refresh to take effect for active sessions |
| **Parity reference** | AU Post app implemented the same change in v1.0.34 (C-18) — that implementation can be used as a reference for expected Zendesk agent-side behaviour |

---

## References

| Resource | Link |
|---|---|
| Trello Card (FDX-193) |


---
