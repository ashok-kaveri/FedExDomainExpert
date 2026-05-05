# FedEx Domain Research Workflow

## Local Sources

Primary local sources:

- `AGENTS.md`: source of truth for current architecture and known fixes
- `CLAUDE.md`: session context mirror
- `pipeline/smart_ac_verifier.py`: AI QA verifier orchestration
- `pipeline/card_processor.py`: AC/TC prompts and review rules
- `pipeline/domain_validator.py`: domain validation prompt and rewrite rules
- `pipeline/order_creator.py`: Shopify order setup rules
- `pipeline/automation_writer.py`: Playwright generation rules
- `pipeline/handoff_docs.py`: support/business handoff rules
- `rag/chain.py`, `rag/vectorstore.py`, `rag/code_indexer.py`: local RAG behavior

Env-driven external repos:

- `AUTOMATION_CODEBASE_PATH`: Playwright automation specs/POMs/helpers
- `BACKEND_CODE_PATH`: backend implementation
- `FRONTEND_CODE_PATH`: frontend implementation
- `WIKI_PATH`: internal wiki
- `SHOPIFY_ACTIONS_PATH`: Shopify bulk/order tools; preserve trailing spaces in path

Do not add hardcoded fallback paths.

## Browse Triggers

Browse when:

- the user explicitly asks for research or browsing
- official FedEx/Shopify/PluginHive behavior is needed and not present locally
- local docs conflict or seem incomplete
- the topic is likely to have changed
- a public URL is referenced
- AC/TC depends on exact current API fields, service limits, or app docs

## Preferred Web Sources

Use official sources first:

- FedEx Developer / FedEx REST API docs
- PluginHive official documentation / help center
- Shopify official documentation
- official changelogs or release notes

When using web sources:

- cite links in the answer
- keep quotes short
- label inference clearly
- do not overfit AC/TC to unsupported claims

## Research Summary Shape

For generation tasks, keep research summary short:

```markdown
Research used:
- Local project: <file or module>
- Automation pattern: <spec/POM if any>
- Web/source: <official doc link if used>
- Open question: <only if unresolved>
```

## Applying Research To US/AC

When research affects User Story / AC:

- add concrete prerequisites
- add carrier/API/domain constraints
- add edge/error scenarios
- add regression scenario for customer/bug cards
- add source attribution per scenario
- mark unknown limits as open questions

## Applying Research To TC

When research affects test cases:

- choose browser-verifiable scenarios
- use correct app surface
- specify order/product/settings prerequisites
- specify evidence source: UI, request ZIP, response ZIP, rate log, document ZIP, Print Documents PDF
- avoid mobile/unit/backend-only cases

## Applying Research To AI QA

When research affects browser verification:

- use automation flow before improvising
- respect iframe vs Shopify admin split
- use exact labels/headings where known
- avoid global setting changes without cleanup
- ask QA only when blocked or unsafe

