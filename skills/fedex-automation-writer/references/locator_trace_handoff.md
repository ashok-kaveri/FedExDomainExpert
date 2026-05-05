# Locator Trace Handoff

The skill pipeline should preserve what AI QA saw in Chrome so automation generation is grounded in real DOM/labels.

## Trace Directory

Save traces under:

```text
data/ai_qa_locator_traces/
```

Preferred file names:

```text
{card_id}.json
{slugified_card_name}.json
```

## Trace Contents

Use this JSON shape:

```json
{
  "card_id": "trello-card-id-or-empty",
  "card_name": "Card name",
  "created_at": "ISO timestamp",
  "source": "fedex-ai-qa-browser | manual-chrome-inspection | dashboard-ui-trace",
  "tc_ids": ["TC-1"],
  "route": "manual label -> SideDock -> request ZIP",
  "page_context": {
    "shopify_admin": true,
    "app_iframe": true,
    "url": ""
  },
  "steps": [
    {
      "step": 1,
      "action": "observe | click | fill | verify",
      "target": "visible label/button/input",
      "url": "",
      "elements": [
        "button: Save",
        "combobox: Signature Options",
        "checkbox: Enable Dry Ice Support [checked=false]"
      ],
      "notes": "why this matters"
    }
  ],
  "recommended_locators": [
    {
      "surface": "app iframe | shopify admin",
      "kind": "role | label | text | css",
      "locator": "this.appFrame.getByRole('button', { name: 'Save' })",
      "purpose": "Save Additional Services section"
    }
  ],
  "evidence": [
    "label generated badge visible",
    "request ZIP contains HOLD_AT_LOCATION"
  ]
}
```

## How Automation Writer Uses It

Use trace to:

- confirm exact button/field names
- choose iframe vs Shopify admin surface
- add only missing locators
- write business assertion helpers
- avoid hallucinated labels

Do not use trace to:

- bypass existing POM methods
- duplicate locators already in the repo
- assert weak UI states when stronger helpers exist

## When To Save

`fedex-ai-qa-browser` should save a trace after a successful or partially successful browser run when:

- the user may generate automation later
- a new locator/flow was discovered
- the run involved settings, documents, request ZIP, product admin, order grid, or SideDock

