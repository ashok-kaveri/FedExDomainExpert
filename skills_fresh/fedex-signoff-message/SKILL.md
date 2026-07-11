---
name: fedex-signoff-message
description: Use inside the FedexDomainExpert project when QA asks to prepare or send the final QA sign-off message for a Trello release line or list. Fetch all cards from the line, prepare the dashboard-style Slack sign-off message, ask QA for any Backlog bug links if bugs were created, review the message with QA, and send to the Slack channel only after QA provides the channel and explicitly confirms.
---

# FedEx Sign-off Message

Prepare and (after explicit confirmation) send the final QA **sign-off message** for a release
line to Slack, in the dashboard format.

## First reads
1. Use `fedex-trello-operator` to fetch every card in the release line/list.
2. Use `fedex-slack-operator` to send — only after explicit channel + confirmation.

## Inputs
- The Trello release line/list (name or id).
- Optional: Backlog bug links for issues found during the cycle.

## Steps
1. Fetch all cards in the line; collect titles, ids, and status.
2. Build the dashboard-style sign-off summary (release name, cards covered, QA result).
3. If bugs were created, ask QA for the Backlog bug links and include them.
4. **Review with QA** — show the drafted message and wait for edits/approval.
5. Send to Slack **only** after QA names the channel and explicitly confirms.

## Rules
- Never send without an explicit channel + explicit "send it" confirmation.
- Don't fabricate results — reflect the actual QA verdicts and any open bugs.

## Output
The reviewed sign-off message, and (on confirmation) confirmation that it was posted to the
named Slack channel.
