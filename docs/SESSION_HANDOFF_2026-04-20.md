# Session Handoff — 2026-04-20

This file captures the important architecture, flow, and UI decisions from the current working session so the same context can be reused in another account or future session.

## Current Product Direction

The platform is a hybrid QA system:

1. AI generates and reviews Acceptance Criteria
2. AI generates and reviews Test Cases
3. AI QA verifies selected reviewed TCs
4. QA reviews failures and approves
5. Automation is generated from approved cards / approved TCs
6. Existing sign-off flow remains the source of truth
7. Handoff documents are generated after sign-off

Important principle:
- not pure automation only
- not pure free-form AI only
- deterministic orchestration for known flows
- agentic fallback for unknown/new flows

## Dashboard Flow

The old single `Release QA` tab was split.

Current top-level tabs:

1. `📝 User Story`
2. `📦 Move Cards`
3. `🧾 Validate AC`
4. `🧪 Generate TC`
5. `🤖 AI QA Verifier`
6. `⚙️ Generate Automation Script`
7. `📋 History`
8. `✅ Sign Off`
9. `📘 Handoff Docs`

### Validate AC

This is the start of the release cycle.

Contains:
- Trello board selection
- release list selection
- load cards
- release intelligence
- card requirements
- toggle detection / notify Ashok
- AC generation
- AC review corrections
- domain validation
- apply validation fixes

Important:
- `Release Intelligence` should show only here

### Generate TC

Uses the same loaded release context from `Validate AC`.

Contains:
- TC generation
- TC review corrections
- Slack DM / Slack channel send
- publish reviewed TCs

Publishing rules:
- Trello comment gets the QA TC summary
- Google Sheet gets positive TCs only
- negative and edge stay in Trello comment only
- duplicate check runs before Google Sheet write

### AI QA Verifier

Uses reviewed TCs.

Contains:
- AI QA execution
- stop / re-verify
- bug review
- Ask Domain Expert
- final approval
- retrospective
- bug reporter follow-on sections

Important:
- this tab should not own TC publishing as the main path anymore
- it can still have fallback save+approve behavior if needed

### Generate Automation Script

This is now release-card based only.

Contains:
- per-card automation generation from approved release cards
- release-level automation actions
- run automation & post to Slack
- generate documentation

Important:
- the old standalone/manual automation UI was removed
- there should be no manual feature-name / manual test-case entry flow here

## AI QA Agent Direction

AI QA is now TC-based, not AC-based.

Core behavior:
- parse reviewed test cases
- QA chooses how many TCs to run
- run highest-priority reviewed TCs first
- use deterministic setup for known categories
- use agent loop where needed

### Internal-only TC metadata

There is internal `execution_flow` metadata for each parsed TC.

Purpose:
- tell verifier whether to use `manual` or `auto` label flow

Important:
- this metadata is internal only
- it must not be added to:
  - Trello comment
  - CSV / Google Sheet
  - user-visible TC markdown

### Flow choice rule

Use `manual` when the TC needs:
- SideDock options
- view logs
- pre-submit verification
- packaging checks before label generation
- HAL / signature / insurance / COD / duties / taxes style options

Use `auto` when the TC mainly needs:
- final generated result
- order summary state
- request/response ZIP after label generation
- documents after label generation

## AI QA Verifier Capabilities Added

The verifier was hardened with deterministic orchestration for:

- packaging flow
- product special-service setup
- manual label launch
- auto label launch
- return label generation
- pickup request / verification
- bulk label flow
- log / request-response ZIP / print documents flow

### Important verification improvements

Added or improved:
- spinner-aware manual-label readiness
- return-label flow goes beyond page-open and can generate return label
- bulk flow waits for label-generated completion
- request-log extraction
- request ZIP structured extraction
- response ZIP structured extraction
- PDF text extraction for print documents when possible

## Toggle Handling

Toggle detection now checks:
- card title
- card description
- card comments

Ashok notification flow is in:
- `Validate AC`

Purpose:
- detect feature-toggle prerequisites early

## Handoff Docs

Added a post-signoff documentation flow.

Generates:
1. `Support Guide`
2. `Business Brief`

### Support Guide

Includes:
- feature summary
- developed by
- tested by
- toggle / prerequisite notes
- how it works
- support/troubleshooting style content

Rules:
- dev/tester ownership belongs here

### Business Brief

Includes:
- problem
- value
- impact
- business scenarios
- rollout notes

Rules:
- should not include developed by / tested by

### Handoff actions

Supports:
- edit inline
- download markdown
- download PDF
- attach PDF to Trello + comment
- send PDF to Slack channel
- send PDF to Slack DM

## QA Names Used by the App

Current QA names used to separate QA from dev ownership:

- Anuja B
- Arshiya Sayed
- Ashok Kumar N
- Basavaraj
- Inderbir Singh
- Keerthanaa Elangovan
- Madan Kumar AS
- Preethi K K
- Shahitha S

## Automation Strategy

Automation generation should:
- use approved release cards
- choose only 1–2 strong E2E cases
- prioritize high-value positive cases
- optionally include one safe edge/negative if appropriate
- prefer strong business assertions over shallow page checks

Automation tab should not return to the old manual generation workflow.

## UI Decisions From This Session

1. Split the old Release QA tab into stage tabs
2. Keep board/list/load-cards in `Validate AC`
3. Keep `Release Intelligence` only in `Validate AC`
4. Keep TC publish/export in `Generate TC`
5. Keep final approval in `AI QA Verifier`
6. Keep automation generation/run in `Generate Automation Script`
7. Remove old standalone manual automation screen
8. Improve button readability and selector layout
9. Replace the `Show all lists` toggle with a checkbox for visibility

## Important Code/Docs Updated In This Session

Main code:
- `ui/pipeline_dashboard.py`
- `pipeline/smart_ac_verifier.py`
- `pipeline/card_processor.py`
- `pipeline/domain_validator.py`
- `pipeline/order_creator.py`
- `pipeline/slack_client.py`
- `pipeline/handoff_docs.py`

Main docs:
- `README.md`
- `CLAUDE.md`
- `docs/GENERIC_PLATFORM_REQUIREMENTS.md`
- `docs/IMPLEMENTATION_CHECKLIST.md`
- `docs/API_PRECHECK_PLAN.md`

## Future Work Already Planned

1. API precheck stage before UI AI QA
2. Better live hardening for packaging/log/document flows
3. Continue improving deterministic playbooks for new scenario families
4. Keep sign-off format separate from AI QA details

## Notes For Another Account / Session

If starting in another account:

1. open this file first
2. open `README.md`
3. open `CLAUDE.md`
4. continue from the current split dashboard architecture
5. do not reintroduce:
   - old single Release QA tab
   - old standalone manual automation tab
   - AI QA details inside sign-off

