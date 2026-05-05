# RAG Sync Flow

## Knowledge Stores

FedexDomainExpert has two RAG areas:

1. Main domain knowledge collection: `fedex_knowledge`
   - FedEx REST knowledge
   - PluginHive docs
   - app UI knowledge
   - PDF test cases
   - wiki
   - Shopify Actions
   - approved cards

2. Code knowledge collection: `fedex_code_knowledge`
   - automation
   - backend
   - frontend

Do not mix the update paths.

## Normal Sync Policy

Backend:

- branch: `master`
- method: `sync_from_git(..., source_type="backend", branch="master")`

Frontend:

- branch: `main`
- method: `sync_from_git(..., source_type="frontend", branch="main")`

Automation:

- branch: QA-selected
- method: `sync_from_git(..., source_type="automation", branch="<selected>")`
- if branch not provided, ask QA

Wiki:

- git pull current branch unless QA says `main`
- delete only source_type `wiki`
- reload with `load_wiki_docs`
- add docs to vectorstore

Shopify Actions:

- preserve exact path from `.env`, including trailing spaces
- delete only source_type `shopify_actions`
- reload `.js` and `.json`

## Full Reindex Policy

Full reindex for backend/frontend/automation is okay when QA asks for that scope.

Full main knowledge rebuild through `ingest/run_ingest.py` clears the main collection before rebuilding. Use only when QA explicitly asks for full main RAG rebuild or when the main collection is corrupt/stale globally.

Never use:

```bash
PYTHONPATH=. .venv/bin/python ingest/run_ingest.py --sources wiki
```

for ordinary wiki refresh, because `run_ingest.py` clears the whole main collection first.

## Dirty Repo Check

Before pulling a git repo:

```bash
git status --porcelain
```

If output is not empty, stop and ask QA whether to continue. Do not hide local changes.

## Recommended QA Prompts

When automation branch is missing:

```text
Which automation branch should I sync? Current branch is `<branch>`. Available branches include: ...
```

When full reindex is requested vaguely:

```text
Which scope do you want fully reindexed: automation, backend, frontend, wiki, Shopify Actions, or full main knowledge?
```
