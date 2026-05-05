---
name: fedex-knowledge-maintainer
description: Use inside FedexDomainExpert after a FedEx release card cycle is complete, or when QA asks Codex or Claude to update old, wrong, missing, or outdated project knowledge. Updates approved-card RAG, QA retrospective feedback, durable AGENTS/skill rules, and replaces obsolete knowledge without duplicating stale instructions.
---

# FedEx Knowledge Maintainer

Use this skill after a FedEx release card cycle is complete, or when the user asks to update old, wrong, missing, or outdated project knowledge.

This skill keeps Codex/Claude knowledge aligned with the dashboard workflow by updating:

- approved card knowledge in ChromaDB through `pipeline/rag_updater.py`
- QA retrospective learnings through `pipeline/qa_feedback.py`
- durable local instructions such as `AGENTS.md` and FedEx skill references when a rule has truly changed

## When To Use

Use this skill when the user says things like:

- "after card cycle update knowledge"
- "old knowledge is wrong, update it"
- "add this learning to our FedEx knowledge"
- "update RAG from this approved card"
- "remember this for next cards"
- "fix outdated domain/automation/QA instructions"

This skill normally runs after:

1. `fedex-trello-operator` fetches the real card/list/comment context.
2. `fedex-ac-writer-reviewer` generates reviewed US + AC.
3. `fedex-dashboard-tc-publisher` generates reviewed TCs and publish formats.
4. `fedex-ai-qa-browser` verifies in Chrome and captures evidence/locator traces.
5. `fedex-bug` handles bug follow-up if needed.
6. `fedex-automation-writer` writes automation when approved.
7. `fedex-signoff-message` prepares/sends the QA sign-off when QA confirms.
8. `fedex-handoff-docs` generates support/business docs if needed.
9. `fedex-rag-sync` syncs source repos/docs if backend, frontend, automation, wiki, or Shopify Actions changed.
10. `fedex-knowledge-maintainer` updates approved-card RAG, QA feedback, and durable rules.

## Read First

Open these files before maintaining knowledge:

- `AGENTS.md`
- `pipeline/rag_updater.py`
- `pipeline/qa_feedback.py`
- `references/knowledge_update_flow.md`

If the update touches a specific skill, also read that skill's `SKILL.md` and relevant `references/` file before editing.

If the request is about pulling latest code/docs or reindexing source knowledge, use `fedex-rag-sync` first. This skill is for card-cycle learning and outdated rule maintenance, not routine source repo sync.

## Core Rule

Do not add duplicate knowledge on top of wrong knowledge.

When a new card teaches a better rule, update or replace the old rule wherever it lives. If the old rule is still useful only for a narrow case, narrow it explicitly instead of deleting it.

## What To Collect

For each completed card, collect as much of this as available:

- Trello card id, name, URL, release/list
- original card description
- final reviewed User Story and Acceptance Criteria
- final reviewed test cases
- AI QA Browser verdict and evidence
- automation file paths, run result, and locator trace
- bug cards raised or linked
- handoff docs generated
- QA retrospective notes:
  - AC gaps
  - TC issues
  - automation issues
  - what worked well
  - scenario-specific learnings

If a field is missing, continue with the fields available and call out what could not be updated.

## Update Approved Card RAG

Use `pipeline.rag_updater.update_rag_from_card` for approved card artifacts.

This function already uses stable upsert ids:

- `{card_id}__description`
- `{card_id}__ac`
- `{card_id}__test_cases`

Because of that, rerunning it for the same card replaces outdated chunks instead of creating duplicate stale chunks.

Preferred helper command:

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-knowledge-maintainer/scripts/maintain_knowledge.py --card-id "<id>" --card-name "<name>" --release "<release>" --description-file "<file>" --ac-file "<file>" --test-cases-file "<file>"
```

## Update QA Feedback Memory

Use `pipeline.qa_feedback.save_feedback` when the cycle produced retrospective notes or scenario learnings.

Scenario learnings should capture:

- scenario name
- root cause
- correct navigation
- correct order action
- verification signal
- notes

These records are indexed as `source_type="qa_feedback"` and are later used by AC writing, TC generation, AI QA Browser, and automation generation.

## Update Durable Instructions

After updating RAG/feedback, inspect durable docs for contradictions:

- `AGENTS.md`
- `CLAUDE.md`, if present
- FedEx skill files under `skills/fedex-*`
- relevant reference docs under each skill

Patch durable files only when the learning is stable enough to affect future cards. Examples:

- a FedEx app navigation route changed
- a request/response JSON path was wrong
- dashboard format changed
- a locator or automation pattern became canonical
- a known bug/workaround became obsolete
- a new feature type needs a deterministic AI QA route

Do not patch durable docs for one-off card details, temporary bugs, or unfinished guesses. Put those in QA feedback instead.

## Knowledge Classification

Classify every learning before writing:

- `card_artifact`: approved description, US/AC, TCs
- `qa_feedback`: retrospective, failed assumption, better evidence signal
- `domain_rule`: FedEx/PluginHive/Shopify behavior that future cards need
- `automation_rule`: POM, locator, fixture, test style, run behavior
- `dashboard_format`: Trello comment, CSV, Slack, handoff, bug flow format
- `obsolete_rule`: an existing rule that must be replaced or narrowed

Store each class in the right place. Do not put all knowledge into `AGENTS.md`.

## Research And Verification

If the new learning conflicts with existing knowledge, verify before patching:

1. Check project code and existing skills.
2. Check automation code through `AUTOMATION_CODEBASE_PATH` when relevant.
3. Check local wiki/docs if relevant.
4. Browse official FedEx, Shopify, or PluginHive docs only when local knowledge is missing or likely stale.

When external research changes a rule, cite the source in the update summary. Prefer concise source notes in reference docs over long copied text.

## Output Format

End with a short maintenance report:

- card updated in RAG: yes/no
- QA feedback saved: yes/no
- durable docs changed: list paths
- outdated rules replaced: short list
- re-ingest needed: yes/no and command
- gaps needing QA confirmation: short list

## Safety

- Do not use hardcoded machine-specific fallbacks.
- Preserve exact env paths, including trailing spaces in `.env` values.
- Do not call Trello, Slack, Shopify, or Google APIs unless the user explicitly asked for that action.
- Do not erase historical knowledge unless it is clearly wrong or replaced by a more precise rule.
- Do not edit unrelated docs while maintaining knowledge.
