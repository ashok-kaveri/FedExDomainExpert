---
name: fedex-slack-operator
description: Use inside FedexDomainExpert when the user asks Codex or Claude to work with Slack using project .env credentials: search Slack users, list channels, fetch messages from any visible channel, read a thread, send a channel message, reply in a Slack thread, send a DM to a user by name or ID, or coordinate with Trello developer assignment. Requires explicit user intent before any Slack send.
---

# FedEx Slack Operator

Use this skill for Slack read/send/reply tasks in the FedEx QA pipeline.

The skill uses project `.env` credentials:

- `SLACK_BOT_TOKEN` for user search, channel listing, history, DMs, channel posts, and replies
- `SLACK_CHANNEL` for default channel posts
- `SLACK_WEBHOOK_URL` only for simple configured-channel posts

Do not hardcode tokens, channel IDs, or user IDs.

## Read First

Before Slack work, read:

- `AGENTS.md`
- `pipeline/slack_client.py`
- `references/slack_ops.md`

Use existing helpers from `pipeline/slack_client.py` when they fit. Use the bundled script for generic channel history/thread replies.

## Allowed Read Tasks

You may read Slack when the user asks:

- "fetch messages in this channel"
- "read this Slack thread"
- "find messages from this user"
- "search Slack user Ashok"
- "show recent QA channel messages"

## Write Safety

Slack sends require clear user intent.

Examples of clear intent:

- "send msg to this user"
- "reply to this Slack thread"
- "send this to the dev"
- "post this in the channel"
- "send the final sign-off message"

If the user asks to draft, prepare the message only.

For QA release sign-off messages, prefer `fedex-signoff-message` because it fetches the Trello line/cards and asks for Backlog links before sending.

For sensitive or broad messages, show the resolved recipient/channel and message before sending unless the user gave exact send wording.

## Common Commands

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-slack-operator/scripts/slack_ops.py users --query "Ashok"
PYTHONPATH=. .venv/bin/python skills/fedex-slack-operator/scripts/slack_ops.py channels
PYTHONPATH=. .venv/bin/python skills/fedex-slack-operator/scripts/slack_ops.py messages --channel "C0123456789" --limit 20
PYTHONPATH=. .venv/bin/python skills/fedex-slack-operator/scripts/slack_ops.py thread --channel "C0123456789" --ts "1710000000.000000"
PYTHONPATH=. .venv/bin/python skills/fedex-slack-operator/scripts/slack_ops.py send-dm --user "U0123456789" --text "..."
PYTHONPATH=. .venv/bin/python skills/fedex-slack-operator/scripts/slack_ops.py send-dm-by-name --query "Dev Name" --text "..."
PYTHONPATH=. .venv/bin/python skills/fedex-slack-operator/scripts/slack_ops.py send-channel --channel "C0123456789" --text "..."
PYTHONPATH=. .venv/bin/python skills/fedex-slack-operator/scripts/slack_ops.py reply --channel "C0123456789" --thread-ts "1710000000.000000" --text "..."
```

## Trello Developer DM Flow

When the user asks to send a message to the developer assigned to a Trello card:

1. Use `fedex-trello-operator` to get card devs.
2. Search Slack by first name and full name.
3. Pick the best exact/near match; if multiple likely users remain, ask QA to choose.
4. Send a concise DM that includes:
   - card name
   - card URL
   - QA request/blocker
   - evidence or expected/actual when relevant

## Output

For read tasks, summarize useful messages with:

- channel/user
- timestamp
- sender
- text summary
- thread timestamp if replyable

For write tasks, return:

- recipient/channel
- message timestamp
- whether it was a DM, channel post, or thread reply
- any API error or missing-scope guidance
