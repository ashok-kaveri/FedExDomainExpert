# FedEx App v2.3.122 Support Guide

## Included Story Cards
| Story ID | Story Title | Toggle Name | Trello card link |
|---|---|---|---|
| FDX-200 | FedEx REST Registration Fails for Countries Without Zip Codes | {shop}.myshopify.com.postalcode.required.countries | [FDX-200](https://trello.com/c/X3CBFT0W/4705-from-sl-fdx-200-fedex-rest-registration-fails-for-countries-without-zip-codes) |
| FDX-199 | Display Active/Draft Status on Products Page & CSV Export [#398387] | {shop}.myshopify.com.product.status.enabled, {shop}.myshopify.com.product.force.import.enabled | [FDX-199](https://trello.com/c/zDjKEiJY/4713-from-sl-fdx-199-display-active-draft-status-on-products-page-csv-export-398387) |
| FDX-198 | EU De Minimis: Mandatory Product Identifiers (PIDs) for B2C EU Shipments [#396854] | None | [FDX-198](https://trello.com/c/JHZJq2Ks/4714-from-sl-fdx-198-eu-de-minimis-mandatory-product-identifiers-pids-for-b2c-eu-shipments-396854) |
| FDX-201 | Fix SLGP Return Label Ignores Signature Selection [#394098] | None | [FDX-201](https://trello.com/c/RWA2ffNU/4715-from-sl-fdx-201-fix-slgp-return-label-ignores-signature-selection-394098) |
| - | [F-DIM] Bulk Edit Product Dimensions + Partial CSV Export [#380003] | {shop}.myshopify.com.bulk.edit.dimensions.enabled | [Card](https://trello.com/c/R0jJD113/4716-from-sl-f-dim-bulk-edit-product-dimensions-partial-csv-export-380003) |
| FDX-186 | Display Adjusted Rate Value in Rate Log [#386786] | None | [FDX-186](https://trello.com/c/FytVB5y2/4718-from-sl-fdx-186-display-adjusted-rate-value-in-rate-log-386786) |

## FDX-200 - FedEx REST Registration Fails for Countries Without Zip Codes
**Trello:** [From SL: FDX-200 — FedEx REST Registration Fails for Countries Without Zip Codes](https://trello.com/c/X3CBFT0W/4705-from-sl-fdx-200-fedex-rest-registration-fails-for-countries-without-zip-codes)
**Release:** FedEx App v2.3.122

---

### Brief Description

The FedEx REST registration form previously required a postal code for all countries, blocking merchants in ~65 countries that don't use postal codes (Kuwait, UAE, Qatar, etc.) from completing registration. The fix makes the postal code field conditionally required based on country selection, reusing the postal-code-optional logic already in place for label and rate flows. Existing registered merchants are unaffected.

---

### Toggle / Prerequisites

| Item | Detail |
|---|---|
| Toggle | `{shop}.myshopify.com.postalcode.required.countries` |
| Kuwait postal code field | Toggle must include `["KW"]` for the postal code field to appear for Kuwait |
| UAE / Qatar | No toggle entry needed — postal code field does not appear by default |
| Existing merchants | No action required; saved registration data is preserved |

---

### Where to Find

**Settings → Account** (inside the FedEx app iframe in Shopify admin) — the FedEx REST account registration form.

---

### Step-by-Step Walkthrough

**Scenario 1 — Country without a required postal code (UAE / Qatar)**

1. Open the FedEx app → navigate to **Settings → Account**.
2. In the registration form, select **UAE** or **Qatar** as the country.
3. Confirm the postal code field does not appear.
4. Complete remaining fields with valid credentials and submit — registration succeeds.

**Scenario 2 — Country that requires a postal code (US / UK)**

5. In the registration form, select **US** or **UK** as the country.
6. Confirm the postal code field appears and is marked required.
7. Leave the postal code blank and attempt to submit — a validation error fires.
8. Enter a valid postal code and submit — registration succeeds.

---

### Expected Behaviour

- Switching country selection dynamically shows or hides the postal code field without a page reload — switching from US to Kuwait removes the requirement; switching back restores it.
- Kuwait merchants can register with or without a postal code when the toggle includes `["KW"]`; entering a valid postal code (e.g. `13001`) also succeeds.
- Ireland's county dropdown (from FDX-181) still renders correctly when Ireland is selected — no regression.
- Logged-in merchants who were registered before this release see their account details intact with no re-registration prompt.

## FDX-199 - Display Active/Draft Status on Products Page & CSV Export [#398387]
**Trello:** [From SL: FDX-199 — Display Active/Draft Status on Products Page & CSV Export](https://trello.com/c/zDjKEiJY/4713-from-sl-fdx-199-display-active-draft-status-on-products-page-csv-export-398387)

---

### Brief Description

The Products page now displays a **Status column** showing each product's Shopify publish state (Active, Draft, or Archived) as a colour-coded badge. Status is kept current automatically via webhook on product updates; the Force Import button can be used to backfill status for products imported before this feature was enabled. The same status value is included in CSV exports when the feature is toggled on.

---

### Toggle / Prerequisites

| Item | Detail |
|---|---|
| **Primary toggle** | `{shop}.myshopify.com.product.status.enabled` → must be `true` |
| **Force Import toggle** | `{shop}.myshopify.com.product.force.import.enabled` → must be `true` to expose the Force Import button |
| **Default state** | Both toggles are **OFF** by default; nothing is visible until enabled |
| **Release** | FedEx App v2.3.122 |

---

### Where to Find

App sidebar → **Products**

The Status column and Force Import button appear in the product list table only when `product.status.enabled` is ON.

---

### Step-by-Step Walkthrough

**Scenario 1 — Verify Status column and badges**

1. Enable `product.status.enabled` for the store in the toggle config.
2. Navigate to **Products** in the app sidebar.
3. Confirm the **Status** column is visible in the product table.
4. Check badge colours: Active → green, Draft → blue, Archived → grey, never-synced → `—`.

**Scenario 2 — Force Import and CSV export**

5. Click the **Force Import** button; confirm the toast reads **"Force import sync started"**.
6. If clicked again while running, confirm the toast reads **"Force Import is already in progress. Please wait."**
7. Manually refresh the page after sync completes; confirm badges now reflect correct statuses.
8. Click the CSV export control; open the file and confirm a **Status** column is present with values `active`, `draft`, or `archived`.

---

### Expected Behaviour

- With the toggle **OFF**, neither the Status column nor the Force Import button renders anywhere on the Products page, and the exported CSV contains no Status column.
- Products set to **Unlisted** in Shopify display as **Active** (Shopify maps unlisted to active in its API response).
- Status changes made directly in Shopify (publish, archive) propagate to the app automatically within a few seconds via webhook — no manual sync required.
- The page does **not** auto-refresh after Force Import completes; support should instruct the merchant to refresh manually to see updated badges.

## FDX-198 - EU De Minimis: Mandatory Product Identifiers (PIDs) for B2C EU Shipments [#396854]
**Trello:** [From SL: FDX-198 — EU De Minimis: Mandatory Product Identifiers (PIDs) for B2C EU Shipments](https://trello.com/c/JHZJq2Ks/4714-from-sl-fdx-198-eu-de-minimis-mandatory-product-identifiers-pids-for-b2c-eu-shipments-396854)

---

### Brief Description

FedEx now requires Manufacturer Product Identifiers on every commodity line for B2C EU shipments under the EU de minimis regulation. Two new fields — **Mfr Product ID (Non-Standard)** and **Mfr Product ID (Standard GTIN/UPC)** — have been added to each product's Customs Information section. These values are injected into the FedEx REST ship request for EU-bound shipments only; non-EU and non-US destinations are unaffected. The product SKU is used alongside these fields when present, but label generation proceeds even if SKU is absent.

---

### Toggle / Prerequisites

- **Feature toggle:** None — fields are live for all merchants on v2.3.122.
- **Applies to:** B2C EU shipments only; PIDs are not injected for US, Canada, India, or other non-EU destinations.
- **Character limit:** Each PID field accepts a maximum of 70 characters; labels will fail if this is exceeded.
- **CSV import/export:** Bulk population is supported via Products CSV.

---

### Where to Find

**Settings → Products →** open any product → **Customs Information** section.

---

### Step-by-Step Walkthrough

**Scenario 1 — Verify and save PID fields on a product**

1. In the app, go to **Settings → Products** and open any product.
2. Scroll to the **Customs Information** section — confirm **Mfr Product ID (Non-Standard)** and **Mfr Product ID (Standard GTIN/UPC)** are visible.
3. Enter values in one or both fields and click **Save** — reopen the product to confirm values persist.

**Scenario 2 — Generate an EU label with PIDs set**

4. Ensure the product has PID values saved (Scenario 1 above).
5. From Shopify Orders, click the order row → **More Actions** → **Generate Label**.
6. Confirm the destination is an EU country (e.g., Germany, France).
7. Select a rate and click **Generate Label** — label should generate successfully.
8. To test CSV: export Products CSV and confirm **Standard Manufacturer Product Id** and **Non Standard Manufacturer Product Id** columns are present; import a CSV with values in those columns and verify they save correctly on the product.

---

### Expected Behaviour

- Both PID fields appear in **Customs Information** and save independently — filling only one, both, or neither all save without validation errors.
- EU B2C labels generate successfully when PIDs are present; labels also generate when SKU is absent.
- Labels to non-EU/non-US destinations (Canada, India, etc.) generate normally with no PID-related changes.
- Any PID value exceeding 70 characters causes label generation to fail.

## FDX-201 - Fix SLGP Return Label Ignores Signature Selection [#394098]
**Trello:** [From SL: FDX-201 — Fix SLGP Return Label Ignores Signature Selection [#394098]](https://trello.com/c/RWA2ffNU/4715-from-sl-fdx-201-fix-slgp-return-label-ignores-signature-selection-394098)

---

### Brief Description

When a merchant selected a signature option on the SLGP return label page, the generated label was using the product-level signature setting instead — overriding the merchant's explicit choice. For DE→DE routes (confirmed with Ante Running), this caused return label generation to fail entirely with a FedEx service unavailability error. The fix guards the product-level signature override so it no longer applies when generating a return label, while leaving forward label behaviour unchanged.

---

### Toggles / Prerequisites

- No feature toggle — fix is live in FedEx App v2.3.122.
- Merchant must have the FedEx app installed and at least one order eligible for a return label.
- To reproduce the product-level conflict, a product with a signature type configured under **Products** is needed.

---

### Where to Find

**Shopify Admin → Orders** → click order row → **More Actions** → **Generate Return Label**
— or —
**Order Summary page** → **Return packages** tab → **Return Packages** button → select rate → **Generate Return Label**

---

### Step-by-Step Walkthrough

**Scenario 1 — Return label honours SLGP signature selection**

1. Open any order in Shopify Admin and navigate to the Order Summary page.
2. Click the **Return packages** tab, then click **Return Packages**.
3. In the SideDock, select a signature option (e.g. **Direct Signature**).
4. Click **Refresh Rates**, select a rate, then click **Generate Return Label**.
5. Confirm the label is created and the signature on the label matches what was selected — not the product-level setting.

**Scenario 2 — Forward label is unaffected**

6. Open an order whose product has a signature type set at the product level.
7. Navigate to the label page via **More Actions → Generate Label**, then click **Generate Label**.
8. Confirm the forward label uses the product-level signature exactly as before.

---

### Expected Behaviour

- Return labels generate successfully for all routes, including DE→DE, with no "FedEx service is not currently available" error.
- The signature type on a return label matches the option selected on the SLGP page, regardless of what is configured at the product level.
- Forward labels continue to use the product-level signature setting — no change in behaviour.
- Bulk return labels (Shopify Orders list → **Actions → Auto-Generate Labels**) also generate successfully with the correct signature applied.

## [F-DIM] Bulk Edit Product Dimensions + Partial CSV Export [#380003]
**Trello:** [From SL: \[F-DIM\] Bulk Edit Product Dimensions + Partial CSV Export \[#380003\]](https://trello.com/c/R0jJD113/4716-from-sl-f-dim-bulk-edit-product-dimensions-partial-csv-export-380003)

---

### Brief Description

Merchants can now select multiple products on the Products page and bulk-edit their dimensions (Length, Width, Height with units) in a single modal, instead of opening each product individually. A new **Export Selected** action downloads a partial CSV (`Product-Export-Selected.csv`) containing only the checked products, while the existing **Export** button (no selection) still produces the full-catalogue `Product-Export.csv`. Both paths support the existing CSV import round-trip for dimension updates.

---

### Toggle / Prerequisites

- **Toggle:** `{shop}.myshopify.com.bulk.edit.dimensions.enabled` must be `true` — checkboxes and bulk actions are hidden when off.
- Metafield sync scenario (warning banner + disabled fields) was descoped; no action needed for that path.
- Selection clears automatically on page change or search/filter update — expected, not a bug.

---

### Where to Find

App sidebar → **Products** page. With the toggle on, each product row shows a checkbox. The bulk action bar appears above the list when one or more products are selected.

---

### Step-by-Step Walkthrough

**Scenario 1 — Bulk Edit Dimensions**

1. Navigate to **Products** in the app sidebar.
2. Check 2–3 product rows; confirm the bulk action bar appears.
3. Click **Edit Dimensions** in the bulk action bar.
4. In the modal, enter valid Length, Width, and Height values (with units) for each product row.
5. Confirm **Save** becomes enabled only when all three dimension fields are filled per row; click **Save**.
6. Verify the modal closes, the product list refreshes, and updated dimensions are visible.

**Scenario 2 — Export Selected → Edit → Import**

1. Check at least 1 product row; click **Export Selected** — browser downloads `Product-Export-Selected.csv`.
2. Edit a dimension value in the CSV, re-import via the existing **Import** flow; confirm the import confirmation appears and the product reflects the new value.

---

### Expected Behaviour

- **Save button state:** disabled until every selected product has all three dimension fields filled; negative values trigger a validation error, `0` is accepted without error.
- **Export file names:** partial export → `Product-Export-Selected.csv` (only selected rows + header); full export → `Product-Export.csv` (entire catalogue); checkboxes clear automatically after export.
- **Post-save refresh:** product list reloads with updated dimensions; opening an individually edited product confirms the bulk-saved values persisted.
- **Toggle off:** no checkboxes render on the Products page and no bulk action bar is accessible.

## FDX-186 - Display Adjusted Rate Value in Rate Log [#386786]
**Trello:** [From SL: FDX-186 — Display Adjusted Rate Value in Rate Log](https://trello.com/c/FytVB5y2/4718-from-sl-fdx-186-display-adjusted-rate-value-in-rate-log-386786)
**Release:** FedEx App v2.3.122

---

### Brief Description

The Rate Log detail view previously showed only the raw FedEx account rate, giving merchants no way to confirm their markup or markdown adjustments were being applied correctly. This change adds a **Final Rate** column to the Rate Log detail that displays the post-adjustment rate alongside the account rate and the adjustment value. When no adjustment is configured for a service, the Final Rate column shows `--` rather than an empty or erroneous value.

---

### Toggle / Prerequisites

- No feature toggle — change is live for all merchants on v2.3.122.
- Merchant must have at least one rate adjustment (% markup, % markdown, or flat value) configured on a FedEx service for the Final Rate column to populate.
- Carrier Calculated Rates must be enabled on the Shopify store for checkout-triggered rate requests to appear in the log.

---

### Where to Find

**App sidebar → Rates Log** → click any rate request row to open the detail view.

---

### Step-by-Step Walkthrough

**Scenario 1 — Service with an adjustment configured**

1. In the FedEx app sidebar, click **Rates Log**.
2. Click any rate request row that was triggered after a checkout with an adjusted service.
3. In the detail view, locate the service row (e.g. FedEx International Priority).
4. Confirm the **Final Rate** column shows the calculated post-adjustment value (e.g. Account Rate × 1.15 for a +15% markup, or Account Rate + $10 for a flat markup).

**Scenario 2 — Service with no adjustment / legacy entry**

5. From **Rates Log**, open a rate request for a service with no adjustment configured, or open any log entry created before v2.3.122.
6. Confirm the **Final Rate** column displays `--` with no error or blank cell.

---

### Expected Behaviour

- **Final Rate populated:** For any service with an active adjustment, Final Rate = Account Rate with the configured markup/markdown applied; the value must match exactly what the customer saw at Shopify checkout for the same request.
- **Combined adjustments:** When both a percentage and a flat value are configured on the same service, the Final Rate reflects both adjustments applied together.
- **No adjustment / zero adjustment:** Final Rate shows `--` — this applies to unadjusted services within the same request, 0% adjustments, and all pre-v2.3.122 log entries.
- **Markdown:** A negative adjustment (e.g. −10%) produces a Final Rate lower than the Account Rate; the adjustment label reflects the negative value.
