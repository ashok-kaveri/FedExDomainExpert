# Toggle Detection And Slack Notification

The dashboard detects feature toggles during `Validate AC` and can DM Ashok Kumar N before QA begins.

Project implementation:

- `pipeline.slack_client.detect_toggles`
- `pipeline.slack_client.notify_toggle_enablement`
- `pipeline.slack_client.check_toggle_reply`
- dashboard UI block in `ui/pipeline_dashboard.py`

## Toggle Detection Patterns

Detect from card title, description, comments, and checklists:

- explicit `toggle: <name>`
- quoted Shopify keys like `all.myshopify.com.shopify.webhook...enabled`
- quoted Shopify keys like `shopify.feature...`
- phrases like:
  - `enable <name> toggle`
  - `activate <name> flag`
  - `turn on <name> feature flag`
  - `<name> feature flag`

Deduplicate case-insensitively.

## Generated AC Handling

When toggles are found:

- add Domain Rules prerequisite
- add Given step prerequisite
- do not assume QA can start until enabled
- add `Toggle Enablement` section after AC

## Slack Send Policy

Do not send Slack automatically after detecting a toggle.

Send only when:

- user explicitly asks to notify/send/message Ashok, or
- user confirms after being shown the prepared message

## Required Credentials

`SLACK_BOT_TOKEN` must be available from `.env` / environment with scopes for:

- `users:read`
- `im:write`
- `chat:write`

The script searches Slack for `Ashok Kumar`.

## Message Shape

Dashboard message text:

```text
Toggle Enable Request - {card_name}

QA is about to start on this card and requires the following toggle(s) to be enabled on {store_name}:

- `{toggle}`

Store admin: {store_url}

Please enable the toggle(s) above and reply `done` to this message so the QA pipeline knows to proceed.
```

## Store Resolution

Use store in this order:

1. user-provided store
2. `STORE` in project environment
3. `STORE` from automation repo `.env` under `AUTOMATION_CODEBASE_PATH`
4. ask user for store

Admin URL:

- prefer `https://admin.shopify.com/store/{store_name}`
- if the store is a myshopify domain, `https://{store_name}/admin` is acceptable

