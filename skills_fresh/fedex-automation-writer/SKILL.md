---
name: fedex-automation-writer
description: Use when working inside the FedexDomainExpert project after US/AC generation, dashboard TC generation, and AI QA browser verification are complete, and the user wants Playwright TypeScript automation written for a FedEx Shopify card. Reuse the dashboard automation conventions, inspect Chrome manually for DOM/locators, reuse existing automation locators and POM methods first, create new locators only when missing, and use saved AI QA locator traces by card id/name when available.
---

# FedEx Automation Writer

Write **Playwright TypeScript** automation for an approved, AI-QA-verified FedEx Shopify card,
matching the existing automation codebase conventions.

## First reads
1. Use `fedex-domain-core` and the code RAG for POM structure, fixtures, and helpers.
2. Look up saved AI QA locator traces by card id/name when they exist.
3. Read the existing automation codebase (`AUTOMATION_CODEBASE_PATH`) before writing anything.

## Inputs
- Approved TCs + AI QA evidence/locator traces for the card.

## Steps
1. Map each TC to a spec. Reuse existing POM methods and locators **first**.
2. Inspect the live DOM in Chrome to confirm selectors before coding new ones.
3. Create new locators/POM methods only where none exist; follow existing naming and file layout.
4. Use project fixtures for store/order setup (e.g. the Shopify order uploader) rather than ad-hoc setup.
5. Keep specs deterministic and independent; avoid `networkidle` on Shopify pages.

## Rules
- Reuse before you create — do not duplicate existing locators or helpers.
- Match the codebase's TypeScript style, folder structure, and POM patterns exactly.
- All paths come from env (`AUTOMATION_CODEBASE_PATH`, etc.) — never hardcode machine paths.

## Output
Playwright TS spec(s) + any new POM methods/locators, placed to match the existing automation
project structure, ready to run.
