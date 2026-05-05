# FedEx Bug Flow

This reference mirrors:

- `pipeline/bug_tracker.py`
- dashboard bug reporter section in `ui/pipeline_dashboard.py`
- `pipeline/trello_client.py`

## Dashboard Flow

1. QA describes a bug.
2. Optional linked release card is selected.
3. Feature/page context and release are provided.
4. `check_and_draft_bug` formats the issue and checks Backlog duplicates.
5. If duplicate:
   - show existing Backlog card
   - do not create new card unless QA says raise anyway
6. If no duplicate:
   - show editable title/severity
   - QA approves
7. `raise_bug` creates the card in Trello Backlog.
8. Dashboard comments on linked release card with the backlog bug link when possible.

## Duplicate Rule

Treat as duplicate when:

- same broken behavior in same feature
- same likely root cause
- same symptom and same page/flow

Do not treat as duplicate when:

- same symptom but different feature/page
- same feature but different broken behavior
- old card is closed/resolved and this is a regression in current release, unless QA agrees it should reuse old card

## Bug Draft JSON Concept

The dashboard asks Claude for:

```json
{
  "title": "concise one-line bug summary",
  "severity": "P1|P2|P3|P4",
  "feature_area": "Settings > Additional Services",
  "steps_to_reproduce": ["step 1", "step 2"],
  "expected_behavior": "what should happen",
  "actual_behavior": "what actually happens",
  "labels": ["QA Reported", "FEDEX-APP", "P2"]
}
```

## Trello Description

Use `BugDraft.to_trello_desc()` from `pipeline.bug_tracker`.

Important fields:

- Type
- Severity
- Feature Area
- Environment
- Release
- Labels
- Steps to Reproduce
- Expected Behaviour
- Actual Behaviour

## Backlog Target

Default list:

```text
Backlog
```

The project code uses `BACKLOG_LIST_NAME = "Backlog"`.

## Linked Release Card Comment

When a bug is created while testing a release card, add a comment to the release card:

```markdown
Bug raised to Backlog: [<bug title>](<bug url>)
Severity: <severity> · Release: <release>
```

Failure to add this comment must not block Backlog card creation.

