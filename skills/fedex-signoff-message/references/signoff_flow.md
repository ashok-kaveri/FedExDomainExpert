# Sign-Off Flow

## Dashboard Source

Dashboard tab:

- `ui/pipeline_dashboard.py` sign-off tab
- `pipeline.slack_client.post_signoff`
- `SlackClient.post_signoff_message`

The message says the release is tested and good for release, lists cards verified, includes Backlog bugs if any, then signs off.

## Data Needed

Required:

- release/list name
- verified cards: name + Trello URL
- Slack channel
- QA confirmation to send

Optional:

- Backlog bug cards: severity, title, URL
- mentions: default `here`
- CC
- QA lead/signer

## Trello Line/List

When QA says "this line", treat it as a Trello list/release line unless the surrounding conversation clearly means something else.

Use `fedex-trello-operator` or the helper script to fetch cards from that list.

Include all fetched cards by default. If QA says not all cards passed, ask which cards to remove.

## Backlog Prompt

Before final review, ask:

```text
Any Backlog bugs created for this release? If yes, please share the link(s). If none, I will send without a Backlog section.
```

Do not invent backlog links from memory.

## Preview Before Send

Always show preview before sending unless the user gives a fully explicit command that includes:

- release/list
- Slack channel
- backlog yes/no
- "send now"

Even then, if Backlog status is unknown, ask once before sending.

## Slack Channel

Slack sends must go to the channel QA specifies.

**Default QA channel**: `C09F65XF4ER` (this is `SLACK_CHANNEL` in `.env`). Use this when QA says "send to QA channel" or "team" without specifying another channel.

If QA gives a channel name like `qa-automation`, resolve it through Slack channel list and use the channel ID.

Selected-channel sending requires `SLACK_BOT_TOKEN`. Do not use `SLACK_WEBHOOK_URL` for this flow because webhooks post to their single fixed configured channel — they cannot target other channels.

If the bot is not in the channel, report Slack's `not_in_channel` or missing-scope guidance.
