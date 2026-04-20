# API Precheck Plan

## Purpose

Add an `API Precheck` stage before UI AI QA so the platform can detect backend and integration failures early, classify issues more cleanly, and avoid wasting browser time on flows that are already broken at the API layer.

This is a future feature plan only. It does not change the current dashboard flow yet.

---

## Goal

For each card:

1. identify whether API testing is relevant
2. infer the important APIs/endpoints touched by the card
3. run a small set of high-value API checks
4. classify results as blocking or non-blocking
5. feed API evidence into UI AI QA
6. report API issues before UI verification when appropriate

---

## Proposed Pipeline Position

Target delivery flow:

1. `Validate AC`
2. `Generate TC`
3. `API Precheck`
4. `AI QA Verifier`
5. `Sign Off`
6. `Handoff Docs`

Important:
- `API Precheck` should be conditional, not mandatory for every card
- pure UI cards should be skippable
- API failures should not always hard-block UI; the platform should decide based on the endpoint and scenario type

---

## When API Precheck Should Run

Run API precheck for cards related to:

- rates / rate calculation
- shipment creation
- label generation
- shipment cancel / regenerate
- return shipment
- pickup creation / management
- settings save that affect backend payloads
- shipment documents / tracking / customs / DG / packaging integration
- order sync / import / backend state changes

Skip or minimize for:

- copy-only changes
- styling/layout changes
- navigation-only changes
- UI-only feature toggles that do not affect backend behavior

---

## High-Level Architecture

### 1. API Scenario Detector

Input:
- Trello card
- generated AC
- reviewed test cases
- requirement research

Output:
- `api_relevant: true|false`
- impacted API categories
- precheck priority

Suggested categories:
- `rates`
- `create_shipment`
- `cancel_shipment`
- `return_shipment`
- `pickup`
- `settings_update`
- `tracking`
- `documents`
- `order_sync`

### 2. API Research Layer

Research sources:
- backend code
- frontend API clients
- automation helpers
- wiki/docs
- reviewed AC/TCs
- RAG knowledge

Expected output:
- endpoint candidates
- auth needs
- required headers
- request payload shape
- expected response fields
- likely success/error patterns

### 3. Environment Resolver

This should be configured once, not guessed per run.

Required environment details:
- API base URL
- auth method
- token/cookie source
- store/account context
- environment name
- allowed read/write behavior

Recommended:
- endpoint allowlist
- reusable headers
- scenario-safe test accounts
- reusable payload templates

### 4. Payload Builder

Build request bodies using:
- TC preconditions
- code/documented defaults
- known scenario templates
- store/account variables

Should support:
- template payloads
- scenario overrides
- reusable substitutions

### 5. API Runner

Preferred direction:
- Postman MCP

Runner responsibilities:
- execute request(s)
- capture status/body/time
- preserve request/response evidence
- support request-level or collection-level tests where useful

### 6. API Verifier

Verify:
- HTTP status code
- required response fields
- business values
- error messages
- returned ids / labels / documents / tracking values
- consistency with AC and reviewed TCs

### 7. Result Router

If API fails:
- classify result
- decide whether UI should be skipped, downgraded, or allowed
- optionally raise API bug before UI testing

If API passes:
- inject API evidence into UI AI QA

---

## What the System Can Infer vs What Must Be Configured

### The system can infer

- likely impacted endpoints
- request field names from code
- payload shape hints
- likely success/error patterns
- expected business fields to verify

### The user/project should provide

- API base URL
- auth strategy
- token acquisition method
- safe account/store/environment
- secrets
- allowed endpoint scope
- reusable test payloads where needed

Important:
- do not assume the agent can safely infer everything from code alone
- auth and environment access should be explicit and reusable

---

## Execution Rules

### Blocking failures

Examples:
- shipment creation endpoint broken
- rates endpoint broken
- pickup creation endpoint broken
- required auth failing
- settings-save API broken for a backend-driven feature

Recommended behavior:
- show API failure clearly
- allow QA to stop before UI
- optionally allow manual override to continue UI anyway

### Non-blocking failures

Examples:
- secondary read endpoint issue
- warning response that does not block the main feature
- partial data mismatch that still allows UI validation

Recommended behavior:
- continue to UI with warning
- carry API evidence into bug review

### Skipped API precheck

When:
- card is UI-only
- no safe auth/environment exists
- endpoint relevance is too weak

Recommended behavior:
- mark `skipped`
- continue to UI flow normally

---

## Proposed Dashboard UX

New top-level tab:
- `🧪 API Precheck`

Suggested sections:

1. Eligibility
- Is this card API-relevant?
- Why or why not?

2. Planned checks
- endpoint list
- request types
- blocking vs non-blocking

3. Environment status
- auth ready
- token ready
- base URL ready

4. Run API precheck
- execute planned checks

5. Results
- pass / fail / partial / skipped
- request/response summary
- evidence details

6. Actions
- send API bug to developer
- continue to UI AI QA
- continue with warning

---

## Output Objects

### `ApiCheckPlan`

Suggested fields:
- `card_id`
- `card_name`
- `relevant`
- `categories`
- `endpoints`
- `auth_profile`
- `payload_templates`
- `blocking_checks`
- `notes`

### `ApiCheckResult`

Suggested fields:
- `endpoint`
- `method`
- `status_code`
- `passed`
- `blocking`
- `request_summary`
- `response_summary`
- `evidence`
- `error`

### `ApiPrecheckReport`

Suggested fields:
- `overall_status`
- `summary`
- `results`
- `proceed_to_ui`
- `bug_candidates`
- `warnings`

---

## Initial Supported API Families

Start with:

1. `rates`
2. `create_shipment`
3. `cancel_shipment`
4. `pickup`
5. `settings_update`

Why:
- these are high-value
- they often block UI testing
- they provide strong early signal for backend regressions

---

## Implementation Phases

### Phase 1

- API relevance detection
- environment/auth config
- manual endpoint mapping per category
- 1 to 2 high-value checks per card
- dashboard result display

### Phase 2

- code-driven endpoint discovery
- payload template system
- response-field verification
- API bug reporting integration

### Phase 3

- full Postman MCP integration
- scenario-specific payload generation
- automatic handoff into UI AI QA
- store API evidence for automation generation

---

## Recommended Safety Rules

- do not run broad API exploration blindly
- use endpoint allowlists
- keep write operations limited and intentional
- use safe test accounts/stores only
- make auth/environment configuration explicit
- preserve request/response artifacts for debugging

---

## Recommended Design Principle

Build this as:

- `guided API precheck`

not:

- `fully autonomous API exploration`

Why:
- safer
- easier to debug
- easier to adopt across projects
- more reliable for release QA

---

## Success Criteria

This feature is successful when:

- API-relevant cards get a small, targeted API validation before UI
- API failures are caught earlier and classified clearly
- UI AI QA receives useful API evidence
- QA can decide quickly whether to continue or stop
- bug reports become clearer about API vs UI vs integration failures

