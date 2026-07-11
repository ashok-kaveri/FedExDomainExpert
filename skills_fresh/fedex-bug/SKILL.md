---
name: fedex-bug
description: Use when working inside the FedexDomainExpert project and QA reports a bug during AI QA, browser, or manual testing and wants it formatted, checked against existing Trello Backlog cards, and created in the Trello Backlog list. Mirrors the dashboard Bug Reporter flow — plain-English QA issue to Jira-style bug draft to duplicate check to Backlog card creation after approval.
---

# FedEx Bug Reporter

Turn a plain-English QA issue into a structured bug, check for duplicates, and create it in the
Trello Backlog list — mirroring the dashboard Bug Reporter.

## First reads
1. Use `fedex-domain-core` to confirm expected vs actual behavior when unclear.
2. Use `fedex-trello-operator` to search the Backlog and to create the card.

## Inputs
- A plain-English description of the bug (ideally with steps, evidence, environment).

## Steps
1. Draft a **Jira-style bug**: title, environment, steps to reproduce, expected, actual, severity,
   evidence/attachments.
2. **Duplicate check** — search existing Backlog cards; if a likely duplicate exists, surface it
   and ask before creating a new one.
3. On approval, create the card in the **Backlog** list via `fedex-trello-operator`, with
   appropriate labels/severity.

## Rules
- Always run the duplicate check before creating.
- Never create the card without explicit approval.
- Keep severity honest and evidence concrete.

## Output
The bug draft, duplicate-check result, and (after approval) the created Backlog card link.
