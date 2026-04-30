---
name: fedex-ai-qa-testcase-prep
description: Use when working inside the FedexDomainExpert project and the user gives a Trello card link, card id, feature request, AC draft, or story description and wants detailed browser-testable test cases prepared first using the card description, comments, project documentation, codebase, automation patterns, and Domain Expert knowledge before Chrome verification.
---

# FedEx AI QA Testcase Prep

Use this skill when the user wants strong, detailed test cases before browser testing.

This skill is the preparation companion to:

- `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/skills/fedex-ai-qa-browser/SKILL.md`

Use this skill first when the input is:

- a Trello card link
- a Trello card id
- a feature request
- a story description
- an AC draft
- an incomplete or weak test case request

## Goal

Given a Trello card or feature request, produce detailed, browser-testable test cases that are easy to verify in the Codex app using Chrome like a human tester.

The output should be good enough that the next session can take the test case and directly verify it using the FedEx browser QA skill.

## First reads

Before generating test cases:

1. Read `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/AGENTS.md`.
2. Read only the directly relevant project files:
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/card_processor.py`
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/trello_client.py`
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/smart_ac_verifier.py`
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/ui/pipeline_dashboard.py`
3. Treat these as the source of truth for:
   - AC and TC generation style
   - browser-verifiable scenario selection
   - Trello card data access
   - AI QA testability rules

Also use the automation repo as a verification-design reference:

- `/Users/madan/Documents/Fed-Ex-automation/fedex-test-automation`

Search that repo for similar scenarios before inventing new test structure.

## Required inputs

Best input:

- Trello card link or card id

Acceptable fallback input:

- raw feature text
- AC text
- user story text
- bug description

If the user gives a Trello card link or id, prefer the real card content over guesswork.

## What to use from Trello

When a Trello card is provided, collect:

- card title
- card description
- comments
- checklists
- attachments or linked implementation context if clearly relevant

Use comments as important context, not noise. Developer comments often contain hidden constraints, rollout notes, or missing acceptance details.

## What to use from project knowledge

Ground the test cases in:

- `AGENTS.md`
- current verifier behavior in `pipeline/smart_ac_verifier.py`
- AC/TC generation rules already implemented in `pipeline/card_processor.py`
- existing FedEx Shopify app automation patterns
- known app architecture:
  - Shopify outside iframe
  - FedEx app inside iframe
  - manual vs auto label flow
  - side dock vs settings vs order grid vs storefront differences

## What “good” test cases look like

The test cases must be:

- browser-verifiable
- detailed enough for human-like Chrome testing
- grounded in the real app flow
- separated by scenario, not mixed together
- clear about setup, action, and expected result
- clear about what evidence is needed

Prefer cases that can be verified by one or more of these evidence types:

1. visible UI state
2. order summary / grid status
3. request or response payload
4. rate log
5. downloaded ZIP content
6. printed PDF / commercial invoice text

## Output requirements

Write test cases in a detailed step style that makes the next verification easy.

For each test case, include:

- `TC ID`
- `Title`
- `Type`: positive, negative, edge, regression, or settings
- `Priority`
- `Execution Flow`: `manual` or `auto` when applicable
- `Preconditions`
- `Steps`
- `Expected Result`
- `Preferred Evidence`

Preferred step style:

1. Navigate to the correct app surface
2. Perform the exact action
3. Verify the expected result
4. Note the best evidence source if UI alone is not enough

## Generation rules

### 1. Produce browser-testable cases first

Favor cases that can really be verified in the live Shopify admin / FedEx app browser flow.

Do not generate test cases that require backend mocking, mobile layouts, or non-supported environments unless the user explicitly asks for them.

### 2. Pick the right flow

Decide whether each case belongs to:

- manual label flow
- auto label flow
- settings flow
- order-grid flow
- product admin flow
- packaging flow
- pickup flow
- return-label flow
- storefront checkout flow

If a case cannot be verified from the browser alone, say so inside the case and prefer the nearest browser-verifiable variant.

### 3. Make evidence explicit

Do not stop at “label generated successfully” if the real proof should be:

- request payload
- rate log
- How To → Click Here ZIP
- Download Documents ZIP
- Print Documents PDF text

### 4. Reuse known project patterns

Examples:

- shipment-purpose override:
  - global setting first
  - per-order override second
  - payload proof required
- HAL / insurance / signature:
  - manual label side dock
- commercial invoice:
  - international only
  - PDF or document bundle evidence
- order grid:
  - search/filter/status-tab cases
- packaging:
  - base settings save
  - more settings for advanced options

### 5. Keep setup realistic

Use the same order-creation logic the project already understands:

- `create_new`
- `create_bulk`
- `existing_unfulfilled`
- `existing_fulfilled`
- `none`

Where useful, make the preconditions explicit in human terms:

- create a fresh international order
- use an existing labeled order
- enable Dry Ice in App Products first
- save the global settings before testing the override

## Preferred workflow

### If the user gives a Trello card link

1. Extract the card id from the link.
2. Read the card using project Trello logic.
3. Collect description, comments, and checklists.
4. Classify the feature area.
5. Search the codebase and automation for similar flows.
6. Generate detailed test cases.
7. If useful, point out which cases are best for immediate Chrome verification.

### If the user gives only story text

1. Infer likely flow family.
2. Search the automation repo for the closest existing scenario.
3. Generate browser-verifiable test cases in the same style.

## Case design guidance

Prefer:

- one clear behavior per test case
- explicit restore/cleanup note if the scenario changes global settings
- one evidence strategy per case unless multiple proofs are required

Avoid:

- combining settings change, order creation, label generation, and document validation into one giant case unless the feature truly requires that
- vague expected results like “works correctly”
- cases that are impossible to verify from the browser

## Handoff to browser verification

When finishing, make the test cases easy for the browser QA skill to consume.

If helpful, end with a short mapping like:

- `Best first case to verify`
- `Needs manual label flow`
- `Needs international order`
- `Needs request ZIP proof`
- `Needs PDF / CI proof`

## If something new is discovered

If the card reveals a new flow, new field, or new verification pattern:

1. Generate the test case anyway.
2. Call out the new pattern briefly.
3. Recommend adding the learned pattern back into:
   - `AGENTS.md`
   - `pipeline/smart_ac_verifier.py`
   - the browser QA skill if needed

## Final standard

The user should not need to explain the scenario twice.

If they give a Trello card and ask to test it, this skill should:

1. turn the card into strong detailed test cases
2. make the cases directly usable for Chrome verification
3. align the case structure with the existing Domain Expert project and automation knowledge
