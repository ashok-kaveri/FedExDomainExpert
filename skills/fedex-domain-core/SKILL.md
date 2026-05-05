---
name: fedex-domain-core
description: Use when working inside the FedexDomainExpert project and the user asks anything about the PluginHive FedEx Shopify app, FedEx app QA domain, app flows, FedEx carrier/API behavior, project architecture, local RAG/code/wiki knowledge, or wants research-backed answers that may require browsing beyond the current knowledge base. This is the shared domain/research core for AC, TC, AI QA, automation, handoff, and support tasks.
---

# FedEx Domain Core

Use this skill as the shared knowledge and research layer for the FedexDomainExpert project.

It should make Codex/Claude behave like the project Domain Expert:

- know the FedEx Shopify app architecture
- understand dashboard pipeline stages
- use local project knowledge before guessing
- browse official/current sources when local knowledge is missing or stale
- cite where facts came from
- feed research-backed conclusions into US/AC, TC, AI QA, automation, and handoff work

## First Reads

Always start with:

1. `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/AGENTS.md`
2. `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/CLAUDE.md` if extra session context is needed
3. `/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/skills/fedex-domain-core/references/research_workflow.md`

Then read only the project files directly relevant to the task.

## What This Skill Covers

Use for questions or tasks about:

- FedEx Shopify app behavior
- PluginHive app UI flows
- Shopify admin vs app iframe navigation
- manual/auto label generation
- SideDock options
- request/response logs
- Print Documents vs Download Documents
- FedEx REST API fields and constraints
- packaging, pickup, return label, bulk label, order grid, products, settings
- generated AC/TC correctness
- AI QA evidence strategy
- automation/POM/spec patterns
- support/business handoff facts
- research that local RAG may not have yet

## Research Order

Use this order:

1. `AGENTS.md` and local skills
2. local project files
3. automation repo files under `AUTOMATION_CODEBASE_PATH`
4. local wiki / docs / Chroma-backed context if available
5. official/current web sources when needed

Browse the web when:

- the user asks to research, browse, verify, or use latest/current information
- local knowledge does not answer the question
- FedEx/Shopify/PluginHive rules may have changed
- public docs/API behavior is needed for AC/TC correctness
- a linked PR, docs page, Zendesk, changelog, or issue is referenced and its content is not already provided

For web research, prefer:

- official FedEx developer/docs pages
- official PluginHive docs/help pages
- official Shopify docs
- project-linked PRs/issues/docs if accessible

Avoid relying on random blogs unless no official source exists, and clearly mark any inference.

## Answer Style

For Q&A:

- answer directly
- mention local/project source and web source when used
- separate known fact from inference
- include exact file references for local code facts
- include links for web sources

For generation tasks:

- summarize the research that matters
- use the research to improve the output
- do not dump long source notes unless the user asks

## Relationship To Other Skills

Other FedEx skills should use this skill's research posture:

- `fedex-trello-operator`: fetch the real card/list/comments/members first when the user gives Trello references.
- `fedex-ac-writer-reviewer`: research first, then generate/review US + AC, then Trello comment only.
- `fedex-dashboard-tc-publisher`: generate dashboard TCs, compact Trello comment, and positive-only CSV rows for the `Ai` tab.
- `fedex-ai-qa-testcase-prep`: create detailed AI QA executable TCs when browser verification needs richer steps.
- `fedex-ai-qa-browser`: verify reviewed TCs in Chrome with evidence, cleanup, and locator trace handoff.
- `fedex-automation-writer`: use reviewed TCs plus AI QA evidence/locator traces to write Playwright automation in `AUTOMATION_CODEBASE_PATH`.
- `fedex-bug`: format QA-found bugs, check Backlog duplicates, and create Trello Backlog cards only when asked.
- `fedex-signoff-message`: fetch release/list cards, ask for Backlog links, prepare the QA sign-off message, and send to Slack only after QA confirms channel/message.
- `fedex-handoff-docs`: generate Support Guide and/or Business Brief PDFs from approved cards.
- `fedex-slack-operator`: search users/channels, read messages, reply in threads, and send DMs/channel posts only when asked.
- `fedex-rag-sync`: pull latest and safely sync/reindex backend, frontend, automation, wiki, and Shopify Actions knowledge.
- `fedex-knowledge-maintainer`: after the card cycle, update approved-card RAG, QA feedback, and outdated durable rules.

Normal card-cycle order:

```text
Trello card/list/comments
  -> domain research
  -> US + AC comment
  -> dashboard TCs + Trello/CSV publish package
  -> AI QA browser verification + locator trace
  -> bug follow-up if needed
  -> automation writer
  -> sign-off message
  -> handoff docs
  -> RAG sync if source repos/docs changed
  -> knowledge maintainer
```

Use Trello/Slack operator skills for actual external reads/writes. Generation skills should prepare content; operator skills should perform Trello/Slack actions when the user clearly asked for those actions.

## Do Not

- Do not invent FedEx limits or API rules.
- Do not assume local RAG is complete.
- Do not use stale memory for current FedEx/Shopify/PluginHive rules if browsing is available and relevant.
- Do not update Trello, Slack, Sheets, or repo files unless the user asks for that action.
- Do not browse for secrets or private data.
