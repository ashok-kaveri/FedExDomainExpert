# FedEx Handoff Document Formats

This reference is based on `pipeline/handoff_docs.py`, the dashboard Handoff Docs tab, and the FedEx release package conventions.

---

## HOW TO FIND NAVIGATION STEPS (priority order — follow this every time)

When writing "Where to Find This in the App" and "Step-by-Step Walkthrough", use this order:

### 1. AI QA Evidence (BEST — use if available)
The AI QA verifier ran real `navigate` / `click` / `fill` actions in the live app.
The `ai_qa_evidence` field contains those exact steps — button names, URLs, element labels.
**Extract the walkthrough from the evidence steps directly.** This is ground truth for any feature, including brand-new ones.

### 2. Frontend Source Code (for NEW features without AI QA evidence)
The frontend codebase (path from the `FRONTEND_CODE_PATH` env var in this project's `.env`) has:
- Exact button text strings (e.g. `"Generate Label"`, `"Hold at Location"`)
- Route paths and screen component names
- React/TypeScript component structure showing which screen a feature lives in

When using from Claude app: read the relevant screen/component file directly to extract button labels and flow.

### 3. Backend Source Code (for API / business logic)
The backend codebase (path from the `BACKEND_CODE_PATH` env var) has:
- API endpoint names and routes
- Feature flag / toggle names
- Service type codes and option names

### 4. Test Cases + AC Text (tertiary)
TCs describe expected steps. AC text describes intended behaviour.
Use only if source code is unavailable or incomplete.

### 5. Navigation Unknown — Check Index, Then Ask QA

If no source gives clear navigation steps, follow this exact sequence:

**Step A — Check if code is indexed:**
```python
from rag.code_indexer import get_index_stats
stats = get_index_stats()
# stats = {"frontend": N, "backend": M, "total": T, ...}
```
- If `frontend == 0` or `backend == 0` → code is NOT indexed or stale
- Tell the user: "The code index is empty/stale. Re-index first, then retry."
- Re-index command:
  ```bash
  PYTHONPATH=. .venv/bin/python -m ingest.run_ingest --sources codebase
  ```
  (run from this project's root)
- After re-indexing: retry code search and try again.

**Step B — If still not found after indexing (or index is current but no results):**
Add a `⚠️ QA NOTE` block at the TOP of the support guide document:

```markdown
---
> ⚠️ **QA NOTE — Navigation Confirmation Needed**
> For card: **[Card Name]**
>
> The following navigation steps could not be determined from available sources
> (AI QA evidence, frontend/backend code, AC/TC text).
> Please confirm the exact steps before sharing this document with the support team:
>
> - [ ] **Where to find**: _e.g. "Which app sidebar section / Settings sub-page contains this feature?"_
> - [ ] **Step N**: _e.g. "What is the exact button/link label? Is it inside a dropdown or directly visible?"_
> - [ ] **Step N+1**: _e.g. "After clicking, what does the user see? Any dialog/modal/redirect?"_
>
> Once confirmed, update the Walkthrough section below with the actual steps.
> If re-indexing the codebase resolves this, regenerate the document.
---
```

**When using from the Claude app (no dashboard):**
Post the QA NOTE message to the QA team via Slack using `fedex-slack-operator`:
```
Hey team, I generated a support guide for [Card Name] but couldn't determine the exact navigation steps for [feature].
Could someone confirm: [specific question about the missing step]?
Once confirmed I'll update the doc. Thanks!
```

Do NOT invent paths. A wrong walkthrough is worse than an honest unknown with a clear question.

---

## APP NAVIGATION MAP (embed in every walkthrough — do not guess)

The FedEx app is embedded inside Shopify admin as an **iframe** (`iframe[name="app-iframe"]`).

### App Sidebar (INSIDE iframe) — exact sections

| Sidebar label | What's there |
|---|---|
| Shipping | All Orders grid |
| Settings | Account, Packaging, Carrier Services, Additional Settings, International Shipping, Pickup Settings, etc. |
| Products | Map Shopify products to special services (Signature, Insurance, DG, etc.) |
| PickUp | Schedule FedEx pickup |
| Rates Log | Historical rate request / response JSON logs |
| FAQ | Help articles |

### Shopify Admin Sidebar (OUTSIDE iframe)

- **Orders** — Shopify orders list (click order → More Actions to reach the FedEx app)
- **Products** — Shopify product catalog

### All Orders Grid (Shipping page)

Tabs: **All | Label Created | Awaiting Shipment | Shipped | Cancelled | Delivery Exception**

### Manual Label Generation

```
1. Shopify admin → Orders → click order row
2. Click More Actions button  ← on the Shopify order page, outside iframe
3. Click "Generate Label" link  ← EXACT name (role=link)
4. FedEx app opens in iframe — label generation page:
   LEFT PANEL:
     a. Generate Packages
     b. Get Rates
     c. Select rate radio button
   RIGHT PANEL (SideDock — configure BEFORE clicking Generate Label):
     1. Address Classification  → Residential / Commercial
     2. Signature Options       → Adult / Direct / Indirect / No Signature / Service Default
     3. Hold at Location (HAL)  → button → modal → select FedEx location → Yes
     4. Insurance               → checkbox → pencil icon → modal → enter declared value
     5. COD                     → checkbox → COD Amount, TIN Type, contact, address
     6. Duties & Taxes (intl)   → Purpose, Terms of Sale, Duties Payment Type
     7. Freight                 → Additional freight info
5. Click "Generate Label"
6. Redirects to Order Summary page
```

### Auto Label Generation

```
Shopify admin → Orders → click order row → More Actions → "Auto-Generate Label"
→ Label generated automatically → Order Summary page
```

### Bulk Label Generation

```
Shopify admin → Orders list → select orders (header checkbox)
→ Actions button → "Auto-Generate Labels" (link, not button)
```

### Return Label

```
Way A: Order Summary → "Return packages" tab → "Return Packages" button
       → Refresh Rates → select service → "Generate Return Label"
Way B: Shopify Orders → More Actions → "Generate Return Label"
       (NOT "Create return label" — that is Shopify-native)
```

### Order Summary Page — Key Buttons

```
Print Documents       → opens PluginHive document viewer in a NEW TAB
Upload Documents      → custom doc upload
Download Documents    → downloads ZIP (label PDF + packing slip — NO JSON)
Track Order           → track shipment
More Actions ▾        → Cancel Label | Return Label | How To
  How To → modal → "Click Here" button downloads RequestResponse ZIP (label PDF + request/response JSON)
Tabs: Packages | Return packages
```

> ⚠️ **Important distinction**: `Download Documents` = label PDF + packing slip only (no JSON).
> The request/response JSON is ONLY available via **More Actions → How To → Click Here**.

### Checking Request JSON (via How To → Click Here ZIP)

Key JSON field paths:
```
requestedShipment.requestedPackageLineItems[0].dimensions         → L/W/H
requestedShipment.requestedPackageLineItems[0].weight.value       → weight
requestedShipment.requestedPackageLineItems[0].declaredValue.amount → insurance value
requestedShipment.requestedPackageLineItems[0].packageSpecialServices.signatureOptionType
requestedShipment.shipmentSpecialServices.specialServiceTypes
  → "HOLD_AT_LOCATION" | "DRY_ICE" | "ALCOHOL" | "BATTERY" | "FEDEX_ONE_RATE"
requestedShipment.shipmentSpecialServices.holdAtLocationDetail.locationId
requestedShipment.shipmentSpecialServices.alcoholDetail.alcoholRecipientType
```

### Label Visual Codes (Print Documents → new tab)

```
"ICE"     → dry ice
"ALCOHOL" → alcohol shipment
"ELB"     → battery (NOT "BATTERY")
"ASR"     → Adult Signature Required
"DSR"     → Direct Signature Required
"ISR"     → Indirect Signature Required
"SS AVXA" → Service Default signature
```

### Products Configuration

```
App sidebar → Products → search product → click product row
Configure special services → Save
```

### Settings Navigation

```
App sidebar → Settings → scroll to relevant section
Sections: Account | Packaging | Carrier Services | Additional Settings |
          International Shipping | Pickup Settings | etc.
```

### Pickup Scheduling

```
App sidebar → PickUp → schedule FedEx pickup
```

### Rates Log

```
During label flow: after "Get Rates" → click ⋯ menu → "View Logs"
→ Dialog shows JSON request (left) + response (right) IN PAGE
After label: Order Summary → More Actions → How To → "Click Here" downloads RequestResponse ZIP (JSON)
         (Download Documents has PDFs only — NOT JSON)
```

### Commercial Invoice (CI)

CI is only present in Download Documents / Print Documents for **international orders** (shipments outside US).
Domestic US orders have label PDF + packing slip only — no CI.

---

## Support Guide Tone

Professional, practical, support-ready.

Audience:

- support team
- demo team
- implementation/support leads

The support reader should be able to explain the feature to a merchant without asking engineering.

Use:

- clear brief description
- concrete paths and steps
- "what support should observe"

Avoid:

- technical words anywhere in the body — code, class, file, or method names, API or schema jargon, internal engineering terms. Three exemptions: the request/log callouts, the `Technical Cards` section, and toggle keys in the index table and `Toggles & Prerequisites` tables
- deep code/internal implementation details
- vague "works correctly" wording
- unsupported claims
- excessive QA/test-count language

---

## Per-Card Support Guide Required Sections

```markdown
# Support Guide: <Story ID or concise feature name>

## Brief Description
Very crisp. 1 short paragraph.

## Toggles & Prerequisites
State whether a feature toggle is required.
If none: "No toggle required — available automatically."
List prerequisites and scope (domestic-only, international-only, SOAP vs REST, per-product vs account-wide).

## Step-by-Step Support Walkthrough
Use Scenario A/B/C when useful. Put the exact navigation inside the action step, taken from the
APP NAVIGATION MAP above — for example Shopify admin Orders, More Actions, "Generate Label",
the SideDock options, app sidebar Settings/Products/PickUp/Rates Log, or the Order Summary buttons.

## Expected Behaviour
Summarize the key signal support should observe: status badge, label visual code, Order Summary state.
```

Do not add `Release Details`, `Where to Find This in the App`, `Business-Safe Explanation`, `Merchant-Safe Explanation`, `Common Questions & Troubleshooting`, `Support Escalation Packet`, `Known Limitations / Rollout Notes`, or `References`. The card section ends after `Expected Behaviour`, and navigation lives inside the walkthrough steps.

---

## Combined Support Guide Required Sections

```markdown
# <Release> Support Guide

## Included Story Cards
| Story ID | Story Title | Toggle Name | Trello card link |
|---|---|---|---|

## <Story ID> - <Card title>
### Brief Description
...

## Technical Cards
### <Story ID> - <Card title>
...
```

Do not add a `How Support Should Use This Package` section. The index page is followed directly by the first card section.

Index page rules:

- use exactly four columns: `Story ID`, `Story Title`, `Toggle Name`, `Trello card link`
- `Story ID` is the story/card number only
- `Story Title` is the card title
- `Toggle Name` is the exact toggle name, or `None` when the card needs no toggle. Source it from anywhere in the card evidence — description, comments, checklists, attachments, approved AC, TCs, QA notes — because the exact key is often only in a comment. Comma-separate multiple keys. Never guess a key; write `Not stated` and flag it when a card clearly needs one but names none
- list technical cards in their normal position here even though their body section moves to the end
- `Trello card link` is a markdown link to the card, labelled with the story id, for example `[941](https://trello.com/c/abc123)`; use `-` when no card URL is known

---

## Technical Cards Section Structure

```markdown
## Technical Cards

### <Story ID> - <Card title>
Two to four lines: what changed, and why it matters.
```

Rules:

- one `## Technical Cards` H2, placed after the last normal card section, and omitted when the release has no technical cards
- a technical card is developer-only work — API-only change, library or version upgrade, refactor, internal clean-up, infrastructure — with nothing support or the merchant can see or do
- a card with both a technical part and a visible part stays a normal card
- each entry is an H3 so the short entries flow together; the renderer already breaks a page before the `## Technical Cards` H2 itself, so never hand-place a break
- no walkthrough, toggles, or expected-behaviour subsections inside these entries
- plain wording still applies; name a version, endpoint, or field only when the entry makes no sense without it

---

## Combined Business Brief Required Structure

```markdown
# What's New: <Release>

## Release Overview
2-3 sentences describing the release value.

## Included Updates
| Story ID | Story Title | Toggle Name | Trello card link |
|---|---|---|---|

## <Story ID> - <Card title>
Per-card plain-English business brief.

## Technical Cards
### <Story ID> - <Card title>
...
```

---

## Per-Card Business Brief Format

```markdown
## <Feature Name in Plain English>
*One sentence headline value.*

---

### Brief Description
2–3 sentences on what frustration or inefficiency existed before.

---

### What's New
- <Action verb + what merchant can now do>
- <3–5 bullets total>

---

### Who Benefits
- **<Merchant type>**: <outcome in 1–2 sentences>
- **<Merchant type>**: <outcome>

---

### Why It Matters
2–3 sentences. Time saved, fewer support tickets, merchant satisfaction.

---

### Availability
One line. If no setup: "Available automatically — no setup required."
```

### Business Brief Rules

- Max ~400 words
- Plain business English — no API, JSON, iframe, regex, backend, frontend, GraphQL
- No developer or QA attribution
- No test case counts, no QA notes
- No internal Trello links in the body
- No toggle detail unless merchant or rollout team must act

---

## Tone Guide

**Support Guide**: Professional, practical, support-ready. Clear paths and what to observe.

**Business Brief**: Plain English. A smart businessperson who has never opened the app should understand it in under 2 minutes.

---

## Release QA Guardrails

- Build release packages from full live Trello card context when available: description, labels, comments, checklists, approved AC/TCs, and AI QA evidence.
- Treat QA comments as required review input because late caveats often appear there.
- Exclude cards labelled `SL: ON Hold`, `SL: Carrier Platform`, `Spill Over`, or `SL: Closed By Support` from both the index table and the body, matching labels case-insensitively. Match on Trello labels, not on the title — `SL: FDX` and `SL: ZI` are story-id prefixes and never exclude a card. Include an excluded card only when the user names it. Report every exclusion and the label behind it; never drop a card silently.
- Run a toggle audit per card across the whole card, not only the description. The exact toggle key is often only in a QA or developer comment. Never guess a key.
- Run a technical-card audit per card and collect developer-only cards into the trailing `Technical Cards` section.
- Run a scope audit per card. Every card is Shopify — the axes that vary are domestic vs international, affected service/special-service types, SOAP vs REST accounts, and account-wide vs per-product. Never widen a scoped change.
- After a release package is generated, send the consolidated toggle list as a Slack DM to `ashok@pluginhive.com` per the `Toggle List Follow-Up` section of `SKILL.md`. FedEx toggle keys are shop-domain scoped, for example `"fedexapp-dg-csp.myshopify.com.fedex.rest.use.comprehensive.rates.enabled": true,`. Skip it when no card has a toggle.
- Do not include a generic `Where to Find This in the App` section. The detailed walkthrough is the source of truth for where support should go.
- Keep feature-specific paths and carrier-specific steps inside the walkthrough sections.
- Every story card section starts on a new PDF page, including the first — the index page stands alone. `render_pdf_bytes` inserts a page break before each `<Story ID> - <Title>` heading, so do not add manual page breaks or blank filler.
- Before final PDF generation, verify no card starts at the bottom of a page without the card detail table/content following on the same page.
- Run a card-by-card payload/log audit before final PDF generation:
  - If QA/support must inspect a carrier request, response, payload, rates log, request/response JSON, tracking payload, or report source field, include the exact node or log field.
  - Put exact nodes/fields in the walkthrough as a highlighted callout using one of these exact labels: `Request node to verify:`, `Request nodes to verify:`, `Request/response nodes to verify:`, or `Request/log fields to verify:`.
  - Use the exact FedEx paths from the `Checking Request JSON` section above.
  - Say where the payload comes from: the rates log dialog during the label flow, or `More Actions -> How To -> Click Here` after the label exists. `Download Documents` has PDFs only.
  - Keep those node names out of merchant-safe wording.
  - Do not invent fields for UI-only, sync-only, report-only, or performance-only cards.

---

## PDF Rendering

Use `pipeline.handoff_docs.render_pdf_bytes` through the skill helper script `scripts/render_handoff_pdf.py`. This gives the same polished dashboard PDF styling.

For release handoff, render one combined Support Guide PDF and one combined Business Brief PDF. Create individual PDFs only for explicit single-card requests.

---

## Quality Checklist (before finalising)

- [ ] Navigation paths use exact labels from APP NAVIGATION MAP (not guessed)
- [ ] Button/link names match EXACT names (e.g. "Generate Label" not "Generate FedEx Label")
- [ ] Exact request/log node names cited as highlighted callouts where verification is possible
- [ ] No technical jargon in the body of either document, outside the three exemptions
- [ ] No card carrying an excluded label reached the index table or the body
- [ ] Technical-only cards sit in the trailing `Technical Cards` section
- [ ] Every card's toggle was searched for across comments, checklists, and QA evidence
- [ ] No invented toggles, limitations, or ownership
- [ ] Business Brief under 400 words
- [ ] CI mentioned only for international orders (not domestic)
