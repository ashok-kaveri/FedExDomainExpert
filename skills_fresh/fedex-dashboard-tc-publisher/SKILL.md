---
name: fedex-dashboard-tc-publisher
description: Use when working inside the FedexDomainExpert project and the user already has a User Story plus Acceptance Criteria and now wants dashboard-style QA test cases generated from that US/AC, in the two dashboard publish formats — compact Trello QA comment and positive-case CSV rows for the Ai sheet tab. Generation-only; must not call Trello, Google Sheets, Slack, Shopify, or project LLM APIs directly. For detailed browser-executable test cases, use fedex-ai-qa-testcase-prep instead.
---

# FedEx Dashboard TC Publisher

Generate QA test cases from approved US/AC in the two formats the dashboard publishes:
a **compact Trello QA comment** and **positive-case CSV rows** for the "Ai" sheet tab.

## First reads
1. Use `fedex-domain-core` for app flows, expected behavior, and field-level detail.
2. Reuse known app navigation and evidence strategies when describing steps.

## Inputs
- Approved User Story + Acceptance Criteria (required).
- Optional: card metadata, related flows.

## Steps
1. Derive test cases from each acceptance criterion — cover positive paths primarily, plus key
   edge/negative cases where the AC calls for them.
2. **Trello comment format** — compact, scannable: TC id, title, type, priority, short steps.
3. **CSV format** — positive-case rows matching the "Ai" sheet columns exactly.
4. Keep any internal execution-flow metadata (manual/auto) out of both published formats.

## Rules
- **Generation only.** Do NOT call Trello, Google Sheets, Slack, Shopify, or LLM APIs from here.
- Do not include internal-only fields in the published output.
- Match the dashboard's exact column order and comment layout.

## Output
Two artifacts: the compact Trello QA comment block and the positive-case CSV rows.
Hand off to `fedex-trello-operator` / the sheet publisher only when the user explicitly asks to post.
