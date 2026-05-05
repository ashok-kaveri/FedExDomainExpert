# Slack Operations

## Project Helpers

`pipeline.slack_client.py` already provides:

- `search_slack_users(query)`
- `list_slack_channels()`
- `post_content_to_slack_channel(...)`
- `send_ac_dm(...)`
- `send_dm_to_user(user_id, text)`
- `upload_file_to_slack_channel(...)`
- `upload_file_to_slack_user(...)`
- `SlackClient.post_message(text, thread_ts="")`

Use the helper script for generic channel history and thread reads because those are not wrapped by the dashboard helpers.

## Required Slack Scopes

The bot token may need these scopes depending on the task:

- `users:read` for user search
- `channels:read` for public channel list
- `groups:read` for private channel list
- `channels:history` for public channel messages
- `groups:history` for private channel messages
- `im:write` for DMs
- `chat:write` for sending messages
- `files:write` for uploads

If Slack returns `missing_scope`, report the exact scope requested by the API.

Private channels only work if the bot is invited into that channel.

## Channel Names And IDs

Slack APIs prefer channel IDs.

When the user gives a channel name:

1. Run `channels`.
2. Match by exact name without `#`.
3. Use the channel ID for history/post/reply.

If multiple channels match, ask the user which one.

## Reading Messages

For recent messages:

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-slack-operator/scripts/slack_ops.py messages --channel "<channel id>" --limit 20
```

For a thread:

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-slack-operator/scripts/slack_ops.py thread --channel "<channel id>" --ts "<message ts>"
```

Return the useful context, not raw Slack JSON, unless the user asks for raw.

## Sending Messages

Never send if the user only asked to draft.

For DMs by name:

1. Search users.
2. Resolve a single confident user.
3. Send with `send-dm-by-name`.

For thread replies, preserve the original `thread_ts`.

## Message Style

Use concise QA language:

```text
Hi <name>, QA update for <card>:

<request or issue>

Card: <url>
Evidence: <short evidence>
```

Avoid long generated explanations unless the user asks for a full report.
