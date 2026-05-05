---
name: fedex-bug
description: Use when working inside the FedexDomainExpert project and QA reports a bug during AI QA/browser/manual testing and wants it formatted, checked against existing Trello Backlog cards, and created in the Trello Backlog list. Mirrors the dashboard Bug Reporter flow: plain-English QA issue -> Jira-style bug draft -> duplicate check -> create Backlog card after approval.
---

# FedEx Bug

Use this skill when QA says a bug was found and wants it raised properly in Trello Backlog.
Use `fedex-trello-operator` for general card/list/comment reads. Use this skill when the target is a properly formatted bug card in Backlog.

It mirrors the dashboard `Bug Reporter` flow:

1. QA describes the issue in plain English.
2. Format it as a structured Jira-style bug.
3. Check Trello Backlog for duplicates.
4. If duplicate exists, show the existing card and do not create a new one unless QA says "raise anyway".
5. If no duplicate, show the draft for review.
6. When QA approves, create the Trello card in `Backlog`.
7. If the bug was found while testing a release card, comment back on that release card with the backlog bug link when possible.

## First Reads

Before acting:

1. Read `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/AGENTS.md`.
2. Read:
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/skills/fedex-bug/references/bug_flow.md`
3. Inspect only directly relevant files:
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/bug_tracker.py`
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/bug_reporter.py`
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/pipeline/trello_client.py`
   - `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/ui/pipeline_dashboard.py`

## Inputs

Ask for or infer:

- bug description
- feature/page context
- release
- card being tested, if any
- actual behavior
- expected behavior
- steps to reproduce
- evidence from AI QA/browser run
- severity if QA already knows it

If QA gives a short report, still produce a reasonable draft but mark missing details.

## Trello Behavior

Do not create a Trello card silently.

Default flow:

1. Draft and duplicate-check first.
2. Show the draft/duplicate result.
3. Create the Backlog card only after the user says approve/create/raise.

If the user explicitly says "create it in backlog" or "raise bug now", you may run the helper in raise mode after doing duplicate check. If a likely duplicate is found, stop and show the duplicate unless the user explicitly says "raise anyway".

If the user asks to notify the assigned developer after creating or drafting the bug, use `fedex-trello-operator` to resolve card devs and `fedex-slack-operator` for the Slack DM.

Target list:

```text
Backlog
```

Use the existing `pipeline.bug_tracker.raise_bug` behavior.

## Bug Draft Format

The Trello card description must follow the project format:

```markdown
## Bug Report

**Type:** Bug
**Severity:** P1 | P2 | P3 | P4
**Feature Area:** ...
**Environment:** QA
**Release:** ...
**Labels:** `QA Reported` · `FEDEX-APP` · `P2`

---

### Steps to Reproduce
1. ...

### Expected Behaviour
...

### Actual Behaviour
...

---
*Raised via FedEx QA Pipeline — Bug Tracker*
```

Labels must include:

- `QA Reported`
- `FEDEX-APP`
- severity label: `P1`, `P2`, `P3`, or `P4`

Severity guide:

- `P1`: app crash, data loss, cannot generate labels broadly
- `P2`: core feature broken, wrong rates, label generation fails for an important service/scenario
- `P3`: non-blocking setting/UI/data display issue
- `P4`: minor UX, typo, cosmetic issue

## Helper Script

Use:

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-bug/scripts/bug_backlog.py --issue "<bug>" --feature "<feature>" --release "<release>"
```

To create after approval:

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-bug/scripts/bug_backlog.py --issue "<bug>" --feature "<feature>" --release "<release>" --raise
```

Optional:

- `--backlog-list "Backlog"`
- `--linked-card-id "<release card id>"`
- `--linked-card-name "<release card name>"`
- `--linked-card-url "<release card url>"`
- `--raise-anyway` when QA confirms a duplicate is actually different

The script uses `.env` and existing Trello/client behavior.

## Final Response

Return:

- duplicate result, if any
- bug title
- severity
- feature area
- Trello Backlog URL when created
- linked release card comment status, if attempted
- any missing details QA should add
