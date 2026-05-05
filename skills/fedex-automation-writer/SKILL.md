---
name: fedex-automation-writer
description: Use when working inside the FedexDomainExpert project after US/AC generation, dashboard TC generation, and AI QA browser verification are complete, and the user wants Playwright TypeScript automation written for a FedEx Shopify card. Reuse dashboard automation_writer/chrome_agent conventions, inspect Chrome manually for DOM/locators, reuse existing automation locators/POM methods first, create new locators only when missing, and use saved AI QA locator traces by card id/name when available.
---

# FedEx Automation Writer

Use this skill for the final automation stage in the Codex/Claude skill pipeline:

1. `fedex-ac-writer-reviewer` generates reviewed US + AC.
2. `fedex-dashboard-tc-publisher` generates dashboard TCs and publish formats.
3. `fedex-ai-qa-browser` verifies selected TCs in the browser and captures evidence/locators.
4. `fedex-automation-writer` creates or updates Playwright automation in the automation repo.
5. `fedex-knowledge-maintainer` records durable automation/QA learning after the cycle is approved.

This skill mirrors the dashboard `Generate Automation Script` behavior while using Codex/Claude app tools.

## First Reads

Before writing automation:

1. Read `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/AGENTS.md`.
2. Read:
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/skills/fedex-automation-writer/references/automation_flow.md`
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/skills/fedex-automation-writer/references/locator_trace_handoff.md`
3. Inspect only directly relevant project files:
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/automation_writer.py`
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/chrome_agent.py`
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/test_runner.py`
4. Inspect the automation repo under `AUTOMATION_CODEBASE_PATH`.

Do not hardcode automation paths. Use `.env` / `config.AUTOMATION_CODEBASE_PATH`.

## Required Inputs

Best input package:

- card name and card id or URL
- reviewed US + AC
- reviewed detailed TCs
- AI QA result/evidence
- saved locator trace from AI QA browser, if available
- any QA notes/test data

If AI QA has not run yet, ask to run `fedex-ai-qa-browser` first or manually inspect Chrome before writing automation.

## Core Rules

- Open/use Chrome manually with Computer Use when locator or DOM certainty is needed.
- Reuse existing automation POMs, locators, and helper methods first.
- Do not duplicate an existing locator/method under a new name.
- If an existing locator is present but weak, prefer adding a small helper method around it instead of replacing old code.
- Create new locators only when no suitable existing locator/method exists.
- Append to existing POMs; do not rewrite/remove existing code.
- Always create a separate new spec file for the card.
- For a new page, create a new POM and update fixtures only when no existing POM fits.
- Follow the automation repo's actual style, imports, naming, fixtures, and folder structure.
- Keep automation focused on Positive and UI-safe Edge cases. Negative backend/API-mocking cases usually stay manual.

## Locator Trace Handoff

Before generating code, look for saved traces under:

```text
data/ai_qa_locator_traces/
```

Search by card id first, then slugified card name.

If no saved trace exists:

1. Use Computer Use to open the browser and manually execute the same flow.
2. Capture visible headings/buttons/labels/inputs/toggles and iframe context.
3. Save the trace using:
   `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/skills/fedex-automation-writer/scripts/save_locator_trace.py`

The automation writer should use locator traces as supporting evidence, not blindly. Existing POM methods still win.

## Generation Workflow

1. Parse card + TC scope.
2. Filter automatable cases:
   - keep strongest Positive cases
   - keep UI-safe Edge case if useful
   - skip backend-mocking or unsafe Negative cases
3. Find existing POM by registry/keywords and repo search.
4. Search automation repo for matching specs/page objects:
   - `rg "<feature keyword>" $AUTOMATION_CODEBASE_PATH`
   - inspect POMs/specs before creating anything
5. Open Chrome manually or use saved locator trace to confirm DOM and exact labels.
6. Decide:
   - existing POM append + new spec
   - new POM + fixture update + new spec
7. Edit files in automation repo following existing style.
8. Review generated code against project rules.
9. Run targeted Playwright test if user asks or if safe/available.
10. Report files changed, test result, and any manual follow-up.

## Code Style Must Match

Spec rules:

- import `test` and `expect` from the repo fixtures path, not directly from `@playwright/test`
- `test.describe.configure({ mode: 'serial' })`
- order creation is a dedicated `test('Create an order from API', ...)` block when needed
- `const store = process.env.STORE; if (!store) throw ...`
- every test has at least one meaningful `expect`
- no `test.only`
- no `waitForTimeout` over 3000
- business assertions beat weak visibility checks

POM rules:

- POMs extend `BasePage`
- locators are readonly class properties
- app iframe locators use `this.appFrame`
- Shopify admin locators use `this.page`
- new locator groups are appended and commented with the card name
- action methods are appended after existing methods
- prefer role/label/text locators grounded in actual DOM/trace

## Safety

- Do not write into the FedexDomainExpert repo when the task is automation code; write into `AUTOMATION_CODEBASE_PATH`.
- Do not change unrelated automation files.
- Do not rewrite fixtures unless adding a genuinely new POM.
- Do not push/commit unless the user asks.
- Do not run destructive git commands.

## Result Format

Return:

- automation decision: existing POM or new POM
- trace used: saved trace / manual Chrome inspection / none
- files changed
- cases automated and cases skipped
- test command run and result, if any
- follow-up needed
- knowledge-maintainer note if a locator, helper, or flow pattern should become durable project knowledge
