---
name: fedex-rag-sync
description: Use inside FedexDomainExpert when QA asks Codex or Claude to pull latest and sync/reindex RAG knowledge for codebase, automation, backend, frontend, wiki, Shopify Actions, or full knowledge. Backend syncs master, frontend syncs main, wiki uses source-only pull/reindex, and automation is branch-aware and must ask QA for branch unless provided. Never run full reindex unless explicitly requested.
---

# FedEx RAG Sync

Use this skill when QA says:

- "pull latest and sync knowledge"
- "update RAG"
- "sync code knowledge"
- "pull latest backend/frontend/wiki/automation"
- "full re-index"
- "update knowledge from latest code changes"

This skill replaces needing to open the dashboard for RAG sync.

## Read First

Before running sync/reindex:

1. Read `AGENTS.md`.
2. Read `references/rag_sync_flow.md`.
3. Use:
   - `rag.code_indexer.sync_from_git`
   - `rag.code_indexer.index_codebase`
   - `rag.vectorstore.delete_by_source_type`
   - `rag.vectorstore.add_documents`
   - `ingest.wiki_loader.load_wiki_docs`
   - `ingest.codebase_loader.load_codebase`

## Branch Rules

These are fixed:

- Backend: always pull/sync `master`.
- Frontend: always pull/sync `main`.
- Wiki: pull current branch by default; if QA says wiki main, use `main`.
- Shopify Actions: reindex source-only; pull only if it is a git repo and QA asks to pull.
- Automation: branch can change. Ask QA for branch unless they already provided it.

Automation examples:

- "sync automation current branch" -> use current branch.
- "sync automation main" -> use `main`.
- "sync automation release/1.2.3" -> use that branch.
- "sync automation" with no branch -> ask QA which branch.

Do not guess the automation branch.

## Safe Defaults

When QA says "sync latest knowledge" without more detail:

1. Sync backend `master`.
2. Sync frontend `main`.
3. Pull/reindex wiki source-only.
4. Ask which automation branch to sync.
5. Do not run full main RAG rebuild.

When QA says "full reindex", confirm which scope:

- code only
- wiki only
- Shopify Actions only
- full main knowledge via `ingest/run_ingest.py`

## Code Knowledge Store

Backend, frontend, and automation use the separate code knowledge collection through `rag.code_indexer`.

Use `sync_from_git` for normal latest changes:

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-rag-sync/scripts/rag_sync.py sync --target backend
PYTHONPATH=. .venv/bin/python skills/fedex-rag-sync/scripts/rag_sync.py sync --target frontend
PYTHONPATH=. .venv/bin/python skills/fedex-rag-sync/scripts/rag_sync.py sync --target automation --branch "<branch>"
```

Use full code reindex only when explicitly asked:

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-rag-sync/scripts/rag_sync.py full-reindex --target automation --branch "<branch>"
```

## Main Knowledge Store

Wiki and Shopify Actions live in the main `fedex_knowledge` collection.

Use source-only delete/reload, not `ingest/run_ingest.py --sources wiki`, because `run_ingest.py` clears the whole main collection first.

Safe source-only commands:

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-rag-sync/scripts/rag_sync.py sync --target wiki
PYTHONPATH=. .venv/bin/python skills/fedex-rag-sync/scripts/rag_sync.py full-reindex --target shopify_actions
```

Full main rebuild is only for explicit reset:

```bash
PYTHONPATH=. .venv/bin/python ingest/run_ingest.py
```

## Status

Before a risky sync, check status:

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-rag-sync/scripts/rag_sync.py status
```

For automation branch choices:

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-rag-sync/scripts/rag_sync.py status --target automation
```

## Safety

- Do not pull automation without a branch/current-branch instruction from QA.
- Do not run full main RAG rebuild unless QA explicitly asks.
- Do not trim `.env` path values that may contain trailing spaces, especially Shopify Actions.
- If a repo has dirty local changes, stop and ask before pulling.
- If network/git pull fails due to sandbox, rerun with escalation.
- Summarize changed files/chunks after sync.

## Output

Return:

- target
- branch used
- pull result
- commit before/after
- files changed/deleted
- chunks updated/indexed
- whether full reindex was used
- any QA action needed
