---
name: fedex-slack-operator
description: Use inside the FedexDomainExpert project when the user asks to work with Slack using project .env credentials — search Slack users, list channels, fetch messages from a visible channel, read a thread, send a channel message, reply in a thread, send a DM by name or ID, or coordinate with Trello developer assignment. Requires explicit user intent before any Slack send.
---

# FedEx Slack Operator

Read and write Slack using the project's `.env` credentials. The shared Slack access layer for
the other FedEx skills (sign-off, handoff uploads, toggle-enable DMs, developer notifications).

## Capabilities
- **Read**: search users, list channels, fetch channel messages, read a thread.
- **Write** (explicit intent required): post a channel message, reply in a thread, send a DM
  by user name or ID, upload a file (e.g. a handoff PDF).

## Rules
- Reads are free; **any send requires explicit user intent** naming the target (channel/user).
- Resolve user names to IDs before DMing; confirm the resolved person when ambiguous.
- Never send sign-off or developer messages without explicit confirmation.

## Output
The requested Slack data, or confirmation of the message/upload sent (with destination).
