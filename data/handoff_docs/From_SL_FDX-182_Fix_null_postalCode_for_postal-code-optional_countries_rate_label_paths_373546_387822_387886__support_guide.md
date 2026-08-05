---

> ⚠️ **QA NOTE — Navigation Confirmation Needed**
> The following navigation steps could not be determined from available sources
> (AI QA evidence, frontend/backend code, AC text). This is a backend bug fix with
> no new UI — navigation steps below are inferred from the known app flow.
> Please confirm before sharing this document:
>
> - [ ] **Where to find**: No new UI element was added. Confirm that the fix is entirely transparent to the user (no toggle, no new button, no settings change required).
> - [ ] **Broker/invoice address path (CONFLICT 1)**: The `extractAddressDetails()` fix at line 570 (broker/invoice addresses) is described in the card but **not confirmed as fixed or QA-tested**. Confirm whether this path was included in the committed fix before telling customers the issue is fully resolved.
> - [ ] **Feature flag (CONFLICT 2)**: Card states the `fedex.empty.postalcode.enabled` flag gate was "removed." Confirm this is live in production and no flag needs to be enabled on merchant accounts.
> - [ ] **Australia (CONFLICT 5)**: AU appears in the QA pass list but is not listed in the card's fix scope. Confirm whether AU was intentionally included in the expanded country list or was a pre-existing working country tested for regression only.
> - [ ] **Untested countries**: 40+ countries in the expanded list (YE, SY, sub-Saharan Africa, etc.) have no QA test evidence. Confirm whether these are considered supported or are included speculatively.
>
> Once confirmed, update the Known Limitations section accordingly.

---

# FDX-182 — Fix: Null Postal Code for Postal-Code-Optional Countries (Rate + Label Paths)

**Trello:** [https://trello.com/c/c7uHEny2](https://trello.com/c/c7uHEny2)
**Tickets:** #373546, #387822, #387886
**Branch:** `bug/fdx-182-fix-null-postal-code-amea`
**Commit:** `8d708d0e12a595e9b5f4ebc4aa9bca1fb9719c26`
**Implemented:** 2026-05-26
**Release:** TBC

---

## Feature Summary

This is a **bug fix**, not a new feature. Merchants shipping to countries where postal codes are not required (e.g., Qatar, Kuwait, UAE, Hong Kong, Bahrain, Oman, Saudi Arabia, Jordan, Iraq, and ~40 additional AMEA/GCC/sub-Saharan African countries) were receiving FedEx API errors because the app was sending `postalCode: null` in both rate requests and label requests. FedEx rejects `null` postal codes even for countries where a postal code is not meaningful.

The fix ensures the app always sends a valid non-null placeholder value (`--`) for these countries instead of `null`. Hong Kong is a special case — the app sends `000000` for HK because Shopify does not display a postal code field for Hong Kong addresses at all, making it impossible for merchants to enter any value manually.

This fix applies to **both** the checkout rates path and the label generation path (manual, auto, and bulk).

---

## Developed By

Unknown *(not recorded on Trello card)*

---

## Tested By

QA Team — fedexapp-rest-basavaraj.myshopify.com

---

## Toggle / Prerequisites

| Item | Detail |
|---|---|
| Feature flag | The `fedex.empty.postalcode.enabled` flag gate has been **removed** per the committed implementation. No flag needs to be enabled. ⚠️ *Confirm this is live in production before advising merchants.* |
| Merchant configuration | No settings changes required by the merchant. The fix is automatic and transparent. |
| Shopify location address | The merchant's Shopify store location and ship-from address must be correctly configured. This fix only addresses the destination postal code — it does not fix incorrectly configured origin addresses. |
| App version | Fix is in the release containing commit `8d708d0e`. Confirm the deployed version with the engineering team before troubleshooting. |

---

## Where to Find This Feature in the App

There is **no new UI element** for this fix. It is a silent backend correction. The change is observable only through:

- Checkout rates loading successfully for affected countries (previously returned a FedEx error)
- Labels generating successfully for affected countries (previously failed with a postal code error)
- The **Rates Log** (App sidebar → **Rates Log**) — outbound API payloads will now show `"postalCode": "--"` (or `"000000"` for HK) instead of `null`

---

## Step-by-Step Walkthrough (Support / Demo)

Use these steps to verify the fix is working for a merchant reporting the issue, or to demonstrate correct behaviour.

### A — Verify Checkout Rates Are Returning for an Affected Country

1. Open the merchant's Shopify storefront.
2. Add any product to the cart and proceed to checkout.
3. Enter a shipping address for an affected country (e.g., Qatar, Kuwait, UAE, Hong Kong — see full list below).
4. **Expected:** FedEx shipping rates appear in the checkout rate list without error.
5. **Previously:** Checkout showed no FedEx rates, or an error was returned from FedEx.

### B — Verify Manual Label Generation for an Affected Country

1. In **Shopify admin**, go to **Orders**.
2. Click the relevant order (destination must be an affected country).
3. Click **More Actions** → **Generate Label**.
4. In the app label page, on the **left panel**, click **Get Rates**.
5. **Expected:** Rates are returned. Select a rate radio button.
6. Click **Generate Label**.
7. **Expected:** Label is generated successfully. You are redirected to the Order Summary page.
8. **Previously:** Step 4 or step 6 would fail with a FedEx error referencing postal code.

### C — Verify Auto Label Generation for an Affected Country

1. In **Shopify admin**, go to **Orders**.
2. Click the relevant order.
3. Click **More Actions** → **Auto-Generate Label**.
4. **Expected:** Label is generated automatically and you are taken to the Order Summary page.

### D — Verify via Rates Log

1. In the **FedEx app sidebar**, click **Rates Log**.
2. Find the rate request for the affected order/country.
3. Expand the request payload.
4. **Expected:** `postalCode` field shows `"--"` for most postal-code-optional countries, or `"000000"` specifically for Hong Kong (HK).
5. **Previously:** `postalCode` field showed `null`.

---

## Expected Behaviour — What Support Should Observe

| Scenario | Before Fix | After Fix |
|---|---|---|
| Checkout rates for QA, KW, UAE, OM, BH, SA, JO, IQ, HK | FedEx error — no rates returned | Rates returned successfully |
| Manual label generation for affected countries | Label request fails — FedEx rejects null postal code | Label generates successfully |
| Auto / bulk label generation for affected countries | Label fails silently or with error | Label generates successfully |
| Rates Log payload — postal code field | `"postalCode": null` | `"postalCode": "--"` (or `"000000"` for HK) |
| Hong Kong specifically | Shopify hides postal code field; app sent null; FedEx rejected | App sends `"000000"` — FedEx accepts |
| Countries with a real postal code entered | Postal code passed through as entered | Unchanged — real postal codes are not affected |

---

## Business-Safe Explanation (For Merchant Communication)

> "Some countries — such as Qatar, Kuwait, UAE, Hong Kong, and others in the Middle East and Asia-Pacific region — do not use postal codes. When your customer enters a shipping address for one of these countries, there is no postal code to provide. Previously, our app was sending a blank/empty postal code to FedEx, which FedEx does not accept — causing rates to fail at checkout and labels to fail during fulfilment.
>
> We have updated the app so that for these countries, we automatically send a recognised placeholder value that FedEx accepts. You do not need to change any settings. Rates and labels for these destinations should now work correctly."

---

## Countries Covered by This Fix

The app's internal list was expanded from 3 countries to approximately 50. The following were **QA-verified** end-to-end:

| Country Code | Country | QA Verified |
|---|---|---|
| QA | Qatar | ✅ |
| KW | Kuwait | ✅ |
| UAE / AE | United Arab Emirates | ✅ |
| OM | Oman | ✅ |
| BH | Bahrain | ✅ |
| SA | Saudi Arabia | ✅ |
| HK | Hong Kong | ✅ |
| JO | Jordan | ✅ |
| IQ | Iraq | ✅ |
| AU | Australia | ✅ *(see Known Limitations — scope unclear)* |

**Additionally included in the expanded configuration list (not individually QA-tested):**
YE (Yemen), SY (Syria), and approximately 40 additional GCC, AMEA, and sub-Saharan African countries added via the `fdx-178-amea-null-postal-code` branch country list.

---

## Common Questions & Troubleshooting

**Q: A merchant in Qatar/Kuwait/UAE is still getting a "postalCode cannot be null" error after this fix. What should I check?**

- Confirm the merchant is on the app version that includes this fix (commit `8d708d0e` / release TBC). Ask engineering to confirm the deployed version.
- Check the **Rates Log** for the failing request. If `postalCode: null` still appears in the payload