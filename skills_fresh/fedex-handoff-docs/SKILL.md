---
name: fedex-handoff-docs
description: Use when working inside the FedexDomainExpert project after cards are approved and the user wants professional release handoff documents like the dashboard Handoff Docs tab — Support Guide, Business Brief, or both — generated from approved US/AC, TCs, AI QA evidence, release and card metadata, toggles, and member ownership. If the user requests only one document, generate only that document and its PDF.
---

# FedEx Handoff Docs

Generate professional release handoff documents for approved FedEx Shopify cards: a
**Support Guide** (support/demo team) and/or a **Business Brief** (non-technical stakeholders),
each as markdown + PDF.

## First reads (REQUIRED)
1. Use `fedex-trello-operator` to fetch card details, members, and approval metadata.
2. Use `fedex-domain-core` for accurate app navigation, button names, and expected behavior.
3. For "Where to Find" and "Walkthrough" sections, use the known app navigation map — do NOT
   infer UI steps from AC text.

## Inputs
- Approved card(s): US/AC, reviewed TCs, AI QA summary/evidence, release name, toggles, members.

## Steps
1. Build a context object per card (description, AC, TCs, QA evidence, toggles, ownership).
2. **Support Guide** — title + Trello link, feature summary, toggles/prerequisites, where to find,
   step-by-step walkthrough, expected behavior. (Per current project rules, omit Developed/Tested
   By, Business-Safe Explanation, Common Questions/Troubleshooting, and Known Limitations.)
3. **Business Brief** — plain-English value: problem, what's new, who benefits, why it matters,
   availability. No QA/dev attribution, no jargon.
4. Render markdown → PDF. For multi-card releases, combine into one document with a cover/TOC.
5. On request, attach the PDF to Trello or upload to Slack (channel or DM) after explicit approval.

## Rules
- Generate only the document(s) the user asked for — do not default to both.
- Use only facts from context; mark unknowns rather than inventing release numbers/toggles.
- Do not emit "QA NOTE / Navigation Confirmation Needed" blocks; write the best supportable steps.

## Output
The requested handoff document(s) as markdown + branded PDF, ready to share.
