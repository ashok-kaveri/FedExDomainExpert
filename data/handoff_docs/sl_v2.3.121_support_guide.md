# Release Support Guide — SL v2.3.121 FedexApp: Iteration Backlog

*Generated on: 2026-06-26*



# FDX-196 — Freight Rate Call Fires for Sub-150lb Shipments Causing Backup Rates

**Trello:** [FDX-196 — Freight Rate Call Fires for Sub-150lb Shipments Causing Backup Rates #395653](https://trello.com/c/cgRCDsuq/4654-fdx-196-freight-rate-call-fires-for-sub-150lb-shipments-causing-backup-rates-395653)

---

## Feature Summary

Merchants with FedEx Freight enabled were sometimes seeing backup (fallback) shipping rates at Shopify checkout instead of live FedEx rates.

The cause was a retry behaviour issue: when a FedEx rate request failed, the app retried it several times. Each retry consumed part of Shopify's limited checkout rate-fetch window, so the valid parcel rates that had already been returned were discarded before they could be shown — and Shopify fell back to backup rates.

**Fix applied (SL v2.3.121):** Failed rate requests that return an HTTP 400 (a permanent "bad request" error that will never succeed on retry) are no longer retried. Only genuinely retryable conditions — network errors, server (5xx) errors, and rate-limit (429) responses — continue to be retried. This keeps the checkout rate window free so the valid FedEx rates are returned and displayed.

---

## Toggles / Prerequisites

| Item | Detail |
|---|---|
| Feature toggle | None — fix is applied globally for all stores |
| FedEx Freight enabled | Merchant must have FedEx Freight configured in their account for this scenario to be relevant |
| Carrier Calculated Shipping (CCS) | Must be active on the Shopify store for real-time rates to appear at checkout |

---

## Where to Find This in the App

This is a backend fix with no UI element. The improved behaviour is observable in two places:

**1. Checkout (end-to-end validation)**
> Shopify storefront checkout — observe which shipping rates are presented to the customer.

**2. Rates Log (to inspect retry behaviour)**
> App sidebar → **Rates Log**

This section shows historical rate request/response JSON. After the fix, failed requests that return an HTTP 400 should no longer show repeated retry attempts.

---

## Step-by-Step Walkthrough (Support / Demo)

### Scenario A — Freight-enabled store previously seeing backup rates

1. Open the merchant's store in Shopify admin and confirm FedEx Freight is enabled in **Settings → Carrier Services**.

2. Proceed through Shopify checkout (or simulate a rate request) for a test order.

3. Observe the shipping rates presented at checkout — **live FedEx rates should appear** within the Shopify checkout rate window, rather than backup/fallback rates.

---

### Scenario B — Retry behaviour (regression check)

1. This is a background behaviour check — no merchant-facing UI steps required.
2. Confirm via log review that HTTP 400 responses are **not** retried, while network errors, 5xx errors, and 429 (rate-limit) responses are **still** retried as expected.

---

## Expected Behaviour / What Support Should Observe

| Scenario | Expected Outcome |
|---|---|
| Freight-enabled store at checkout | Live FedEx rates appear at checkout instead of backup/fallback rates |
| HTTP 400 from FedEx | **Not retried** — request fails immediately, no repeated retry delay |
| Network / 5xx / HTTP 429 errors | **Still retried** — existing behaviour preserved |
| Checkout rate response time | Valid rates returned well within the checkout rate window |

> **Support note:** If a merchant on a Freight-enabled store is still seeing backup rates at checkout after this release, ask them to share the relevant **Rates Log** entry (request/response JSON) for investigation. A high fallback rate value in their Shopify shipping settings (e.g. $400) can help distinguish fallback from live carrier rates while investigating.



---



# FDX-182b — Broker Invoice Empty PostalCode Fix (FDX-182 Follow-up)

**Trello:** [From SL: FDX-182b — Broker Invoice Empty PostalCode Fix (FDX-182 follow-up) [#373546, #387822]](https://trello.com/c/mINR0zjC/4528-from-sl-fdx-182b-broker-invoice-empty-postalcode-fix-fdx-182-follow-up-373546-387822)

---

## Feature Summary

This is a follow-up to FDX-182 (PR #835), which fixed postal code handling for postal-code-optional countries (Hong Kong, UAE, Qatar, Kuwait, and other AMEA/GCC regions) across the main shipper and recipient address builders.

FDX-182b closes a gap that was missed in that fix: the `extractAddressDetails()` function — used specifically for the **delivery invoice / importer-of-record address path** on international shipments — was still setting `postalCode` using an inline `|| ''` fallback. FedEx REST rejects an empty string `""` the same way it rejects `null`, causing international label generation to fail for merchants shipping to postal-code-optional countries when an importer-of-record address is present.

The fix routes `extractAddressDetails()` through the same `getPostalCodeFrom()` logic already used by all other address builders, ensuring the correct placeholder value (`'000000'` for HK, `'--'` for other AMEA/GCC countries) is returned instead of an empty string.

**Release:** SL v2.3.121
**Approved:** 2026-06-26

---

## Toggles / Prerequisites

| Item | Detail |
|---|---|
| Feature toggle | None — fix is applied automatically on upgrade to v2.3.121 |
| Affected shipment type | International labels only |
| Required configuration | An **importer-of-record** address must be set on the shipment; destination must be a postal-code-optional country (Hong Kong, UAE, Qatar, Kuwait, or similar AMEA/GCC region) |
| Unaffected flows | Domestic label generation; standard shipper/recipient address paths |

---

## Where to Find This Feature in the App

This fix operates at the backend label-generation layer and does not surface as a visible UI element. The relevant user-facing flow is **international label generation** with an importer-of-record address configured under **Duties & Taxes** settings in the label generation panel.

**Path to trigger the affected flow:**

> **Shopify Admin → Orders** → click an international order row → **More Actions** → **Generate Label**

Inside the app label page:

- **Right panel (SideDock):** Duties & Taxes section — confirm **Duties Payment Type** and importer-of-record details are configured for the shipment
- **Left panel:** Generate Packages → **Get Rates** → select a rate → **Generate Label**

---

## Step-by-Step Walkthrough

Use an international test order destined for a postal-code-optional country (Hong Kong, UAE, Qatar, or Kuwait) with an importer-of-record address configured.

**1. Open the order in Shopify Admin**
- Navigate to **Shopify Admin → Orders**
- Click the target international order row

**2. Open the label generation page**
- Click **More Actions** (top-right of the order detail page)
- Click **Generate Label**
- The FedEx app label page opens in the iframe

**3. Configure Duties & Taxes in the SideDock (right panel)**
- Locate the **Duties & Taxes** section in the SideDock
- Set **Purpose**, **Terms of Sale**, and **Duties Payment Type** as appropriate for the shipment
- Ensure the importer-of-record address is populated — this is the address path that was affected by the bug

**4. Generate the label**
- In the left panel, click **Get Rates**
- Select a rate using the radio button
- Click **Generate Label**

**5. Confirm success**
- The app redirects to the **Order Summary** page
- The label is generated without a FedEx REST API rejection error
- On the Order Summary page, use **Print Documents** or **Download Documents** to retrieve the label

**6. Verify the fix for postal-code-optional countries**
- Repeat steps 1–5 for each of the following destination countries: **Hong Kong, UAE, Qatar, Kuwait**
- Label generation should succeed in all cases — no empty `postalCode` rejection from FedEx

---

## Expected Behaviour / What Support Should Observe

| Scenario | Expected Result |
|---|---|
| International label to **Hong Kong** with importer-of-record address, no postal code | Label generates successfully; `postalCode` sent to FedEx as `'000000'` (not `""`) |
| International label to **UAE / Qatar / Kuwait** with importer-of-record address, no postal code | Label generates successfully; `postalCode` sent to FedEx as `'--'` (not `""`) |
| International label to a country **with** a postal code | Label generates successfully; actual postal code is used — no change in behaviour |
| **Domestic** label generation (any country) | Unaffected — behaviour identical to pre-fix |
| Main shipper / recipient address paths (from FDX-182 / PR #835) | Unaffected — no regression expected |

**What a successful demo looks like:**
The merchant completes the Generate Label flow for an international order to a postal-code-optional country and lands on the Order Summary page with a valid label available for download. Prior to this fix, the same flow would have returned a FedEx API error due to the empty `postalCode` field in the delivery invoice / importer-of-record address block.



---



# Preserve Account Settings Through SOAP to REST Migration

**Trello:** [From SL: FDX-194 — Preserve Account Settings Through SOAP to REST Migration](https://trello.com/c/wfDm8wwZ/4533-from-sl-fdx-194-preserve-account-settings-through-soap-to-rest-migration)

---

## Feature Summary

When FedEx migrates a merchant's account from the legacy SOAP API to the modern REST API, this feature ensures that all previously configured account settings are automatically preserved through the transition. Merchants do not need to manually re-enter or reconfigure their account details after the migration completes. A migration summary screen is presented to confirm the outcome of the migration for each account.

---

## Toggles / Prerequisites

| Item | Detail |
|---|---|
| Feature Toggle | None — available to all merchants on SL v2.3.121+ |
| FedEx Account | Merchant must have at least one FedEx account connected to the app |
| App Version | SL v2.3.121 or later |

---

## Where to Find This Feature

**Path:** App Sidebar → **Settings** → **Accounts**

The migration summary and preserved account details are surfaced within the Accounts section of Settings. After a SOAP-to-REST migration event occurs for a connected FedEx account, the app displays a **Migration Summary** screen at this location, and the existing account details remain intact and visible in the **Account Details** view.

---

## Step-by-Step Walkthrough

Use the following steps to demonstrate or verify this feature during a support session or demo.

### 1. Navigate to Account Settings

1. Open the FedEx app inside Shopify Admin (embedded iframe).
2. In the app sidebar, click **Settings**.
3. Under Settings, select **Accounts**.

### 2. Review Account Details

1. On the Accounts page, confirm that the merchant's FedEx account(s) are listed with their existing configuration intact — account number, credentials, and associated settings should all be present.
2. Verify that no settings have been lost or reset as a result of the SOAP-to-REST migration.

### 3. Review the Migration Summary

1. If a migration has been triggered for the account, the app will display a **Migration Summary** screen.
2. The Migration Summary presents a per-item status for each setting that was carried through the migration. Each item is shown with one of the following status indicators:
   - ✅ **Success** — setting was preserved successfully
   - ❌ **Failed** — setting could not be migrated
   - ⚠️ **Warning** — setting was migrated with a caveat
   - 🕐 **Pending** — migration for this setting is still in progress
3. A **Banner** at the top of the summary provides an overall migration status message.
4. While results are loading, a **Spinner** is displayed — this is expected behaviour.

### 4. Confirm No Reconfiguration Is Required

1. Navigate back to **Settings → Accounts**.
2. Open the **Account Details** view for the migrated account.
3. Confirm all previously saved account settings are present and correct — no manual re-entry should be needed.

---

## Expected Behaviour / What Support Should Observe

| Scenario | Expected Result |
|---|---|
| Merchant's account undergoes SOAP-to-REST migration | All account settings are automatically preserved; no data loss |
| Support opens Settings → Accounts post-migration | Account details are fully populated with pre-migration configuration |
| Migration Summary screen loads | A spinner appears briefly, then per-item status icons (tick, cancel, risk, clock) are shown alongside each migrated setting |
| All items migrate successfully | Banner and item list show success indicators; no manual action required from the merchant |
| One or more items fail or warn | Relevant items display failure (❌) or warning (⚠️) icons; the banner reflects the overall outcome |
| Merchant navigates away and returns to Accounts | Settings remain intact; Migration Summary is accessible for review |



---



# FedEx One Rate with Ground

**Trello:** [FedEx One Rate with Ground](https://trello.com/c/IYRpT76g/4612-fedex-one-rate-with-ground)

---

## Feature Summary

FedEx One Rate is a flat-rate domestic US shipping option that requires a FedEx-branded box. Previously, when One Rate was enabled in the app, ground service rates were not fetched — because ground services are incompatible with FedEx box packaging.

With this update, the app now makes a **secondary API call** using `YOUR_PACKAGING` as the packaging type when One Rate is active. This fetches ground rates alongside One Rate options. The **cheapest available rate** is surfaced at Shopify checkout. The packaging algorithm and box selection logic are otherwise unchanged.

---

## Toggles / Prerequisites

| Item | Detail |
|---|---|
| Feature toggle | **Yes — gated behind a per-store feature flag:** `<store>.myshopify.com.fedex.rest.ground.with.one.rate.enabled`. **Released with the toggle OFF** in SL v2.3.121 — must be explicitly enabled per store to activate the behaviour. |
| FedEx account requirement | Must have a valid FedEx account connected in the app |
| One Rate must be configured | One Rate services must already be enabled in the app's rate settings |
| Shopify Carrier Calculated Shipping | Must be enabled on the merchant's Shopify plan for rates to display at checkout |
| Shipping region | US domestic shipments only |

---

## Where to Find the Feature

This feature operates at the **rate-fetching layer** — there is no new UI toggle or dedicated screen. The behaviour is observed through the rates displayed at **Shopify checkout** and in the **Rates Log**.

**Relevant app locations:**

- **Settings → Carrier Services** — where One Rate services are enabled/configured
- **Rates Log** — to inspect the rate request/response and confirm ground rates are being returned alongside One Rate options

---

## Step-by-Step Walkthrough

### 1. Confirm One Rate Is Configured

1. Open the FedEx app inside Shopify admin (via the embedded app iframe).
2. In the app sidebar, navigate to **Settings**.
3. Go to **Carrier Services**.
4. Confirm that FedEx One Rate services are enabled for the merchant's account.

---

### 2. Verify Ground Rates Appear at Checkout

1. From the Shopify storefront (or a test order), proceed to checkout with a **US domestic shipping address**.
2. At the shipping rate selection step, observe the rates displayed.
3. **Expected:** Ground service rates now appear alongside One Rate options. The cheapest available rate is listed.

---

### 3. Inspect the Rate Request/Response via Rates Log

1. In the app sidebar, navigate to **Rates Log**.
2. Locate the most recent rate request for the order under test.
3. Open the request JSON and confirm the packaging type includes `YOUR_PACKAGING` (used to fetch ground rates).
4. Open the response JSON and confirm ground service rates are present in the returned options.

---

### 4. Manual Label Generation (Spot-Check)

1. In Shopify admin, go to **Orders** and click the relevant order row.
2. Click **More Actions → Generate Label**.
3. In the app label page, click **Get Rates** in the left panel.
4. Confirm that ground rate options are listed alongside One Rate options in the rate selection list.
5. Select a rate and proceed to **Generate Label** as normal.

---

## Expected Behaviour — What Support Should Observe

| Scenario | Expected Result |
|---|---|
| One Rate is enabled; merchant checks out with a US domestic address | Ground rates appear at checkout alongside One Rate options |
| Cheapest rate display | The lowest-priced rate (whether ground or One Rate) is surfaced at checkout |
| Packaging logic | No change to box selection or packaging algorithm — only the API request packaging type changes to `YOUR_PACKAGING` for the ground rate fetch |
| Rates Log inspection | Request JSON shows `YOUR_PACKAGING` packaging type; response JSON includes ground service rates |
| Manual label generation | Ground rates visible in the Get Rates panel alongside One Rate options |
| Non-US or international orders | No change in behaviour — this feature applies to US domestic shipments only |
| One Rate not configured | No change in behaviour — ground rates continue to fetch as before |



---



# Country-wise HS Code by Destination

**Trello:** [From SL: FDX-191 — Country-wise HS Code by Destination #368005](https://trello.com/c/wVnHN24M/4529-from-sl-fdx-191-country-wise-hs-code-by-destination-368005)

---

## Feature Summary

This feature extends the FedEx app's product customs configuration to support **per-destination HS (Harmonized System) codes**. Previously, each product held a single global HS code that was sent to FedEx for all international shipments regardless of destination country. With this change, merchants can define country-specific HS codes per product. When a label is generated, the app resolves the correct HS code by matching the shipment's destination country — falling back to the global HS code if no country-specific override exists. Resolution happens server-side; no change is required to the label generation workflow itself.

---

## Toggles / Prerequisites

| Item | Detail |
|------|--------|
| Feature toggle | **Yes — gated behind a per-store feature flag (released with the toggle OFF).** Must be explicitly enabled per store to activate country-wise HS code resolution. |
| Applicable shipment type | International shipments only (destination country must differ from ship-from country) |
| Existing global HS code | Unaffected — continues to function as the fallback when no country-specific code matches |
| Inventory webhook behaviour | Shopify inventory webhooks sync only the global `HSCode` field; `countryWiseHSCodes` is never overwritten by webhook events |

---

## Where to Find the Feature

The per-country HS code configuration lives inside the **Products** section of the FedEx app, within each product's customs details.

**Path:**
> FedEx App sidebar → **Products** → select a product → **Custom Details** section

The existing single **HS Code** field remains in place. Beneath it, a new **Country-specific HS Codes** section allows merchants to add one or more country-code / HS-code pairs.

---

## Step-by-Step Walkthrough

### Configuring Country-specific HS Codes on a Product

1. Open the FedEx app inside Shopify admin and click **Products** in the app sidebar.
2. Locate and click the product you want to configure.
3. Scroll to the **Custom Details** section of the product settings page.
4. Confirm the existing global **HS Code** field is populated (this acts as the fallback for any destination not explicitly listed).
5. Below the global HS Code field, locate the **Country-specific HS Codes** section.
6. Click the **Add** button (or equivalent row-add control) to insert a new row.
7. In the new row:
   - Select the **destination country** from the country dropdown.
   - Enter the **HS code** applicable for that destination in the HS code input field.
8. Repeat steps 6–7 for each additional destination country that requires a different HS code.
9. To remove a country-specific entry, click the **remove** control (delete/trash icon) on the corresponding row.
10. Click **Save** to persist the configuration. All country-specific entries and the global HS code are saved together.

---

### Verifying HS Code Resolution at Label Generation

1. Navigate to **Shopify admin → Orders** and open an international order whose destination country has a configured country-specific HS code.
2. Click **More Actions → Generate Label**.
3. In the label page, proceed through the **Generate Packages → Get Rates** flow, select a rate, and click **Generate Label**.
4. Observe the generated label and the FedEx API commodity payload — the HS code sent to FedEx should match the country-specific code configured for the destination country.
5. Repeat with an international order shipping to a country that does **not** have a country-specific override — the global HS code should be used in the commodity payload.

---

## Expected Behaviour / What Support Should Observe

| Scenario | Expected Result |
|----------|----------------|
| Destination country matches a configured country-specific HS code | That country-specific HS code is sent as `harmonizedCode` in the FedEx commodity payload |
| Destination country has no country-specific override | The product's global HS code is sent as `harmonizedCode` (unchanged fallback behaviour) |
| Merchant saves product settings | All country-specific HS code rows are preserved after save — none are silently dropped |
| Shopify inventory webhook fires for the product | Global `HSCode` may be updated by Shopify sync; `countryWiseHSCodes` entries are **not** affected or overwritten |
| Merchant has no country-specific codes configured | Behaviour is identical to pre-feature — global HS code used for all destinations |
| Product has country-specific codes; return label generated | Same destination-country resolution logic applies; the correct HS code is used in the return label commodity |
| Merchants on prior versions / no country-specific codes set | No change in behaviour; feature is purely additive |

> **Support note:** HS code resolution is handled entirely server-side at label generation time. Merchants do not need to change their label generation workflow. If a merchant reports an unexpected HS code on a label, verify the country-specific entries saved on the product and confirm the destination country of the order matches the configured country code exactly.



---



# FedEx App – Ground Close Manifest

**Trello:** [FedEx app - Ground close manifest](https://trello.com/c/Plvl70tL/4595-fedex-app-ground-close-manifest)

---

## Feature Summary

This feature introduces **Ground Close Manifest** support for the FedEx app via the FedEx REST API. It allows merchants to generate an end-of-day close manifest, ensuring the eligible ground packages shipped that day are formally closed out with FedEx. The implementation includes a manifest database collection with indexing and a new admin menu option for triggering manifest generation.

> **Important scope:** Ground Close Manifest is **only available for Dangerous Goods (DG) — Ground shipments**. It does not apply to standard (non-DG) ground shipments.

---

## Toggles / Prerequisites

| Item | Detail |
|---|---|
| Feature Toggle | **Yes — gated behind a per-store feature flag (released with the toggle OFF).** Must be explicitly enabled per store. |
| FedEx Account | Must be connected and active within the app |
| Shipment Type | **Dangerous Goods (DG) — Ground shipments only.** Not available for standard non-DG ground shipments. |
| App Version | SL v2.3.121 / FedEx App Iteration Backlog (approved 2026-06-26) |

---

## Where to Find the Feature

The Ground Close Manifest option is accessible from within the FedEx app (embedded Shopify admin iframe) via the **admin menu**. Based on the card description, a new menu option for generating manifests has been added to the app's admin navigation.

**Path:**
> Shopify Admin → Apps → PH Ship Rate and Track for FedEx → *(Admin menu — manifest option)*

The manifest option surfaces as a dedicated menu entry within the app's admin-level navigation, separate from the standard merchant-facing sidebar sections (Shipping, Settings, Products, PickUp, Rates Log, FAQ).

---

## Step-by-Step Walkthrough

Use the following steps when demonstrating or supporting this feature:

1. **Open the FedEx app** from Shopify Admin → Apps → *PH Ship Rate and Track for FedEx*. The app loads inside the Shopify admin iframe.

2. **Navigate to the admin menu** within the app. Locate the new **manifest / Ground Close Manifest** menu option that has been added as part of this release.

3. **Select the Ground Close Manifest option.** This opens the manifest generation interface.

4. **Initiate manifest generation** by clicking the relevant generate/submit button within the manifest screen. The app will call the FedEx REST API to close out eligible Ground shipments for the day.

5. **Confirm the manifest is generated.** The app records the manifest result in the manifest database collection. Observe a success confirmation or manifest reference on screen.

6. **Scope reminder** — the close manifest applies to **Dangerous Goods (DG) Ground shipments only**. Standard non-DG ground shipments are not included in this flow.

---

## Expected Behaviour / What Support Should Observe

- A **Ground Close Manifest menu option** is visible in the app's admin navigation after the release is deployed.
- Clicking the option and triggering generation results in a **successful manifest submission** to FedEx via the REST API.
- The manifest transaction is **persisted to the manifest database collection** (with index), meaning repeated or historical manifest requests can be tracked server-side.
- The close manifest scope is limited to **Dangerous Goods (DG) Ground shipments only** — standard non-DG ground shipments are not part of this flow.
- If no eligible DG Ground shipments exist for the day, the app should respond accordingly (no manifest generated / empty result) without throwing an unhandled error.
- The feature does **not** affect rate calculation, label generation, or any other existing app workflows.



---



# FedEx DG Shipment Bug Fixes

**Trello:** [FedEx Dg Shipment bug fixes](https://trello.com/c/qEflxYBG/4598-fedex-dg-shipment-bug-fixes)

---

## Feature Summary

This release delivers targeted bug fixes to the FedEx Dangerous Goods (DG) shipment workflow within the FedEx Shopify app. The following issues have been resolved:

1. **OP900 label** — Corrected issues affecting OP900 label generation for dangerous goods shipments. The OP900 label is produced **only for hazardous (dangerous goods) products** — it is not generated for non-hazardous shipments.
2. **Standalone battery (ORMD)** — Resolved incorrect or missing data being passed for standalone battery items classified as Other Regulated Materials – Domestic (ORMD).

These are back-end and form-handling corrections to existing DG shipment functionality.

---

## Toggles / Prerequisites

| Item | Detail |
|---|---|
| Feature toggle | **Yes — gated behind the per-store Dangerous Goods feature flag:** `<store>.myshopify.com.fedex.rest.dg.enabled`. DG functionality (and these fixes) only apply when this flag is enabled for the store. |
| FedEx account | Must have a valid FedEx account connected in **Settings → Account** |
| Dangerous Goods enabled | Products must be mapped to Dangerous Goods / ORMD services via **Products** in the app sidebar |
| Hazardous products only | The OP900 label is generated **only for hazardous (dangerous goods) products** |

---

## Where to Find the Feature

These fixes apply within the **Manual Label Generation** flow for orders containing Dangerous Goods or ORMD-classified products.

**Path:**
```
Shopify Admin → Orders → [select order] → More Actions → Generate Label
```

Once the label page opens inside the app iframe:

- **DG / ORMD package settings** are configured in the **LEFT panel** under **Generate Packages**
- **OP900 label output** is produced after clicking **Generate Label** (for hazardous/DG products only) and is available on the **Order Summary** page via **Print Documents** / **Download Documents**

---

## Step-by-Step Walkthrough

### Scenario A — OP900 Label (Dangerous Goods)

1. From **Shopify Admin**, navigate to **Orders** and open an order containing a DG-mapped product.
2. Click **More Actions** → **Generate Label**.
3. In the app iframe **LEFT panel**, configure the package details. Ensure the item is recognised as a Dangerous Goods product (mapped via **Products** in the app sidebar).
4. Click **Get Rates** and select the appropriate rate using the radio button.
5. Click **Generate Label**.
6. On the **Order Summary** page, click **Print Documents** or **Download Documents**.
7. **Observe:** The OP900 label is generated and available for download without errors.

---

### Scenario B — Standalone Battery / ORMD

1. Open an order containing a product mapped to **Standalone Battery** or **ORMD** under **Products** in the app sidebar.
2. Click **More Actions** → **Generate Label**.
3. In the **LEFT panel**, confirm the package reflects the ORMD/standalone battery classification.
4. Click **Get Rates** → select a rate → click **Generate Label**.
5. **Observe:** The standalone battery / ORMD designation is correctly passed in the shipment request and the label generates successfully without classification errors.

---

## Expected Behaviour — What Support Should Observe

| Scenario | Expected Result |
|---|---|
| OP900 label generation | For hazardous (DG) products only: label generates without API errors; OP900 document is available under **Print Documents** / **Download Documents** on the Order Summary page |
| Standalone battery / ORMD | ORMD/standalone battery data is correctly included in the FedEx API request; label generates successfully with the correct commodity classification |
| No regression on standard DG shipments | Non-ORMD dangerous goods labels continue to generate as expected |
| No new UI changes | The label generation interface appears identical to pre-fix behaviour; no new fields, toggles, or screens are introduced |


---



# Fetch Product Dimensions from Shopify Metafields

**Trello:** [From SL: FDX-192 — Fetch Product Dimensions from Shopify Metafields [#385933]](https://trello.com/c/Xv3QfxPQ/4530-from-sl-fdx-192-fetch-product-dimensions-from-shopify-metafields-385933)

---

## Feature Summary

This feature enables the FedEx Shopify app to automatically pull product dimensions (Length, Width, and Height) from Shopify metafields during product sync, rather than requiring merchants to enter them manually. Merchants configure a single shop-level metafield mapping (namespace + key per dimension) in the app settings. Once configured, the app fetches metafield values whenever a product is synced or updated via webhook, and applies them as the product's shipping dimensions. If a metafield value is absent or invalid for a given product, the app retains the existing manually-entered value — it does not zero it out. Merchants with no mapping configured are completely unaffected; existing behaviour is unchanged.

This feature was built specifically to support large catalogs (5,500–7,500+ SKUs) where manual dimension entry is not feasible.

**Force Import:** Merchants can use the **Force Import** option to sync the latest product updates from Shopify on demand. The Force Import option becomes available under **Product Settings** once the **Sync Dimensions from Metafields** setting has been enabled in **App Settings**. This lets merchants pull the newest metafield-based dimensions without waiting for a webhook-triggered sync.

---

## Toggles / Prerequisites

| Item | Detail |
|---|---|
| Feature toggle | **Yes — gated behind the per-store feature flag:** `<store>.myshopify.com.metafield.dimension.sync.enabled`. Must be enabled per store for the metafield dimension sync to activate. |
| Shopify metafields required | Merchant must have product dimensions stored in Shopify metafields (e.g. `custom.shipping_length`) before mapping will return values |
| Mapping configuration | Merchant must save at least one namespace + key pair in the app's metafield mapping settings for any auto-population to occur |
| Scope | Only **Length, Width, and Height** are mapped from metafields. Weight is not part of this feature. |
| Existing manual values | Retained as fallback when a configured metafield key is missing or returns an invalid value for a specific product |

---

## Where to Find the Feature in the App

The metafield dimension mapping configuration is located in the app's **Settings** area.

**Path:**
> FedEx App (iframe) → **Settings** → *(General Settings or Additional Settings section)* → **Metafield Dimension Mappings**

The mapping UI presents three rows — one each for **Length**, **Width**, and **Height** — each containing two text input fields: **Namespace** and **Key**.

Product-level dimension values populated by this feature are visible in the app's **Products** section, where individual product dimensions can be reviewed after a sync.

> **Products path:** FedEx App (iframe) → **Products**

The **Force Import** option (on-demand sync of the latest product updates from Shopify) is located under **Product Settings**, and appears only after the **Sync Dimensions from Metafields** setting is enabled in **App Settings**.

> **Force Import path:** App Settings → enable **Sync Dimensions from Metafields** → **Product Settings** → **Force Import**

---

## Step-by-Step Walkthrough

### Part 1 — Configure Metafield Mappings in Settings

1. Open the Shopify admin and navigate to the embedded FedEx app.
2. In the app sidebar, click **Settings**.
3. Locate the **Metafield Dimension Mappings** configuration section (within General Settings or Additional Settings).
4. For each dimension the merchant has stored in Shopify metafields, enter the corresponding values:
   - **Length** → enter the **Namespace** (e.g. `custom`) and **Key** (e.g. `shipping_length`)
   - **Width** → enter the **Namespace** and **Key** (e.g. `shipping_width`)
   - **Height** → enter the **Namespace** and **Key** (e.g. `shipping_height`)
5. Leave any row blank if the merchant does not store that dimension in metafields — the app will retain whatever value is already saved for that dimension.
6. Click **Save** (or the equivalent save action for the settings section).
7. After saving, the app may prompt the merchant to trigger a product re-sync to apply the mappings to their existing catalog.

### Part 2 — Verify Dimensions Are Populated on Products

1. In the app sidebar, click **Products**.
2. Select any product that has metafield values set in Shopify for the configured namespace/key pairs.
3. Confirm that the **Length**, **Width**, and **Height** fields reflect the values stored in the Shopify metafields — not zeros or stale manual entries.
4. Select a product that does **not** have metafield values set in Shopify for one or more dimensions.
5. Confirm that the missing dimension retains its previously saved value (manual entry or prior sync value) — it should **not** be zeroed out.

### Part 3 — Verify Behaviour on Product Sync / Webhook Update

1. In Shopify admin, update a product's metafield value (e.g. change `custom.shipping_length` from `15` to `20`).
2. Allow the `products/update` webhook to fire (or trigger a manual sync from the Products section).
3. Return to **Products** in the FedEx app and confirm the updated dimension value is now reflected for that product.
4. Confirm that dimensions for products whose metafields were not changed remain unaffected.

### Part 4 — Force Import the Latest Product Updates

1. Confirm the **Sync Dimensions from Metafields** setting is enabled in **App Settings** — this is what makes the Force Import option appear.
2. Go to **Product Settings** and locate the **Force Import** option.
3. Click **Force Import** to pull the latest product updates (including metafield-based dimensions) from Shopify on demand, without waiting for a webhook-triggered sync.
4. Return to **Products** and confirm the dimensions reflect the most recent Shopify metafield values.

### Part 5 — Verify No Impact When No Mapping Is Configured

1. On a test shop where the Metafield Dimension Mappings section has **no values entered**, trigger a product sync or update.
2. Confirm that product dimensions behave exactly as before this feature — no extra API calls are made, and existing dimension values are preserved.

---

## Expected Behaviour / What Support Should Observe

| Scenario | Expected Result |
|---|---|
| Mapping configured, product has metafield value | Dimension is populated from the metafield value after sync |
| Mapping configured, product has **no** metafield value for a dimension | Existing manually-entered value is retained; field is **not** zeroed |
| Mapping configured, metafield value is invalid/non-numeric | Warning logged server-side; existing value retained for that product |
| **No mapping configured** for the shop | No metafield API calls made; all existing product dimension behaviour unchanged |
| Large catalog re-sync (250+ products) | Metafield values are fetched in batches of up to 250 products per API call — no N+1 calls; sync completes without timeout |
| Product updated in Shopify (`products/update` webhook) | App makes a separate metafield API call for that product (metafields are not included in the webhook payload) and updates dimensions accordingly |
| Rates or label generation after mapping | Rates and labels use the metafield-sourced dimensions; packaging algorithm (box selection, volumetric weight) reflects accurate L/W/H instead of defaulting to 10×10×10 cm |

> **Note for support demos:** If a merchant reports that dimensions are still showing as 10×10×10 cm (the app default when dimensions are missing), the first check is whether the Metafield Dimension Mappings are saved correctly in Settings and whether the product actually has the corresponding metafield values set in Shopify. A product re-sync after saving the mapping is required for the values to be applied to the existing catalog.