---
name: fedex-ac-writer-reviewer
description: Use when working inside the FedexDomainExpert project and the user gives a Trello card, feature request, bug or customer issue, PR note, or rough requirement and wants a dashboard-style User Story plus Acceptance Criteria generated, reviewed, rewritten, checked for toggle prerequisites, and prepared for Trello comment posting. Generation and review only — does not run AI QA or write test cases.
---

# FedEx AC Writer & Reviewer

Turn a raw card or request into a clean, dashboard-style **User Story + Acceptance Criteria**,
review it, and prepare it for posting back to Trello.

## First reads (REQUIRED)
1. Use `fedex-domain-core` for any app/carrier facts the AC depends on.
2. Use `fedex-trello-operator` to fetch the card description, comments, and attachments when a
   card id/URL is given.

## Inputs
- A Trello card (id/URL), feature request, bug report, PR note, or freeform requirement.
- Optional: related backlog cards, PR/code references, customer/Zendesk context.

## Steps
1. **Research first** — pull card text, related backlog cards, PR/code refs, wiki, and customer
   issues via `fedex-domain-core`. Do not write AC from the title alone.
2. **Draft the User Story** — "As a <role>, I want <capability>, so that <value>."
3. **Draft Acceptance Criteria** — numbered, testable, covering happy path, edge cases, and
   negative cases. Each criterion must be independently verifiable.
4. **Toggle / prerequisite check** — detect any feature flag, setting, or store precondition the
   feature needs, and call it out explicitly.
5. **Review pass** — critique the draft for gaps, ambiguity, and untestable wording; auto-rewrite
   weak output and surface the review findings.
6. **Prepare for Trello** — format as a comment-ready markdown block. Post only with explicit
   user approval via `fedex-trello-operator`.

## Rules
- Use only facts from research; never invent API fields, routes, or toggles.
- AC must be testable — no vague verbs like "should work properly".
- Keep US/AC in the project's dashboard format.

## Output
US + AC markdown, the review findings, detected toggles, and a comment-ready block.
With explicit approval and Slack credentials, can send the standard toggle-enable DM to the
designated owner via `fedex-slack-operator`.
