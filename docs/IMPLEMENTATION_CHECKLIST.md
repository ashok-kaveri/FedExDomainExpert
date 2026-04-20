# Generic AI QA Platform — Implementation Checklist

Use this checklist when adapting the platform to a new project.

This is the short practical companion to:

[GENERIC_PLATFORM_REQUIREMENTS.md](/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert/docs/GENERIC_PLATFORM_REQUIREMENTS.md:1)

---

## 1. Project Setup

- Define environment variables for all local paths
- Remove machine-specific defaults
- Confirm model/API keys
- Confirm collaboration tool credentials
- Confirm document export dependencies
- Confirm browser automation runtime

Done when:
- app starts without hardcoded local paths
- missing config fails clearly

---

## 2. Knowledge Sources

- Identify product documentation source
- Identify internal wiki/notes source
- Identify ticket/tracker source
- Identify codebase source
- Identify automation codebase source
- Identify API reference source
- Identify support/customer issue source
- Decide which historical data should be indexed

Done when:
- ingestion can run source by source
- semantic search returns useful context

---

## 3. Requirement Writing

- Define user story + AC output format
- Define requirement classification categories
- Add research-first requirement generation
- Add AC review pass
- Add AC persistence
- Add AC push/share actions

Done when:
- raw request becomes structured AC with review findings

---

## 4. Domain Validation

- Define validation rules
- Add missing-prerequisite detection
- Add duplicate-scenario detection
- Add regression/customer-impact checks
- Add “apply fixes” rewrite path

Done when:
- weak AC can be improved before TC generation

---

## 5. Test Case Generation

- Define TC markdown/schema format
- Define TC type/priority rules
- Add TC review pass
- Add TC persistence
- Define external export format
- Define internal verifier metadata format

Done when:
- approved AC becomes reviewed execution-ready TCs

---

## 6. AI QA Agent

- Make AI QA TC-based
- Add browser execution framework
- Add progress reporting
- Add stop behavior
- Define result statuses
- Define evidence model
- Add retry/backoff for transient model/API failures

Done when:
- selected reviewed TCs can run against the real app with evidence

---

## 7. Scenario / Prerequisite Planning

- Identify major flow categories
- Define test-data strategies
- Define setup requirements per category
- Define cleanup/reset requirements
- Define manual vs auto or equivalent execution-path rules
- Add deterministic helpers before agentic fallback

Done when:
- AI agent does not wander on common scenarios

---

## 8. Verification Depth

- Add log verification helpers
- Add request/response payload summarization
- Add downloaded file/document parsing
- Add document/PDF verification if needed
- Add business-field verification summaries

Done when:
- verdicts are based on real evidence, not only screenshots

---

## 9. Bug Reporting

- Define QA vs developer member handling
- Add developer lookup
- Add bug-report message format
- Attach evidence and scenario details
- Support manual and automatic bug reporting

Done when:
- QA findings can be turned into actionable developer notifications

---

## 10. Automation Generation

- Reuse existing automation structure where possible
- Define page/module detection strategy
- Generate only a small high-value subset
- Prefer strong business assertions
- Add run-and-fix loop
- Show what was selected and what was skipped

Done when:
- approved TCs can produce maintainable automation in project style

---

## 11. Sign-Off

- Preserve the team’s existing sign-off pattern
- Keep AI QA separate from final sign-off wording
- Add release summary preview
- Add Slack/tool delivery
- Add optional sheet/report export

Done when:
- sign-off still feels native to the team’s process

---

## 12. Handoff Docs

- Add post-sign-off document generation
- Create Support Guide template
- Create Business Brief template
- Include ownership info where needed
- Include toggle/prerequisite notes where needed
- Add markdown preview/edit
- Add PDF export
- Add Trello attachment/comment flow
- Add Slack channel/DM file sharing

Done when:
- approved cards can produce release-ready handoff docs

---

## 13. Dashboard UX

- Create clear step-based tabs/sections
- Persist approved-card state
- Persist review findings
- Show live AI QA progress
- Support rerun/reverify
- Support preview before external posting

Done when:
- the workflow is understandable without code knowledge

---

## 14. Reuse Layer

Before adapting to a new project, isolate:
- project-specific navigation
- project-specific deterministic helpers
- project-specific knowledge sources
- project-specific automation conventions
- project-specific sign-off wording
- project-specific document tone/branding

Done when:
- core platform can stay the same across projects

---

## 15. Final Readiness Check

Confirm all of these:

- requirements are generated from research
- AC has review + validation
- TCs have review
- AI QA uses reviewed TCs
- evidence is captured
- automation generation is selective and maintainable
- sign-off stays in the existing team pattern
- handoff docs can be generated and shared
- environment config is portable
- project-specific logic is isolated

If all are true, the platform is ready to replicate in another project.
