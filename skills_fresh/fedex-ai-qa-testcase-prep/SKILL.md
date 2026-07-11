---
name: fedex-ai-qa-testcase-prep
description: Use when working inside the FedexDomainExpert project and the user gives a Trello card link, card id, feature request, AC draft, or story and wants full, detailed, browser-testable test cases prepared specifically for the AI QA Agent / Chrome verification, using the same FedEx Domain Expert rules, evidence strategies, and automation-flow knowledge as the dashboard. Do not use for compact Trello comments, CSV rows, or Google Sheet formats — use fedex-dashboard-tc-publisher for those.
---

# FedEx AI QA Test Case Prep

Produce **detailed, browser-executable** test cases designed for the AI QA Agent (Chrome /
Computer Use) to run against the real Shopify + FedEx app.

## First reads
1. Use `fedex-domain-core` for exact app flows, routes, and expected behavior.
2. Reuse the project's known navigation map and the five evidence strategies (label badge,
   download documents ZIP, request/response JSON, rate logs, printed-document codes).

## Inputs
- Trello card (id/URL), feature request, AC draft, or story description.

## Steps
1. Parse the feature into discrete, verifiable test cases.
2. For each TC, write explicit browser steps: navigate → set up order/settings → act → verify.
3. Specify the **order decision** (create_new / create_bulk / existing_fulfilled /
   existing_unfulfilled / none) and any preconditions/cleanup.
4. Specify the **evidence strategy** and exact pass/fail signal for each verification.
5. Mark each TC's execution flow as `manual` or `auto` (internal metadata).

## Rules
- Steps must be concrete enough for a browser agent to execute without guessing.
- Never break or pollute existing store/app state — use safe test data.
- Reuse automation/codebase/domain knowledge before describing any navigation.

## Output
A set of detailed, browser-testable TCs (with preconditions, steps, evidence strategy, and
expected result) ready to feed `fedex-ai-qa-browser`.
