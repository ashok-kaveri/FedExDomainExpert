---
name: fedex-ai-qa-browser
description: Use when working inside the FedexDomainExpert project to verify FedEx Shopify app test cases in the real browser, reproduce manual or auto label scenarios, compare behavior with the existing automation patterns, debug flaky navigation or download flows, and produce a pass/fail result with evidence and next-step knowledge updates.
---

# FedEx AI QA Browser

Use this skill when the user gives a test case, scenario, AC, or bug and wants real verification against the FedEx Shopify app using the FedexDomainExpert project.

This skill is meant to cover the full FedEx Shopify QA surface, not only one scenario family. It should be used for:

- domestic label generation
- international label generation
- manual label scenarios
- auto label scenarios
- side dock options
- packaging settings and advanced packaging rules
- pickup scheduling
- return labels
- bulk label generation
- product-level special services
- request/response log validation
- PDF/document validation
- navigation and regression checks
- new or unfamiliar FedEx app scenarios that still fit the project domain

## First reads

Before taking action:

1. Read `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/AGENTS.md`.
2. Treat `AGENTS.md` as the source of truth for:
   - app architecture
   - manual vs auto label flows
   - order decision logic
   - verification strategies
   - known bugs already fixed
3. When the task touches orchestration or behavior, inspect only the files directly involved:
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/smart_ac_verifier.py`
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/order_creator.py`
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/ui/pipeline_dashboard.py`
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/rag_updater.py`

## Goal

Given a test case or scenario, do three things well:

1. Understand what the scenario needs.
2. Verify it in the real app using the same reliable flows the team already uses.
3. Return a concise verdict with evidence, blockers, and any durable learning that should be added back into the project.

The expectation is that the skill can handle all normal FedEx app test scenarios by combining:

- the rules in `AGENTS.md`
- the verifier logic in `pipeline/smart_ac_verifier.py`
- the order creation logic in `pipeline/order_creator.py`
- the existing Playwright automation patterns in `fedex-test-automation`

Do not narrow the skill to a single bug, a single modal, or a single feature.

## Browser surface

For live app verification, prefer the real browser surface the user is already using:

- Use Chrome through `Computer Use` when the task is about the real Shopify admin or the installed FedEx app.
- Use the existing automation repo as the ground truth for stable selectors and working flows.
- Do not invent a brand-new flow if the automation already covers it.

Automation repo reference:

- `/Users/madan/Documents/Fed-Ex-automation/fedex-test-automation`

Important related page objects and specs:

- `/Users/madan/Documents/Fed-Ex-automation/fedex-test-automation/src/pages/app/ManualLabelPage/ManualLabelPage.ts`
- `/Users/madan/Documents/Fed-Ex-automation/fedex-test-automation/src/pages/app/ManualLabelPage/SideDockConfig.ts`
- `/Users/madan/Documents/Fed-Ex-automation/fedex-test-automation/src/pages/app/settings/internationalShippingSettingsPage.ts`
- `/Users/madan/Documents/Fed-Ex-automation/fedex-test-automation/src/pages/basePage.ts`
- `/Users/madan/Documents/Fed-Ex-automation/fedex-test-automation/tests/label_generation/holdAtLocationLabelGeneration.spec.ts`

Also inspect matching specs or helpers for the current scenario before inventing a new flow. Search the automation repo first with `rg`.

## Supported scenario families

Treat these as first-class supported use cases:

- manual label generation
- auto label generation
- domestic shipments
- international shipments
- shipment purpose / terms / duties / taxes
- hold at location
- insurance
- COD
- signature options
- dangerous goods related flows already supported in the app
  - dry ice
  - alcohol
  - battery
- packaging settings
  - base packaging setup
  - more settings / advanced packaging
- pickup request creation and verification
- return label flows
- bulk label generation
- order grid / order summary / status validation
- request and response log validation
- label / packing slip / commercial invoice verification
- regressions in app navigation, forms, and generated outputs

If a scenario falls inside the FedEx Shopify app domain but does not exactly match a listed example, still handle it by mapping it to the nearest supported flow.

## Execution workflow

### 1. Parse the scenario

Extract:

- label flow: `manual` or `auto`
- order need: `create_new`, `create_bulk`, `existing_unfulfilled`, `existing_fulfilled`, or `none`
- shipping type: domestic, international, Canada, UK
- setup needs: products, settings, side dock options, packaging, pickup, return label, docs, logs
- evidence type needed: UI, request JSON, response JSON, ZIP, PDF, rate log, badge, toast

Use the rules already documented in `AGENTS.md`. Do not re-invent classification logic.

If the user provides only a plain-language scenario, still classify it into the existing project categories before acting.

### 2. Reuse existing knowledge before acting

If the scenario resembles an existing automated flow, inspect the related spec or page object first and mirror its sequence.

Examples:

- `Hold at Location` and request-log validation:
  - follow the same `More Actions -> How To -> Click Here` flow used in the existing automation
- Shipment purpose override:
  - prefer exact combobox labels
  - use the same side dock flow already proven in automation
- Settings navigation:
  - prefer direct app routes or section-local actions over broad sidebar assumptions

For broader flows, also reuse the project’s known patterns for:

- order creation and address inference
- packaging setup and cleanup
- side dock preparation before generation
- request/response ZIP verification
- print-document PDF verification
- return-label generation
- bulk workflow completion polling

### 3. Drive the real app

When verifying in Chrome:

1. Observe the current browser state first.
2. Confirm whether the app content is inside the Shopify app iframe.
3. Use the already known app flow:
   - manual label: order -> generate label -> side dock -> rates -> generate
   - auto label: order -> auto-generate label -> order summary
   - settings: direct settings route or section-local action
4. Prefer stable, visible UI signals:
   - headings
   - exact combobox labels
   - action buttons
   - badge text like `label generated`
5. After each meaningful action, verify the app actually moved to the next expected state.

### 4. Choose the right verification strategy

Use the lightest strategy that proves the requirement:

1. UI badge or visible state
2. Download documents ZIP for physical docs
3. `More Actions -> How To -> Click Here` for request/response JSON
4. Manual-label view logs for pre-generation rate validation
5. `Print Documents` for PDF text checks

Do not use PDF text when the needed truth exists only in request JSON.
Do not use request JSON when a simple visible badge is enough.

When a scenario requires multiple proofs, combine them in this order:

1. visible app result
2. generated document or summary evidence
3. request/response payload evidence

## Lessons from the shipment-purpose debugging

Carry these forward without the user re-explaining them:

### Navigation

- Do not assume a broad app-shell click lands on the correct settings sub-surface.
- If automation already uses a direct route or section-local action, prefer that.
- For long settings pages, scroll the target section into view before asserting.

### Side dock selectors

- Prefer exact accessible labels for comboboxes.
- Avoid broad `div` filtering when a label maps to multiple selects.
- Example class of fix: `Purpose Of Shipment To be used in Commercial Invoice` is better than a partial text container match.

### How To -> Click Here log downloads

- This flow is shared. Do not build a one-off path per test.
- Use the same shared modal flow used by working tests.
- Scroll the `How To` modal until `Click Here` is truly visible.
- Force click only when the visible button is present but the UI layer is finicky.
- Capture download through the shared helper pattern before deciding the flow is broken.

### Browser-debug mindset

- If another spec already works, compare the sequence and helper usage before changing locators.
- If a click appears correct but no file appears, question event timing and helper sequencing, not just the locator text.
- Reuse existing passing automation as the first debugging reference.

## Novel scenarios

If the scenario is new and not clearly covered:

1. Use the closest matching pattern from `AGENTS.md`.
2. Verify the scenario in the real app.
3. Report what was reused, what was new, and what was learned.
4. Propose the durable update that should be added to project knowledge.

When new durable knowledge is discovered, capture it in one of these forms:

- update `AGENTS.md` if it is a stable project rule, architecture detail, or known issue fix
- update the relevant verifier logic if the project behavior must change
- add a short “knowledge update plan” in the response if the user has not yet asked for code changes

Do not silently write broad knowledge changes unrelated to the task.

For genuinely new scenarios, the skill should still try to:

- classify the scenario
- choose the nearest proven FedEx app flow
- execute in browser
- gather evidence
- explain what is new versus what was reused
- suggest the minimum durable project update

## Result format

When giving the user the result of a live verification, include:

1. Verdict: `Pass`, `Fail`, or `Blocked`
2. What was verified
3. Evidence used
4. If failed: exact stuck point and best next fix
5. If new learning was found: a short “Knowledge update” note

Keep it concise. The user prefers direct outcomes over long theory.

## When to update project knowledge

If the user asks to make the learning permanent, update the relevant project file with the minimum durable change:

- `AGENTS.md` for workflow knowledge
- verifier code for runtime logic
- related docs or helper modules for repeatable patterns

If the finding belongs in the knowledge base but not yet in repo text, recommend the next action clearly:

- update `AGENTS.md`
- add a new test or helper
- run the ingest/update flow later so the RAG reflects the new behavior

## Avoid these mistakes

- Do not treat Shopify admin navigation and app iframe navigation as the same thing.
- Do not invent a second flow when an existing automation flow already works.
- Do not default to broad locators when exact labels exist.
- Do not claim a fix is complete unless the scenario was rerun or the evidence clearly proves it.
- Do not overwrite env-driven path behavior with hardcoded fallbacks.
- Do not assume the skill is only for shipment-purpose or label-log bugs; it must support the full FedEx QA domain.
