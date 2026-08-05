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

## First Reads (REQUIRED — do not skip)

1. Read the handoff doc formats reference — it contains the complete app navigation map, exact button names, step-by-step templates, and document formats:
   `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/skills/fedex-handoff-docs/references/handoff_doc_formats.md`
2. Use `fedex-trello-operator` to fetch card details/members when a card ID/URL is provided.
3. Use `fedex-domain-core` when customer-facing explanations need current FedEx/PluginHive facts.

**CRITICAL RULE**: For "Where to Find This in the App" and "Step-by-Step Walkthrough" sections, use ONLY the exact routes, button names, and step sequences from the `APP NAVIGATION MAP` in the reference file. Do NOT infer navigation paths from AC text — the AC rarely describes exact UI steps.

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

- open with a crisp `Brief Description` of what changed
- explain where support can see it
- explain what the merchant should experience
- include walkthrough steps
- include toggles/prerequisites
- include developed by / tested by

For a multi-card release package, include an Index Page with exactly these columns: "Story ID", "Story Title", "Toggle Name", "Trello card link".

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

## Brief Description
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
```

Do not add `Business-Safe Explanation`, `Merchant-Safe Explanation`, `Common Questions & Troubleshooting`, `Support Escalation Packet`, `Known Limitations / Rollout Notes`, or `References` sections. The document ends after `Expected Behaviour`.

## Multi-Card Release Package Structure

When the user asks for a combined release package, start with the index page and go straight into the card sections:

```markdown
# <Release> Support Guide

## Included Story Cards
| Story ID | Story Title | Toggle Name | Trello card link |
|---|---|---|---|

## <Story ID> - <Card title>
### Brief Description
...
```

Index page rules:

- use exactly four columns: `Story ID`, `Story Title`, `Toggle Name`, `Trello card link`
- `Story ID` is the story/card number only
- `Story Title` is the card title
- `Toggle Name` is the exact toggle name, or `None` when the card needs no toggle
- `Trello card link` is a markdown link to the card, labelled with the story id, for example `[941](https://trello.com/c/abc123)`; use `-` when no card URL is known

Do not add a `How Support Should Use This Package` section. The index page is followed directly by the first card section.

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
