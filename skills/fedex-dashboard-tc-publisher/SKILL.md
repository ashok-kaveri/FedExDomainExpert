---
name: fedex-dashboard-tc-publisher
description: Use when working inside the FedexDomainExpert project and the user has already generated a User Story plus Acceptance Criteria and now wants dashboard-style QA test cases generated from that US/AC using project/domain/automation knowledge, with the two dashboard publish formats: compact Trello QA comment and positive-case CSV rows for the Ai sheet tab. This skill is generation-only and must not call Trello, Google Sheets, Slack, Shopify, or project LLM APIs.
---

# FedEx Dashboard TC Generator Publisher

Use this skill for dashboard-style test case generation and publishing output.

This skill is separate from `fedex-ai-qa-testcase-prep`:

- `fedex-ai-qa-testcase-prep` creates rich test cases for AI QA Agent / Chrome verification.
- `fedex-dashboard-tc-publisher` creates dashboard-compatible QA test cases from approved US/AC and prepares Trello comment + CSV rows.

## First Reads

Before generating or transforming output:

1. Read `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/AGENTS.md`.
2. Read this reference when exact formats are needed:
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/skills/fedex-dashboard-tc-publisher/references/dashboard_tc_formats.md`
3. If the user asks for case generation from a card/story, also inspect only the directly relevant rules in:
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/card_processor.py`
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/sheets_writer.py`

## Execution Boundary

Do not call:

- `TrelloClient`
- Google Sheets / `gspread`
- Slack clients
- Shopify APIs
- `ChatAnthropic` wrappers from project code
- dashboard publish functions such as `write_test_cases_to_card` or `append_to_sheet`

Generate the output directly in Codex/Claude using the same formats and rules.

If the user gives only a Trello URL and no card content is available through the conversation, use `fedex-trello-operator` to fetch the card title, description, comments, checklists, and attachments before generating. If Trello access is unavailable, ask the user to paste the card content.

## Supported Requests

Use this skill when the user asks for:

- dashboard-style TC generation from User Story + AC
- test cases to add to Trello
- test cases to add to CSV or Google Sheet
- Trello QA summary comment
- positive-only sheet rows
- Ai tab CSV output
- converting detailed TC markdown into publish formats
- checking whether a compact Trello summary is enough for sheet publishing

## Primary Input

The normal input is approved or reviewed User Story + Acceptance Criteria from `fedex-ac-writer-reviewer`.

Use the US/AC as the source of truth, then enrich coverage using:

- `AGENTS.md`
- known FedEx app architecture and AI QA verifier rules
- relevant automation repo patterns
- dashboard TC rules in `pipeline/card_processor.py`
- sheet/Trello formatting rules in `pipeline/sheets_writer.py`
- any card comments/checklists/PR notes the user provides

Do not generate TC scenarios that are outside the approved AC unless they are clearly necessary edge/error/regression coverage implied by the AC or project knowledge.

## Output Modes

Choose the smallest output that satisfies the request.

### 1. Detailed TC Markdown

Use when the user needs reviewed test cases before publishing.

Follow the dashboard TC block format:

```markdown
### TC-1: <short title>
**Type:** Positive | Negative | Edge
**Priority:** High | Medium | Low
**Preconditions:** <what must be true before testing>

**Steps:**
Given <initial state>
When <action>
And <additional action>
Then <expected result>
And <additional expected result>
```

Rules:

- Generate at least 4 cases when creating from scratch.
- Include at least 2 Positive, 1 Negative, and 1 Edge case when the feature supports it.
- Cover every AC scenario at least once across the generated TCs.
- Steps must be Given / When / And / Then lines, not numbered steps.
- Do not include mobile, responsive, unit-test, mock, backend-only, or helper-function cases.
- Keep cases browser-verifiable in the PH FedEx app, Shopify admin, request/response logs, downloaded documents, or visible app outcomes.
- Prefer evidence-aware cases that later AI QA can verify through UI, request/response ZIP, rate logs, document ZIPs, or Print Documents PDF.

### 2. Compact Trello QA Comment

Use when the user says Trello, Trello comment, publish to Trello, or dashboard comment.

This includes all Positive, Negative, and Edge cases as one-liners grouped by type.

### 3. CSV / Google Sheet Rows

Use when the user says CSV, sheet, Google Sheet, master sheet, or add rows.

Only Positive cases go to CSV / Sheet rows. Negative and Edge cases stay in the Trello comment only.

Always target the `Ai` sheet tab for CSV/Sheet output. Do not auto-detect a tab for this skill.

The dashboard columns are:

```csv
SI No,Epic,Scenarios,Description,Comments,Priority,Details/Transaction ID,Pass/Fail [Shopify],Release
```

### 4. Publish Package

When the user asks for "same as dashboard" or asks for both Trello and CSV, return:

1. Detailed TC markdown
2. Compact Trello QA comment
3. Sheet tab: `Ai`
4. Positive-only CSV rows
5. Count summary

## Sheet Tab Suggestion

For this skill, always use:

```text
Ai
```

Do not use the dashboard keyword tab detector unless the user explicitly asks for legacy tab selection.

## Important Dashboard Rules

- A compact Trello summary is not enough to republish to Sheet. Sheet rows need the full detailed TC markdown.
- Negative and Edge cases are not added to the Sheet by default.
- Positive cases are added to the `Ai` sheet tab.
- In the FedexDomainExpert dashboard workflow, when the user says "csv", "sheet", "master sheet", "add to csv", or "same as dashboard", treat that as Google master-sheet publishing intent unless they explicitly ask for a local CSV file/export.
- Do not create repo-local CSV files as the primary outcome for dashboard publish requests. Local CSV files are only for explicit export/draft requests.
- Trello comment should include all case types.
- Do not write to Trello or Sheet from this skill. Produce paste-ready content only.
- If the user asks to post the Trello comment, hand off to `fedex-trello-operator`.
- If the user asks to add to the master sheet, hand off to the project Google Sheets path (`pipeline.sheets_writer`) and replace/remove old rows for the same card when the user asks to update existing published cases.
- If the user asks to send/publish the TC content in Slack, hand off to `fedex-slack-operator`.

## Final Response

Keep the response practical:

- Give the generated artifact directly.
- If multiple artifacts are requested, label each clearly.
- Mention any assumptions, especially release name, QA name, epic, or selected sheet tab.
- If the user wants CSV, use a fenced `csv` block.
