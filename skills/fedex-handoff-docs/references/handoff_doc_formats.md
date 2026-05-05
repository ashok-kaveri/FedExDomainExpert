# Handoff Document Formats

This reference is based on:

- `pipeline/handoff_docs.py`
- dashboard `Handoff Docs` tab
- sample release package `FedEx118_ReleaseCards.pdf`

## Sample Support Guide Style

The attached release package uses:

- branded PluginHive / Shopify FedEx Shipping App release header
- release version and date
- card-by-card sections
- support guide label
- release details
- feature summary
- toggles and prerequisites
- where to find the feature
- support/demo walkthrough
- expected behavior
- business-safe customer explanation
- common questions and troubleshooting

Support guide examples from the sample:

- explain background silently operating fixes clearly
- state if no toggle is required
- specify scope such as international-only or domestic-only
- give concrete scenarios with expected support observations
- include merchant-facing explanation in quoted/plain language
- include Q&A for likely support tickets

## Support Guide Tone

Professional, practical, support-ready.

Audience:

- support team
- demo team
- implementation/support leads

The support reader should be able to explain the feature to a merchant without asking engineering.

Use:

- clear feature summary
- concrete paths and steps
- "what support should observe"
- "what to tell the merchant"
- "what to check if it fails"

Avoid:

- deep code/internal implementation details
- vague "works correctly" wording
- unsupported claims
- excessive QA/test-count language

## Support Guide Required Sections

```markdown
# Support Guide - <Feature/Card Name>

## Release Details
- Feature Reference: <id if known>
- Trello: <url if known>
- App Release: <release>
- Approved: <date>
- Developed by: <names or Unknown>
- Tested by: <names or QA Team>

## Feature Summary
2-4 paragraphs.

## Toggles & Prerequisites
State whether a feature toggle is required.
List prerequisites and scope.

## Where to Find This in the App
Give app path or explain if behavior is background-only.

## Step-by-Step Walkthrough (Support / Demo)
Use Scenario A/B/C when useful.

## Expected Behaviour - What Support Should Observe
Summarize the key signal.

## Business-Safe Explanation (For Merchant-Facing Communication)
Use customer-safe wording.

## Common Questions & Troubleshooting
Use Q/A format.

## Known Limitations / Rollout Notes
Mention open questions or limitations only if supported.

## References
Trello/card/source links.
```

## Business Brief Required Structure

```markdown
## <Feature Name in Plain English>
*One sentence headline value.*

---

### The Problem
2-3 sentences.

---

### What's New
- 3-5 bullets.

---

### Who Benefits
2-3 merchant/support scenarios.

---

### Why It Matters
2-3 sentences.

---

### Availability
One line.
```

Rules:

- max about 400 words
- plain business English
- no developer/tester attribution
- no QA notes
- no internal Trello links in body
- no technical terms unless impossible to avoid
- no toggle detail unless merchant/rollout must act

## PDF Rendering

Use `pipeline.handoff_docs.render_pdf_bytes` through the skill helper script. This gives the same polished dashboard PDF styling.

If rendering a release package with many cards, create individual PDFs unless the user asks for a combined package.

