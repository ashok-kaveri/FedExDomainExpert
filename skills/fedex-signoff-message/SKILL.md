---
name: fedex-signoff-message
description: Use inside FedexDomainExpert when QA asks Codex or Claude to prepare or send the final QA sign-off message for a Trello release/list/line. Fetch all cards from the Trello line, prepare the dashboard-style Slack sign-off message, ask QA for any Backlog bug links if bugs were created, review the message with QA, and send to the Slack channel only after QA provides the channel and explicitly confirms.
---

# FedEx Sign-Off Message

Use this skill when QA says:

- "prepare sign off msg for this line"
- "prepare sign msg for this release"
- "QA signoff message"
- "send sign-off to Slack"
- "fetch all cards from this line and prepare final message"

This mirrors the dashboard `QA Sign Off` tab.

## Read First

Before preparing a sign-off:

1. Read `AGENTS.md`.
2. Read `references/signoff_flow.md`.
3. Use:
   - `pipeline/slack_client.py` for message format
   - `fedex-trello-operator` for Trello list/card reads when needed
   - `fedex-slack-operator` for Slack channel/user lookup when needed

## Required Flow

1. Identify the Trello board/list/release line.
2. Fetch all cards from that list/line.
3. Prepare the verified card list with card names and Trello URLs.
4. Ask QA whether any Backlog bugs were created:
   - If yes, ask QA to share the Backlog card link(s).
   - Add each bug as `severity, title, URL` when possible.
   - If no bugs, omit the Backlog section.
5. Ask/confirm:
   - release name
   - Slack mentions, default `here` if QA wants team notification
   - CC, if any
   - QA lead/signer name
   - Slack channel to send in
6. Show a final preview.
7. Send only after QA explicitly confirms the preview and channel.

Do not send to Slack while still preparing or while Backlog links are unknown.

## Trello Card Selection

Default behavior:

- Include all cards fetched from the requested Trello list as verified cards.
- If QA says only some passed, ask which cards to include or exclude.
- Preserve card names exactly as Trello shows them.
- Include Trello URL under each card.

If the list cannot be resolved, use `fedex-trello-operator` to show available lists and ask QA which one.

## Backlog Bug Links

The dashboard can auto-fill bugs created in the same session, but Codex/Claude may not have that session state.

So always ask QA:

```text
Any Backlog bugs created for this release? If yes, please share the Trello link(s), severity if known, and title if the link title is not obvious.
```

If QA says no Backlog bugs, continue with no Backlog section.

If QA only provides bug titles without URLs, include them as plain text but mention that URLs were not provided.

## Message Format

Use the same shape as `SlackClient.post_signoff_message`:

```text
<!here>

We've completed testing  *<release>*  and it's good for the release :white_check_mark:

*Cards Verified:*

<card name>
<card url>

*Cards added to backlog (<count>):*

<severity> — <bug link/title>

*QA Signed off* :tada:

CC: <@user or @name>
_Signed by: <qa lead>_
```

Mention handling:

- `here` -> `<!here>`
- `channel` -> `<!channel>`
- Slack IDs starting `U` or `W` -> `<@ID>`
- plain names -> `@name`

## Helper Script

Prepare preview:

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-signoff-message/scripts/signoff_ops.py prepare --list "Dev Done" --release "<release>" --mentions "here" --qa-lead "Madan"
```

Send after explicit confirmation:

```bash
PYTHONPATH=. .venv/bin/python skills/fedex-signoff-message/scripts/signoff_ops.py send --list "Dev Done" --release "<release>" --channel "#qa-automation" --mentions "here" --qa-lead "Madan" --backlog-json "<json file>"
```

The script uses `.env` credentials and existing project clients.
Sending to a QA-selected channel requires `SLACK_BOT_TOKEN`; a webhook alone can only post to its fixed configured channel.

## Safety

- Do not send to Slack without explicit QA confirmation.
- Do not invent Backlog bug links.
- Do not mark cards done or comment on Trello unless QA asks separately.
- Do not use a default Slack channel if QA asked to choose a channel and has not provided one.
- Do not use `SLACK_WEBHOOK_URL` for selected-channel sign-off sends; use bot-token channel posting.
- If Slack/Trello credentials are missing, return the preview and exact missing config.

## Output

For prepare-only:

- release name
- Trello list name
- card count
- verified cards
- Backlog links included/missing
- Slack channel: pending or chosen
- final preview
- question for QA confirmation/channel/backlog links

For send:

- channel
- Slack timestamp
- message preview
- any failures
