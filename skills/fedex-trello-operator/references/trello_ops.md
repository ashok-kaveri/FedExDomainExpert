# Trello Operations

## Project Client

Use `pipeline.trello_client.TrelloClient`.

Important methods:

- `get_boards()`
- `get_lists()`
- `get_cards_in_list(list_id)`
- `get_card(card_id)`
- `get_card_members(card_id)`
- `add_comment(card_id, text)`
- `move_card_to_list(card_id, list_name)`
- `create_card(list_name, name, desc, label_names=None, pos="bottom")`
- `search_cards_on_board(query)`

`get_card()` and `get_cards_in_list()` include attachments, checklists, and plain text comments.

## Card References

Users may provide:

- full Trello URL
- short Trello `/c/<shortlink>/...` URL
- full card ID
- short card ID

The helper script normalizes common URL forms before calling the Trello API.

## Developer Detection

Use `pipeline.bug_reporter.get_card_devs(card_id)`.

It reads assigned Trello card members and filters out QA names:

- Anuja B
- Arshiya Sayed
- Ashok Kumar N
- Basavaraj
- Inderbir Singh
- Keerthanaa Elangovan
- Madan Kumar AS
- Preethi K K
- Shahitha S

Any remaining assigned members are treated as developers.

If no dev is found, tell QA to assign a developer as a Trello card member or give a dev name manually.

## Comment Replies

Trello comments are not true threaded replies in this project wrapper.

To reply to a developer:

1. Add a new comment to the card.
2. Mention the Trello username when available, for example `@username`.
3. Include the QA message and evidence.

Keep comments professional and direct:

```markdown
@devusername QA update:

Observed issue:
...

Expected:
...

Evidence:
...
```

## Board/List Selection

Dashboard flows are workspace-aware. Do not assume one fixed board when the user names another board/list.

If a list name is ambiguous:

1. Fetch boards/lists.
2. Ask only if there is no safe match.
3. Prefer exact case-insensitive list match.

## Write Boundaries

- US/AC: add comment only.
- TC summary: add comment only.
- Bugs: use `fedex-bug` for Backlog creation when possible.
- Handoff docs: attach/comment only when the user asks.
- Do not overwrite descriptions unless the user explicitly asks for a description edit and it is not US/AC generation.
