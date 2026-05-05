---
name: fedex-handoff-docs
description: Use when working inside the FedexDomainExpert project after cards are approved and the user wants professional release handoff documents like the dashboard Handoff Docs tab: Support Guide, Business Brief, or both, generated from approved US/AC, TCs, AI QA evidence, release/card metadata, toggles, and member ownership. If the user requests only one document, generate only that document and PDF.
---

# FedEx Handoff Docs

Use this skill to generate professional handoff documents for approved FedEx Shopify app release cards.

It mirrors the dashboard `Handoff Docs` tab:

- Support Guide
- Business Brief
- Markdown + PDF output
- Trello/Slack-ready artifacts when requested

If the user asks for only one document, generate only that document. Do not generate both by default.

## First Reads

Before generating:

1. Read `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/AGENTS.md`.
2. Read:
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/skills/fedex-handoff-docs/references/handoff_doc_formats.md`
3. Inspect only directly relevant project files:
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/handoff_docs.py`
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/ui/pipeline_dashboard.py`

Use `fedex-domain-core` research when local context is incomplete or customer-facing explanations need current FedEx/PluginHive/Shopify facts.
Use `fedex-trello-operator` to fetch card details/members or attach/comment PDFs when explicitly requested.
Use `fedex-slack-operator` to send PDFs or messages to Slack when explicitly requested.

## Inputs

Best input package:

- card name/id/url
- release name
- approved US + AC
- reviewed TCs
- AI QA summary/evidence
- support sign-off notes
- developed by / tested by
- toggles/prerequisites
- known limitations
- rollout notes

If some inputs are missing, still generate a useful draft, but mark unknown fields clearly. Do not invent ownership, release numbers, toggles, or unsupported limitations.

## Document Selection

Generate based on user request:

- "support guide", "support doc", "demo doc", "customer support explanation" -> Support Guide only
- "business brief", "business doc", "stakeholder doc", "marketing/sales summary" -> Business Brief only
- "handoff docs", "both docs", "support and business" -> both

If unclear, ask which one: Support Guide, Business Brief, or both.

## Support Guide Purpose

The Support Guide is for support/demo teams who need to understand the feature well enough to explain it to customers.

It must be practical, professional, and support-friendly:

- explain what changed
- explain where support can see it
- explain what the merchant should experience
- include walkthrough steps
- include customer-safe explanation
- include troubleshooting questions
- include toggles/prerequisites
- include developed by / tested by

Do not write vague release notes. This should be a real support enablement document.

## Business Brief Purpose

The Business Brief is for non-technical stakeholders: product, sales, marketing, account managers.

It must:

- stay under about 400 words unless user asks otherwise
- use plain business English
- avoid technical terms
- omit developed by / tested by
- omit QA notes and test counts
- mention toggle/availability only if the merchant or rollout team must do something

## PDF Generation

When the user asks for PDF:

1. Generate the markdown first.
2. Save the markdown under `data/handoff_docs/`.
3. Render PDF using:
   `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/skills/fedex-handoff-docs/scripts/render_handoff_pdf.py`

For one requested document, create only one PDF.

For both, create two PDFs unless the user explicitly asks for a combined release package.

## Support Guide Structure

Follow the sample release support guide style:

```markdown
# Support Guide - <Feature/Card Name>

## Release Details
- Feature Reference:
- Trello:
- App Release:
- Approved:
- Developed by:
- Tested by:

## Feature Summary
...

## Toggles & Prerequisites
...

## Where to Find This in the App
...

## Step-by-Step Walkthrough (Support / Demo)
### Scenario A - ...
1. ...
2. ...

## Expected Behaviour - What Support Should Observe
...

## Business-Safe Explanation (For Merchant-Facing Communication)
...

## Common Questions & Troubleshooting
**Q: ...**
...

## Known Limitations / Rollout Notes
...

## References
...
```

## Quality Bar

Before finalizing:

- make it understandable for support people
- remove internal/code jargon unless necessary
- keep merchant-facing wording safe and clear
- do not expose implementation details that customers do not need
- verify every claim comes from card/AC/TC/AI QA evidence or researched domain facts
- keep the support guide thorough enough for a support call
- keep the business brief short and polished

## Final Response

Return:

- document(s) generated
- markdown path if saved
- PDF path if rendered
- any missing inputs or assumptions

Use absolute file paths in final responses.
