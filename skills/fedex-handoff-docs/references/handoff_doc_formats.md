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
The frontend codebase (`FRONTEND_CODE_PATH=/Users/madan/Documents/fedex-Frontend-Code/shopify-fedex-web-client`) has:
- Exact button text strings (e.g. `"Generate Label"`, `"Hold at Location"`)
- Route paths and screen component names
- React/TypeScript component structure showing which screen a feature lives in

When using from Claude app: read the relevant screen/component file directly to extract button labels and flow.

### 3. Backend Source Code (for API / business logic)
The backend codebase (`BACKEND_CODE_PATH`) has:
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
  cd /Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert
  PYTHONPATH=. .venv/bin/python -m ingest.run_ingest --sources codebase
  ```
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

## Support Guide Format

```markdown
# Support Guide — <Feature/Card Name>

## Release Details
- Feature Reference: <id if known>
- Trello: <url>
- App Release: <release>
- Approved: <date>
- Developed by: <names or Unknown>
- Tested by: <names or QA Team>

## Brief Description
Very crisp. 1 short paragraph describing what changed — plain English.

## Toggles & Prerequisites
State whether a feature toggle is required.
If none: "No toggle required — available automatically."
List prerequisites and scope (domestic-only, international-only, etc.).

## Where to Find This in the App
<Use exact navigation paths from APP NAVIGATION MAP above>
Example:
- Shopify admin → Orders → click order → More Actions → "Generate Label"
- FedEx app → SideDock → Hold at Location → modal
- FedEx app → Settings → Account Settings section

## Step-by-Step Walkthrough (Support / Demo)
<Use exact button names from APP NAVIGATION MAP above>

### Scenario A — <happy path>
1. ...
2. ...

### Scenario B — <variant or edge case> (if applicable)
1. ...

## Expected Behaviour — What Support Should Observe
- <Status badge, label code, JSON field value>
- <What is visible on the Order Summary page>
```

Do not add `Business-Safe Explanation`, `Merchant-Safe Explanation`, `Common Questions & Troubleshooting`, `Support Escalation Packet`, `Known Limitations / Rollout Notes`, or `References`. The document ends after `Expected Behaviour`.

---

## Multi-Card Release Package Format

```markdown
# <Release> Support Guide

## Included Story Cards
| Story ID | Story Title | Toggle Name |
|---|---|---|

## <Story ID> - <Card title>
### Brief Description
...
```

Index page rules:

- use exactly three columns: `Story ID`, `Story Title`, `Toggle Name`
- `Story ID` is the story/card number only
- `Story Title` is the card title
- `Toggle Name` is the exact toggle name, or `None` when the card needs no toggle

Do not add a `How Support Should Use This Package` section. The index page is followed directly by the first card section.

---

## Business Brief Format

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

## Quality Checklist (before finalising)

- [ ] Navigation paths use exact labels from APP NAVIGATION MAP (not guessed)
- [ ] Button/link names match EXACT names (e.g. "Generate Label" not "Generate FedEx Label")
- [ ] JSON field paths cited where verification is possible
- [ ] No invented toggles, limitations, or ownership
- [ ] Business Brief under 400 words
- [ ] No technical jargon in Business Brief
- [ ] CI mentioned only for international orders (not domestic)
