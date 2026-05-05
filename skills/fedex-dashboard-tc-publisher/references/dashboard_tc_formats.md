# Dashboard TC Publish Formats

This reference mirrors the current dashboard behavior in:

- `pipeline/card_processor.py`
- `pipeline/sheets_writer.py`
- `ui/pipeline_dashboard.py`

## Detailed Test Case Markdown

Source format used by the dashboard:

```markdown
### TC-{n}: <short title>
**Type:** Positive | Negative | Edge
**Priority:** High | Medium | Low
**Preconditions:** <what must be true before testing>

**Steps:**
Given <initial state>
When <first action>
And <additional action>
Then <expected result>
And <additional expected result>
```

Validation rules:

- Every TC block starts with `### TC-n:`.
- Every TC has exactly one `**Type:**` line.
- Every TC has a `**Priority:**` line.
- Every TC has a `**Preconditions:**` line.
- Every TC has a `**Steps:**` section.
- Step lines must start with `Given`, `When`, `And`, `Then`, or `But`.
- No numbered steps under `**Steps:**`.
- No bullet steps under `**Steps:**`.
- No unit-test/backend-only wording: unit test, mock, stub, assert returned object, method returns, function returns, call helper directly.
- No mobile/responsive/viewport cases.

## Compact Trello QA Comment

Dashboard format:

```markdown
📋 **QA Test Cases — {card_name} ({release})**
_Prepared by: {qa_name}_

**✅ Positive**
• TC-1: <title> — <first Then line>
• TC-2: <title> — <first Then line>

**❌ Negative**
• TC-3: <title> — <first Then line>

**⚠️ Edge**
• TC-4: <title> — <first Then line>

_Total: {total} cases — {positive_count} positive · {negative_count} negative · {edge_count} edge_
```

Rules:

- Omit `_Prepared by:` if QA name is unknown.
- Omit a group section if that group has no cases.
- The one-line result comes from the first `Then ...` line in the detailed TC block.
- This compact summary is for Trello only.
- This compact summary is not enough to regenerate Sheet rows.

## CSV / Google Sheet Row Format

For the Codex/Claude skill flow, always target sheet tab:

```text
Ai
```

This overrides the dashboard's older keyword-based tab selection. Keep the CSV columns the same.

Dashboard sheet columns:

```csv
SI No,Epic,Scenarios,Description,Comments,Priority,Details/Transaction ID,Pass/Fail [Shopify],Release
```

Column mapping:

- `SI No`: sequential row number in this generated output unless the user provides existing last SI No.
- `Epic`: provided epic, otherwise card name.
- `Scenarios`: TC title after `### TC-n:`.
- `Description`: Given/When/And/Then steps joined with newlines.
- `Comments`: Preconditions.
- `Priority`: High / Medium / Low.
- `Details/Transaction ID`: blank unless user provides a value.
- `Pass/Fail [Shopify]`: blank unless user provides a value.
- `Release`: release name if provided.

Positive-only rule:

- Add only `**Type:** Positive` cases to CSV / Google Sheet rows.
- Negative and Edge cases go to the Trello comment only.

CSV generation notes:

- Quote fields containing commas, quotes, or newlines.
- Escape quotes inside CSV fields by doubling them.
- Keep multiline Given/When/Then text in the `Description` cell when producing CSV.

## Count Summary

Dashboard style:

```markdown
📊 **{total} total TCs** · ✅ {positive_count} positive → Sheet · ❌ {negative_count} negative → Trello comment only · ⚠️ {edge_count} edge → Trello comment only
```

## Compact Summary Detection

A Trello summary starts with:

```text
📋 **QA Test Cases —
```

If input is already a compact summary:

- You can report counts from the `_Total:` line.
- Do not create CSV rows from it.
- Ask for or regenerate full detailed TC markdown before Sheet output.

## Sheet Tab Rule

For this skill, always output:

```markdown
**Target Sheet Tab:** Ai
```

Do not use keyword detection unless the user explicitly asks for the old dashboard tab behavior.

## Legacy Sheet Tab Keyword Map

Only use this if the user explicitly asks for old dashboard tab detection. Suggest the first strong match:

- `Rate Settings`: rate setting, carrier service, adjustment, display name, shipping cost, checkout rate
- `Rate_Domestic_Packaging Type`: domestic packaging, domestic package type, packaging type domestic
- `Rate_International_Packaging Type`: international packaging, international package type, packaging type international
- `Label_Domestic_Packaging Type`: label domestic packaging, label package domestic
- `Label_International_Packaging Type`: label international packaging, label package international
- `Single Label Generation [manual]`: single label, manual label, generate label, label generation
- `Return Setting & Return Label`: return, return label, return setting
- `Pickup Settings`: pickup, pick up, schedule pickup
- `Additional Services`: dry ice, dangerous goods, alcohol, signature, one rate, hold at location, duties, tax, saturday delivery, pass signature, priority signature
- `Documents/Labels Settings1`: document, commercial invoice, customs, CI, ETD, label size, label format, label setting
- `Printing & Downloading`: print, download, printing, downloading, bulk print
- `Bulk order cases`: bulk, bulk order, multiple orders
- `Orders Grid [order's page ]`: order grid, orders page, order list, fulfillment
- `International Shipping Settings`: international, global, cross-border, Qatar, Kuwait, postal code, country
- `Settings > account settings `: account setting, account setup, API key, meter number, credentials, FedEx account
- `Settings > Print Settings`: print setting, label size, label format, thermal, print format, label stock
- `Settings > Notifications`: notification, email notification, tracking email, notify
- `Settings>Subscription`: subscription, plan, billing, upgrade
- `Pluginhive app setup`: app setup, installation, install, onboard, setup
- `Locations ON/OFF`: location, warehouse, origin location, ship from
- `Defects`: defect, bug, fix, issue

Legacy fallback:

- If no confident keyword match exists, suggest `Draft Plan`.
