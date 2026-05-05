# FedEx Knowledge Update Flow

## Goal

At the end of each card cycle, make future Codex/Claude runs smarter in the same way the dashboard becomes smarter.

The maintainer should update three layers:

1. Approved card memory through `pipeline.rag_updater.update_rag_from_card`.
2. QA retrospective memory through `pipeline.qa_feedback.save_feedback`.
3. Durable local instructions when a stable rule changed.

## End-To-End Cycle

```text
Approved card
  -> final US/AC comment
  -> reviewed TC comment + Ai sheet rows
  -> AI QA evidence
  -> automation script + run result
  -> bug cards / handoff docs
  -> QA retrospective
  -> knowledge maintainer
```

## What Goes Where

### RAG Approved Card Knowledge

Store final card artifacts:

- original description
- final approved User Story and AC
- final reviewed test cases

Use:

```python
from pipeline.rag_updater import update_rag_from_card
```

This is for future retrieval when similar cards come.

### QA Feedback Knowledge

Store process learnings:

- AC missed a precondition
- TC had wrong execution route
- AI QA needed a better verification signal
- automation locator was wrong or flaky
- a scenario needs a specific order action

Use:

```python
from pipeline.qa_feedback import QAFeedback, ScenarioLearning, save_feedback
```

This is for improving future card processing and scenario handling.

### Durable Docs And Skills

Patch durable docs when a learning changes a stable rule.

Good examples:

- "Print Documents opens a new viewer tab, not a ZIP"
- "Domestic shipments do not include Commercial Invoice"
- "CSV test cases always go to the Ai tab"
- "US/AC must be posted as Trello comments only"
- "Bulk label selection must click the visible header label, not the hidden checkbox input"

Bad examples:

- "This one card had a typo"
- "QA could not test today because credentials expired"
- "A temporary staging outage happened"
- "One local browser was slow"

Those belong in QA notes, not durable rules.

## Outdated Knowledge Cleanup

When new knowledge contradicts old knowledge:

1. Find the old statement with `rg`.
2. Decide whether it is fully wrong or only too broad.
3. Replace it, narrow it, or mark the new exception clearly.
4. Search again for the old wording.
5. Summarize exactly what was replaced.

Useful searches:

```bash
rg -n "Smart AC Verifier|description|Ai tab|Download Documents|Print Documents|execution_flow|Backlog|Ashok" AGENTS.md skills pipeline ui
```

## Re-Ingest Decision

Run source sync/reindex only when source documents changed or when the user asks to refresh ChromaDB from local sources. Prefer `fedex-rag-sync` for routine source sync.

Safe routine refresh:

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-rag-sync/scripts/rag_sync.py sync --target wiki
PYTHONPATH=. .venv/bin/python skills/fedex-rag-sync/scripts/rag_sync.py full-reindex --target shopify_actions
```

Full re-ingest:

```bash
PYTHONPATH=. .venv/bin/python ingest/run_ingest.py
```

RAG approved-card updates through `update_rag_from_card` do not require running `ingest/run_ingest.py`.

## Maintenance Report Template

```markdown
Knowledge maintenance complete.

- RAG card update: yes/no
- QA feedback saved: yes/no
- Durable docs updated: path list or none
- Outdated rules replaced: short list
- Re-ingest needed: yes/no
- QA confirmation needed: none/list
```
