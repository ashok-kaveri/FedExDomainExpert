---
name: fedex-trello-operator
description: Use inside FedexDomainExpert when the user asks Codex or Claude to work with Trello using project .env credentials: read boards, lists, cards, descriptions, comments, checklists, attachments, fetch all cards from a list, identify the developer assigned to a card, add comments or QA replies, move cards, search cards, or create generic Trello cards. For QA bug Backlog creation, use fedex-bug. Requires explicit user intent before any Trello write.
---

# FedEx Trello Operator

Use this skill for Trello actions in the FedEx QA pipeline.

The skill uses the project wrapper `pipeline/trello_client.py`, which reads:

- `TRELLO_API_KEY`
- `TRELLO_TOKEN`
- `TRELLO_BOARD_ID`
- optional `TRELLO_WORKSPACE_ID`

Do not hardcode credentials or board IDs.

## Read First

Before doing Trello work, read:

- `AGENTS.md`
- `pipeline/trello_client.py`
- `references/trello_ops.md`

For developer detection, also use `pipeline/bug_reporter.get_card_devs`, which filters QA members from assigned Trello members.

## Allowed Read Tasks

You may read Trello when the user asks:

- "read comments of this card"
- "fetch all cards from this list"
- "show cards in Dev Done"
- "fetch all cards from this line for sign off"
- "tell me who is dev for this card"
- "read this Trello card"
- "search this card on board"
- "get checklist/attachments/comments"

## Write Safety

Trello writes require clear user intent.

Examples of clear intent:

- "reply to dev in comments"
- "add this comment to the card"
- "move this card to Dev Done"
- "create a generic Trello card"

For QA bug cards in Backlog, use `fedex-bug` instead of this operator.

If the user only asks to draft, prepare the comment and do not post.

Never update the card description for generated US/AC. That project rule is fixed: US/AC goes to Trello comments only.

## Common Commands

Use the helper script:

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-trello-operator/scripts/trello_ops.py card --card "<card id or url>"
PYTHONPATH=. .venv/bin/python skills/fedex-trello-operator/scripts/trello_ops.py comments --card "<card id or url>"
PYTHONPATH=. .venv/bin/python skills/fedex-trello-operator/scripts/trello_ops.py cards-in-list --list "Dev Done"
PYTHONPATH=. .venv/bin/python skills/fedex-trello-operator/scripts/trello_ops.py devs --card "<card id or url>"
PYTHONPATH=. .venv/bin/python skills/fedex-trello-operator/scripts/trello_ops.py add-comment --card "<card id or url>" --text "..."
```

## Dev Handoff To Slack

When the user asks "tell me who is dev for this card and send msg to that dev in Slack":

1. Use this skill to identify Trello dev members:
   ```bash
   PYTHONPATH=. .venv/bin/python skills/fedex-trello-operator/scripts/trello_ops.py devs --card "<card>"
   ```
2. Use `fedex-slack-operator` to search Slack by the dev full name.
3. Show the resolved user(s) before sending unless the user already gave clear send wording.
4. Send a concise DM with card name, card URL, what QA needs, and any blocker/evidence.

## Output

For read tasks, return concise structured results:

- card title and URL
- list name when known
- members/devs
- newest relevant comments first
- checklists/attachments only if useful

For write tasks, return:

- action performed
- card name
- card URL
- comment/action result
- any failures or missing credentials

For final QA sign-off preparation, hand off to `fedex-signoff-message` after fetching the line/list cards.
