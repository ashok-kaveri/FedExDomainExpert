---
name: fedex-trello-operator
description: Use inside the FedexDomainExpert project when the user asks to work with Trello using project .env credentials — read boards, lists, cards, descriptions, comments, checklists, attachments, fetch all cards from a list, identify the developer assigned to a card, add comments or QA replies, move cards, search cards, or create generic Trello cards. For QA bug Backlog creation use fedex-bug. Requires explicit user intent before any Trello write.
---

# FedEx Trello Operator

Read and write Trello using the project's `.env` credentials (`TRELLO_API_KEY`, `TRELLO_TOKEN`,
and an optional default board). The shared Trello access layer for the other FedEx skills.

## Capabilities
- **Read**: boards, lists, cards (description, comments, checklists, attachments, members),
  fetch all cards in a list, identify the assigned developer, search cards on a board.
- **Write** (explicit intent required): add comments / QA replies, move cards between lists,
  create generic cards.

## Rules
- Reads are free; **any write requires explicit user intent** ("post this comment", "move card X").
- Board access is workspace-aware: resolve boards, then lists for the selected board.
- Never invent card content; quote what's actually on the card.
- For creating QA bug cards in Backlog, defer to `fedex-bug` (it adds the duplicate check).

## Output
The requested Trello data, or confirmation of the write performed (with the card/comment link).
