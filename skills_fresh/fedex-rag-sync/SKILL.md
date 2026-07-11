---
name: fedex-rag-sync
description: Use inside the FedexDomainExpert project when the user asks to pull latest and sync or reindex RAG knowledge for codebase, automation, backend, frontend, wiki, Shopify Actions, or full knowledge. Backend syncs master, frontend syncs main, wiki uses source-only pull and reindex, and automation is branch-aware and must ask QA for the branch unless provided. Never run a full reindex unless explicitly requested.
---

# FedEx RAG Sync

Pull the latest source and reindex the project's RAG knowledge collections
(`fedex_knowledge`, `fedex_code_knowledge`).

## Sources & branch rules
- **backend** → sync `master`
- **frontend** → sync `main`
- **automation** → branch-aware; **ask QA for the branch** unless it's provided
- **wiki** → source-only pull + reindex
- **shopify_actions** → preserve the exact configured path (may end in a trailing space)
- **codebase / full** → only on explicit request

## Steps
1. Confirm which source(s) to sync; for automation, confirm the branch first.
2. Pull latest for each selected source on its correct branch.
3. Run the partial reindex for just those sources, e.g.:
   `PYTHONPATH=. .venv/bin/python ingest/run_ingest.py --sources wiki shopify_actions`
4. Report what was pulled and reindexed.

## Rules
- **Never run a full reindex unless explicitly requested** — prefer partial, scoped reindexes.
- Use env-driven paths only; never hardcode machine-specific folders.
- Always confirm the automation branch before syncing it.

## Output
A summary of sources pulled, branches used, and collections reindexed.
