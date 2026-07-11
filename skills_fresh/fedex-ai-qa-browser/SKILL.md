---
name: fedex-ai-qa-browser
description: Use when working inside the FedexDomainExpert project to verify dashboard-generated FedEx Shopify app test cases in a real browser with Computer Use, following the same AI QA Verifier knowledge as the dashboard — parse TC metadata, reuse automation/codebase/domain knowledge before navigating, safely drive Shopify and FedEx app flows, ask QA only when truly blocked, and return pass/fail evidence without breaking the current store or app state.
---

# FedEx AI QA Browser Verifier

Execute prepared test cases against the live Shopify admin + embedded FedEx app using a real
browser (Computer Use), and return pass/fail with evidence.

## First reads
1. Use `fedex-domain-core` for app structure and expected behavior.
2. Use `fedex-shopify-store-actions` to create/find the orders a TC needs.
3. Know the iframe model: app sidebar (Shipping, Settings, Products, PickUp, Rates Log) lives
   INSIDE `iframe[name="app-iframe"]`; Shopify Orders/Products live OUTSIDE it.

## Inputs
- One or more prepared test cases (ideally from `fedex-ai-qa-testcase-prep`) with order decision,
  preconditions, steps, and evidence strategy.

## Steps
1. Parse TC metadata (id, type, order decision, execution flow, evidence strategy).
2. Resolve preconditions (product flags, settings, order setup) deterministically first.
3. Drive the flow: manual vs auto label launch, sidedock config, settings, manifest, etc.
4. Capture evidence using the right strategy (label badge, Download Documents ZIP,
   How To → request/response JSON, Rates Log, Print Documents codes).
5. Summarize raw payloads into compact business facts before judging.
6. Return a verdict: **pass / fail / partial** with the supporting evidence.

## Rules
- Never corrupt store/app state; reset any toggles you changed.
- Use deterministic orchestration where flows are known; fall back to the agentic loop only when needed.
- Ask QA a specific question only when genuinely blocked — never guess a destructive action.
- Honor stop requests at the next safe checkpoint.

## Output
Per-TC verdict (pass/fail/partial) + evidence (JSON facts, screenshots, document codes), ready
for bug review or sign-off.
