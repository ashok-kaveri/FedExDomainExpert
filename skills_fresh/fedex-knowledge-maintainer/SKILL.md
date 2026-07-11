---
name: fedex-knowledge-maintainer
description: Use inside the FedexDomainExpert project after a FedEx release card cycle is complete, or when QA asks to update old, wrong, missing, or outdated project knowledge. Updates approved-card RAG, QA retrospective feedback, durable AGENTS/skill rules, and replaces obsolete knowledge without duplicating stale instructions.
---

# FedEx Knowledge Maintainer

Keep the project's durable knowledge current after a release cycle: embed approved cards,
record QA retrospective feedback, and update long-lived rules — without leaving stale duplicates.

## When to use
- A release card cycle finished and its learnings should be captured.
- Project knowledge is wrong, outdated, missing, or contradictory.

## Steps
1. **Approved-card RAG** — embed approved cards' description/AC/TCs into `fedex_knowledge` so the
   system learns from each sprint.
2. **Retrospective feedback** — record QA notes on what the pipeline got right/wrong this cycle.
3. **Durable rules** — update `CLAUDE.md` / `AGENTS` / skill instructions when a rule genuinely changed.
4. **Replace, don't duplicate** — when fixing knowledge, edit or remove the obsolete entry rather
   than adding a competing one.

## Rules
- Don't duplicate existing knowledge or rules — update in place.
- Only record durable, reusable facts; skip one-off conversation details.
- Verify a referenced file/flag still exists before writing a rule about it.

## Output
A summary of what was embedded, what feedback was recorded, and which rules were updated or retired.
