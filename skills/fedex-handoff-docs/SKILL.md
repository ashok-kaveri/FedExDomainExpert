---
name: fedex-handoff-docs
description: Use when working inside the FedexDomainExpert project after cards are approved and the user wants professional release handoff documents like the dashboard Handoff Docs tab: Support Guide, Business Brief, or both, generated from approved US/AC, TCs, AI QA evidence, release/card metadata, toggles, and member ownership. If the user requests only one document, generate only that document and PDF.
---

# FedEx Handoff Docs

Use this skill to generate professional handoff documents for approved PluginHive FedEx Shopify app release cards.

It mirrors the dashboard `Handoff Docs` tab:

- Combined release Support Guide
- Combined release Business Brief
- Optional single-card Support Guide / Business Brief for quick review
- Markdown + PDF output
- Trello/Slack-ready artifacts when requested

Default release delivery is one combined PDF per document type. If the user asks for only one document type, generate only that combined document. Use single-card documents only when the user explicitly asks for one card.

## First Reads

Before generating:

1. Read `AGENTS.md`.
2. Read:
   - `skills/fedex-handoff-docs/references/handoff_doc_formats.md`
3. Inspect only directly relevant project files:
   - `pipeline/handoff_docs.py`
   - `ui/pipeline_dashboard.py`

Use `fedex-domain-core` research when local context is incomplete or customer-facing explanations need current FedEx/PluginHive/Shopify facts.
Use `fedex-trello-operator` to fetch card details/members or attach/comment PDFs when explicitly requested.
Use `fedex-slack-operator` to send PDFs or messages to Slack when explicitly requested.

**CRITICAL RULE**: walkthrough navigation comes from the `APP NAVIGATION MAP` in the reference file, from AI QA evidence, or from the frontend/backend code — never from AC text. The AC rarely describes exact UI steps. A wrong walkthrough is worse than an honest unknown with a clear question.

For release packages, always use full live Trello card context when available: description, comments, labels, attachments/checklist summaries, approved AC/TCs, and AI QA evidence. QA comments often contain late caveats and must not be skipped.

## Excluded Cards

Before anything else, drop cards that are not part of the release story set. Exclude any card carrying one of these labels:

- `SL: ON Hold`
- `SL: Carrier Platform`
- `Spill Over`
- `SL: Closed By Support`

Rules:

- Match labels case-insensitively and tolerate emoji, colour prefixes, and extra spacing around the name.
- Match on the card's Trello **labels**, not on its title. `SL: FDX` and `SL: ZI` are story-id prefixes in card titles and never trigger an exclusion.
- Exclude the card from the index table as well as the body. A card left out of the body but listed in the index reads as a missing section.
- Include an excluded card only when the user names it or explicitly asks for it. Naming the card is the instruction — do not ask again.
- Never drop the card silently. Always report which cards were excluded and which label triggered it, so a short release is visibly deliberate.
- Excluded cards contribute no toggles to the `Toggle List Follow-Up` DM.

Before writing any release package, do a toggle audit for every card:

- Search the whole card for the toggle, not just the description: comments, checklists, attachments, approved AC, TCs, and QA evidence. The exact toggle key is often only in a QA or developer comment.
- Put the exact key in the index table `Toggle Name` column. List every key comma-separated when a card has more than one, and `None` when the card needs no toggle.
- Never guess or reconstruct a toggle key. If the card clearly needs one but no key is stated anywhere, write `Not stated` and flag it in the final response.

Before writing a release Support Guide, do a payload/log audit for every card:

- If the evidence asks support to inspect a carrier request, response, payload, rates log, request/response JSON, tracking payload, report source field, or label document, include the exact node/field name support must verify.
- FedEx request nodes are documented in the reference file, for example `requestedShipment.shipmentSpecialServices.specialServiceTypes` or `requestedShipment.requestedPackageLineItems[0].declaredValue.amount`. Use the exact path.
- Put the callout immediately after the relevant walkthrough step, using one of these exact bullet labels so the PDF renderer highlights it:
  - `Request node to verify: ...`
  - `Request nodes to verify: ...`
  - `Request/response nodes to verify: ...`
  - `Request/log fields to verify: ...`
- Say where the payload comes from when it is not obvious: the rates log dialog during the label flow, or `More Actions -> How To -> Click Here` after the label exists. `Download Documents` has PDFs only.
- Do not add node callouts to UI-only, report-only, sync-only, or performance cards unless card evidence names an actual request/log field.
- If the exact field is unknown after checking card comments/checklists and code/context, say what log to inspect in troubleshooting and do not invent a node name.

Before writing Support Guide or Business Brief content, do a technical-card audit for every card:

- A technical card is one only a developer cares about: an API-only change, a library or version upgrade, a refactor, an internal clean-up, or infrastructure work with nothing support or the merchant can see or do.
- Move every technical card into a single `## Technical Cards` section placed after the last normal card section. Keep each entry to a few lines: what changed and why it matters.
- Keep technical cards in their normal position in the index table — only the body section moves.
- If a card has both a technical part and something support can see or demo, keep it as a normal card.

Before writing Support Guide or Business Brief content, do a scope audit for every card:

- The FedEx app runs embedded in Shopify admin. Shopify is the platform for every card — there is no platform choice to make here.
- Instead, pin the scope axes that actually vary and state them explicitly: domestic vs international, which service types or special services are affected, SOAP vs REST accounts, and whether the change is account-wide or per-product.
- Detect the scope from the title, labels, description, comments, linked ticket, PR notes, AC, TCs, and QA evidence. Do not widen a domestic-only or international-only change into a general one.
- Commercial Invoice appears only for international shipments; domestic US orders have label PDF and packing slip only. Never imply otherwise.

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

- "support guide", "support doc", "demo doc", "customer support explanation" -> combined release Support Guide only
- "business brief", "business doc", "stakeholder doc", "marketing/sales summary" -> combined release Business Brief only
- "handoff docs", "both docs", "support and business" -> both combined release PDFs
- "single card", "only this card", or a specific card id/name -> single-card document for that card

If unclear, ask which one: Support Guide, Business Brief, or both.

## Support Guide Purpose

The Support Guide is for support/demo teams who need to understand the feature well enough to explain it to customers.

It must be practical, professional, and support-friendly and very crisp and do not use any Technical jargon.

Use no technical words anywhere in the body of either document: no code, class, file, or method names, no API or schema jargon, and no internal engineering terms. Write it the way you would explain the feature to someone who has never seen the code. Three places are exempt, because the exact string is the point: the request/log callouts described above, the `Technical Cards` section, and toggle keys in the index table and `Toggles & Prerequisites` tables.

- Include the Index Page with exactly these columns: "Story ID", "Story Title", "Toggle Name", "Trello card link"
- Explain "Brief Feature Summary" in a title called "Brief Description" Keep it very crisp
- include where support can see it inside the relevant walkthrough steps
- explain what the merchant should experience
- include walkthrough steps built from the exact button and link names in the navigation map
- include toggles/prerequisites

Do not write vague release notes. This should be a real support enablement document.

## PDF Generation

When the user asks for PDF:

1. Generate the markdown first.
2. Save the markdown under `data/handoff_docs/`.
3. Render PDF using:
   `skills/fedex-handoff-docs/scripts/render_handoff_pdf.py`

For one requested release document, create one combined PDF containing all selected/approved release cards.

For both, create two combined PDFs: one Support Guide package and one Business Brief package.

## Slack Delivery

Send with `scripts/send_handoff_pdf_to_slack.py`. Nothing is sent without `--yes`, so always dry-run first and show the resolved target.

```bash
# dry run — prints target, filename, size, message text
python3 scripts/send_handoff_pdf_to_slack.py --pdf <pdf path> --title "<doc title>"

# DM to the doc owner (default target)
python3 scripts/send_handoff_pdf_to_slack.py --pdf <pdf path> --title "<doc title>" --yes

# team channel: bare --channel targets qa_members_internal
python3 scripts/send_handoff_pdf_to_slack.py --pdf <pdf path> --title "<doc title>" --channel --yes
```

**When the request already names a destination, that is the approval — do not ask again.**
"DM me the PDF", "send it to me", "share it in #qa-team" all authorise that one send: dry-run,
then send in the same turn, then report the target and file id. Re-sending a corrected version
of a document the user already asked to be sent needs no fresh approval either.

Ask first only when:

- the user asked for a document but named no destination, or
- the send target differs from the one they named — in particular, approval for a DM is never
  approval for a team channel, and vice versa.

Always report the outcome: target, file id on success, or the exact Slack error on failure.

## Toggle List Follow-Up

After a release package is generated, send the consolidated toggle list as a Slack DM to `ashok@pluginhive.com`. This is a standing instruction from the doc owner, so it needs no fresh approval — but always show the message text before sending, then report the result.

Rules:

- Send the toggle list only. Never attach the document to this message; document delivery stays under `Slack Delivery` above.
- Skip the step entirely when no card in the release has a toggle. Say so in the final response instead of sending an empty message.
- Build the list with `fedex-toggle-enable-list`, reusing the `Toggle Name` column of the guide's index table as the source. One line per toggle, in this exact shape:

```
"<shop domain>.<toggle name>": true,
```

- FedEx toggles are keyed by the merchant's Shopify store domain, including the `.myshopify.com` suffix.
- Shape example: `"fedexapp-dg-csp.myshopify.com.fedex.rest.use.comprehensive.rates.enabled": true,`
- Use the shop domain the release was tested against. Take it from the card evidence or from the request. `fedexapp-dg-csp.myshopify.com` is the usual QA store — use a different domain the moment the evidence or the user names one, and never invent a store.
- When the release covers more than one shop, send one fenced block per shop, each with a line naming the store it is for.
- Some FedEx cards name a toggle with no shop prefix at all. Do not bolt a domain onto those — list them separately with the note that they are applied against the named shop directly, exactly as `fedex-toggle-enable-list` specifies.
- Use `fedex-slack-operator` for the DM, since this is a text message rather than a file upload.
- Carry over the `fedex-toggle-enable-list` guardrails: never invent a toggle, never repair a malformed shop domain, and list anything left out with a one-line reason.

## Combined Release Package Structure

Combined Support Guide:

```markdown
# <Release> Support Guide

## Included Story Cards
| Story ID | Story Title | Toggle Name | Trello card link |
|---|---|---|---|

## <Story ID> - <Card title>
### Brief Description
...

## Technical Cards
### <Story ID> - <Card title>
...
```

Do not add a `How Support Should Use This Package` section. The index page is followed directly by the first card section.

Combined Business Brief:

```markdown
# What's New: <Release>

## Release Overview
...

## Included Updates
| Story ID | Story Title | Toggle Name | Trello card link |
|---|---|---|---|

## <Story ID> - <Card title>
### Brief Description
...

## Technical Cards
### <Story ID> - <Card title>
...
```

## Technical Cards Section

Layout rules, which follow how `render_pdf_bytes` breaks pages:

- Use one H2 `## Technical Cards` after the last normal card section. Inside a combined package the renderer page-breaks before every non-package H2, so this section gets its own page automatically — never hand-place a break.
- List each technical card under it as an H3 `### <Story ID> - <Card title>` so the short entries flow together instead of taking a page each.
- Two to four lines per card: what changed, and why it matters for the product or the merchant. No walkthrough, no toggles section, no expected-behaviour section.
- Plain wording still applies. Name a version, endpoint, or field only when the entry makes no sense without it.
- Omit the section entirely when the release has no technical cards.

## Support Guide Structure

For each card section inside the combined Support Guide, follow the sample release support guide style:

```markdown
# Support Guide: <Story ID or concise feature name>

## Brief Description
...

## Toggles & Prerequisites
...

## Step-by-Step Support Walkthrough
...

## Expected Behaviour
...
```

Do not add `Release Details`, `Where to Find This in the App`, `Business-Safe Explanation`, `Merchant-Safe Explanation`, `Common Questions & Troubleshooting`, `Support Escalation Packet`, `Known Limitations / Rollout Notes`, or `References` sections. The card section ends after `Expected Behaviour`, and navigation lives inside the walkthrough steps.

## Quality Bar

Before finalizing:

- make it understandable for support people
- remove internal/code jargon entirely from the body; the only exceptions are request/log callouts and the `Technical Cards` section
- verify every card's toggle was searched for across comments, checklists, and QA evidence, not just the description
- verify no card labelled `SL: ON Hold`, `SL: Carrier Platform`, `Spill Over`, or `SL: Closed By Support` slipped into the index table or the body
- verify technical-only cards sit in the `Technical Cards` section at the end, not mixed into the walkthrough cards
- verify every navigation step uses an exact label from the navigation map, for example "Generate Label" rather than "Generate FedEx Label"
- keep merchant-facing wording safe and clear
- do not expose implementation details that customers do not need
- verify every claim comes from card/AC/TC/AI QA evidence or researched domain facts
- verify every live Trello QA comment and checklist has been considered before finalizing a release package
- do not add a generic `Where to Find This in the App` section; include exact navigation in the relevant walkthrough step instead
- include highlighted exact request/log node names when the card requires request-payload, response, or rates-log verification, such as `requestedShipment.shipmentSpecialServices.specialServiceTypes` or `packageSpecialServices.signatureOptionType`
- verify Commercial Invoice is mentioned only for international shipments
- every story card starts on a new page, including the first — the index page stands alone and the renderer inserts the breaks, so never hand-place one
- verify no card heading starts at the bottom of a page without its detail table/content following on the same page
- keep the support guide thorough enough for a support call
- keep the business brief short and polished

## Final Response

Return:

- document(s) generated
- markdown path if saved
- PDF path if rendered
- whether the toggle list DM was sent, skipped because no card has a toggle, or failed
- which cards were excluded and the label that triggered each exclusion
- any missing inputs or assumptions

Use absolute file paths in final responses.
