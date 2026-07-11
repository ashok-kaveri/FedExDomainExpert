---
name: fedex-domain-core
description: Use when working inside the FedexDomainExpert project and the user asks anything about the PluginHive FedEx Shopify app, FedEx QA domain, app flows, FedEx carrier/API behavior, project architecture, or local RAG/code/wiki knowledge, or wants research-backed answers that may need browsing beyond the current knowledge base. This is the shared domain and research foundation that every other FedEx skill builds on.
---

# FedEx Domain Core

The shared knowledge and research engine for the FedexDomainExpert project. Other skills
(AC writing, TC generation, AI QA, automation, handoff, sign-off) call into this skill
whenever they need authoritative facts about the app, the carrier, or the codebase.

## When to use
- Any question about the PluginHive FedEx Shopify app, its UI flows, or settings
- Any question about FedEx carrier behavior, rate/label/return/manifest APIs
- Project architecture, file layout, or "where does X live" questions
- Requests that need current facts not already in the local knowledge base

## Knowledge sources (search in this order)
1. **Local RAG — `fedex_knowledge`**: domain docs, wiki, app UI, FedEx API, approved cards
2. **Local RAG — `fedex_code_knowledge`**: automation POM, backend, frontend source
3. **Project files**: `CLAUDE.md`, `config.py`, `pipeline/`, `rag/` for ground truth
4. **Live web**: only when local knowledge is stale or missing, and say so explicitly

## Rules
- Prefer local knowledge over memory. Quote file paths when you cite project facts.
- Never invent FedEx API field names, app routes, or button labels — look them up.
- When the knowledge base contradicts a memory or assumption, trust the knowledge base.
- If you browse the web, state which claims came from outside the local KB.
- Keep answers concise and decision-ready; link to the source rather than pasting it whole.

## Output
A direct, sourced answer. When the answer feeds another skill (AC, TC, handoff), return
the facts as clean structured notes the next skill can consume.
