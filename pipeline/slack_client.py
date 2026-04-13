"""
Slack Client  —  Pipeline Notifications
=========================================
Posts automation run results and release summaries to a Slack channel.

Supports two modes (webhook is simpler and preferred):

  Mode 1 — Incoming Webhook (preferred):
    SLACK_WEBHOOK_URL  — from api.slack.com/apps → Incoming Webhooks

  Mode 2 — Bot Token:
    SLACK_BOT_TOKEN    — xoxb-... token
    SLACK_CHANNEL      — Channel ID (C09F65XF4ER) or name (#qa-automation)

Optional:
    SLACK_MENTION_ON_FAIL — user/group to @mention on failures (e.g. U0123456789 or !here)
"""
from __future__ import annotations
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TestRunResult:
    release: str
    total: int
    passed: int
    failed: int
    skipped: int
    duration_secs: float
    failed_tests: list[str] = field(default_factory=list)   # test titles that failed
    failed_specs: list[str] = field(default_factory=list)   # spec file paths that failed
    card_results: list[dict] = field(default_factory=list)  # [{card_name, spec, passed, failed}]
    branch: str = ""
    run_url: str = ""   # link to CI run if available

    @property
    def status(self) -> str:
        return "✅ PASSED" if self.failed == 0 else "❌ FAILED"

    @property
    def pass_rate(self) -> str:
        if self.total == 0:
            return "0%"
        return f"{int(self.passed / self.total * 100)}%"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class SlackClient:
    def __init__(
        self,
        token: Optional[str] = None,
        channel: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ):
        self.webhook_url  = webhook_url  or os.getenv("SLACK_WEBHOOK_URL", "")
        self.token        = token        or os.getenv("SLACK_BOT_TOKEN", "")
        self.channel      = channel      or os.getenv("SLACK_CHANNEL", "")
        self.mention_on_fail = os.getenv("SLACK_MENTION_ON_FAIL", "")

        # Webhook is preferred — no channel needed.
        # Allow DM-only usage: token alone is enough (channel may be a placeholder).
        if not self.webhook_url and not self.token:
            raise ValueError(
                "Slack credentials missing.\n"
                "Set SLACK_WEBHOOK_URL  OR  SLACK_BOT_TOKEN in .env"
            )

    def _post(self, payload: dict) -> dict:
        """Post to Slack via webhook (preferred) or bot token API."""
        if self.webhook_url:
            # Incoming Webhook — simpler, no channel needed in payload
            resp = requests.post(
                self.webhook_url,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            # Webhook returns plain "ok" text, not JSON
            return {"ok": True, "ts": ""}

        # Bot token fallback
        payload["channel"] = self.channel
        resp = requests.post(
            f"{SLACK_API}/chat.postMessage",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")
        return data

    # ── DM helpers (require bot token — webhook cannot open DMs) ────────────

    def _bot_headers(self) -> dict:
        """Return Authorization headers for bot-token API calls."""
        if not self.token:
            raise RuntimeError(
                "Slack DM requires SLACK_BOT_TOKEN. "
                "A webhook URL alone cannot open direct messages."
            )
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def search_users(self, query: str) -> list[dict]:
        """
        Search workspace members by display name or real name.

        Paginates through the full workspace member list (users.list is paginated).
        Returns a list of dicts: [{"id": str, "name": str, "display_name": str}]
        Requires SLACK_BOT_TOKEN with users:read scope.
        Raises RuntimeError with a clear message on API errors (missing scope, etc).
        """
        query = query.strip().lower()
        if not query:
            return []

        all_members: list[dict] = []
        cursor = ""

        # Paginate through all workspace members
        while True:
            params: dict = {"limit": 200}
            if cursor:
                params["cursor"] = cursor

            resp = requests.get(
                f"{SLACK_API}/users.list",
                headers=self._bot_headers(),
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("ok"):
                error = data.get("error", "unknown")
                if error == "missing_scope":
                    raise RuntimeError(
                        "Bot token is missing the 'users:read' scope. "
                        "Go to api.slack.com/apps → OAuth & Permissions → "
                        "Bot Token Scopes → add 'users:read', then reinstall the app."
                    )
                raise RuntimeError(f"Slack users.list error: {error}")

            all_members.extend(data.get("members", []))

            # Follow pagination cursor
            cursor = (data.get("response_metadata") or {}).get("next_cursor", "")
            if not cursor:
                break

        results = []
        for member in all_members:
            if member.get("deleted") or member.get("is_bot") or member.get("id") == "USLACKBOT":
                continue
            profile      = member.get("profile", {})
            real_name    = (profile.get("real_name") or "").lower()
            display_name = (profile.get("display_name") or "").lower()
            username     = (member.get("name") or "").lower()
            # Also check first/last name separately for partial matches
            first_name   = (profile.get("first_name") or "").lower()
            last_name    = (profile.get("last_name") or "").lower()

            if any(
                query in field
                for field in (real_name, display_name, username, first_name, last_name)
                if field
            ):
                results.append({
                    "id":           member["id"],
                    "name":         profile.get("real_name") or member["name"],
                    "display_name": profile.get("display_name") or member["name"],
                })

        logger.info(
            "Slack user search '%s': scanned %d members, found %d matches",
            query, len(all_members), len(results),
        )
        return results

    def send_dm(self, user_id: str, text: str) -> str:
        """
        Send a direct message to a Slack user.

        Opens (or reuses) a DM conversation, then posts the message.
        Returns the message timestamp (ts).
        Requires SLACK_BOT_TOKEN with im:write + chat:write scopes.
        """
        # Step 1: open/get the DM channel
        open_resp = requests.post(
            f"{SLACK_API}/conversations.open",
            headers=self._bot_headers(),
            json={"users": user_id},
            timeout=15,
        )
        open_resp.raise_for_status()
        open_data = open_resp.json()
        if not open_data.get("ok"):
            raise RuntimeError(
                f"conversations.open error: {open_data.get('error', 'unknown')}"
            )
        dm_channel = open_data["channel"]["id"]

        # Step 2: post the message
        msg_resp = requests.post(
            f"{SLACK_API}/chat.postMessage",
            headers=self._bot_headers(),
            json={"channel": dm_channel, "text": text, "mrkdwn": True},
            timeout=15,
        )
        msg_resp.raise_for_status()
        msg_data = msg_resp.json()
        if not msg_data.get("ok"):
            raise RuntimeError(
                f"chat.postMessage DM error: {msg_data.get('error', 'unknown')}"
            )

        ts = msg_data.get("ts", "")
        logger.info("Sent DM to user %s (ts=%s)", user_id, ts)
        return ts

    # ── Public methods ───────────────────────────────────────────────────────

    def post_test_results(self, result: TestRunResult) -> str:
        """
        Post a formatted test run summary to the configured Slack channel.

        Returns the Slack message timestamp (ts) for threading.
        """
        mention = f"<@{self.mention_on_fail}> " if self.mention_on_fail and result.failed > 0 else ""
        status_emoji = "✅" if result.failed == 0 else "❌"

        # ── Header block ──────────────────────────────────────────────────
        header_text = (
            f"{status_emoji} *FedEx Automation — {result.release}*\n"
            f"{mention}"
            f"*{result.status}* · "
            f"{result.passed}/{result.total} tests passed "
            f"({result.pass_rate}) · "
            f"{result.duration_secs:.0f}s"
        )

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{status_emoji} FedEx Automation — {result.release}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Status:*\n{result.status}"},
                    {"type": "mrkdwn", "text": f"*Pass Rate:*\n{result.pass_rate}"},
                    {"type": "mrkdwn", "text": f"*Tests:*\n{result.passed} ✅  {result.failed} ❌  {result.skipped} ⏭️"},
                    {"type": "mrkdwn", "text": f"*Duration:*\n{result.duration_secs:.0f}s"},
                ],
            },
        ]

        # ── Branch / run link ─────────────────────────────────────────────
        if result.branch or result.run_url:
            context_elements = []
            if result.branch:
                context_elements.append({"type": "mrkdwn", "text": f"🌿 Branch: `{result.branch}`"})
            if result.run_url:
                context_elements.append({"type": "mrkdwn", "text": f"🔗 <{result.run_url}|View CI Run>"})
            blocks.append({"type": "context", "elements": context_elements})

        # ── Per-card results ──────────────────────────────────────────────
        if result.card_results:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Per-card results:*"},
            })
            for cr in result.card_results:
                icon = "✅" if cr.get("failed", 0) == 0 else "❌"
                spec = cr.get("spec", "")
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"{icon} *{cr['card_name']}*\n"
                            f"  `{spec}` — "
                            f"{cr.get('passed', 0)} passed · {cr.get('failed', 0)} failed"
                        ),
                    },
                })

        # ── Failed test list ──────────────────────────────────────────────
        if result.failed_tests:
            failed_lines = "\n".join(f"• {t}" for t in result.failed_tests[:10])
            if len(result.failed_tests) > 10:
                failed_lines += f"\n…and {len(result.failed_tests) - 10} more"
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*❌ Failed tests:*\n{failed_lines}",
                },
            })

        blocks.append({"type": "divider"})

        payload = {
            "channel": self.channel,
            "text": header_text,   # fallback for notifications
            "blocks": blocks,
        }

        data = self._post(payload)
        ts = data.get("ts", "")
        logger.info("Posted test results to Slack (ts=%s)", ts)
        return ts

    def post_message(self, text: str, thread_ts: str = "") -> str:
        """Post a plain text message (optionally as a thread reply)."""
        payload: dict = {"channel": self.channel, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        data = self._post(payload)
        return data.get("ts", "")

    def is_configured(self) -> bool:
        """Return True if webhook URL OR (bot token + channel) are configured."""
        return bool(self.webhook_url or (self.token and self.channel))

    def post_signoff_message(
        self,
        release: str,
        verified_cards: list[dict],        # [{"name": str, "url": str}]
        backlog_cards: list[str],           # bug titles added to backlog (plain text fallback)
        mentions: list[str],               # Slack user IDs or "here" / "channel"
        cc: str = "",                       # single mention for CC line
        qa_lead: str = "",                  # name of QA lead signing off
        backlog_links: Optional[list] = None,  # [{"name": str, "url": str, "severity": str}]
    ) -> str:
        """
        Post a QA sign-off message to Slack in the standard team format:

            @here @alice @bob

            We've completed testing  RELEASE  and it's good for the release ✅

            Cards Verified:

            Card Name
            https://trello.com/c/xxx

            Cards added to backlog :

            Bug title 1
            Bug title 2

            QA Signed off 🎉

            CC: @manager

        Returns the Slack message timestamp (ts).
        """
        # ── Build mention string ──────────────────────────────────────────
        mention_parts = []
        for m in mentions:
            if m in ("here", "channel", "everyone"):
                mention_parts.append(f"<!{m}>")
            elif m.startswith("U") or m.startswith("W"):
                mention_parts.append(f"<@{m}>")
            else:
                mention_parts.append(f"@{m}")
        mention_line = "  ".join(mention_parts)

        # ── Build verified cards block ────────────────────────────────────
        if verified_cards:
            cards_block = "\n\n".join(
                f"{c['name']}\n{c['url']}" if c.get("url") else c["name"]
                for c in verified_cards
            )
        else:
            cards_block = "(none)"

        # ── Build backlog block ───────────────────────────────────────────
        # Prefer rich backlog_links (with URLs) over plain backlog_cards strings
        _bug_dicts = backlog_links if backlog_links else []

        if _bug_dicts:
            # Format each bug as a Slack link "<url|name>" when a URL is available
            bug_lines = []
            for b in _bug_dicts:
                name = b.get("name", "")
                url  = b.get("url", "")
                sev  = b.get("severity", "")
                prefix = f"{sev} — " if sev else ""
                if url:
                    bug_lines.append(f"{prefix}<{url}|{name}>")
                else:
                    bug_lines.append(f"{prefix}{name}")
            backlog_block = "\n".join(bug_lines)
            backlog_count = len(_bug_dicts)
        elif backlog_cards:
            backlog_block = "\n".join(backlog_cards)
            backlog_count = len(backlog_cards)
        else:
            backlog_block = ""
            backlog_count = 0

        # ── Assemble full message text ────────────────────────────────────
        lines = [mention_line, ""]
        lines.append(
            f"We've completed testing  *{release}*  and it's good for the release :white_check_mark:"
        )
        lines.append("")
        lines.append("*Cards Verified:*")
        lines.append("")
        lines.append(cards_block)
        lines.append("")

        if backlog_block:
            lines.append(f"*Cards added to backlog ({backlog_count}):*")
            lines.append("")
            lines.append(backlog_block)
            lines.append("")

        lines.append("*QA Signed off* :tada:")

        if cc:
            lines.append("")
            cc_fmt = f"<@{cc}>" if (cc.startswith("U") or cc.startswith("W")) else f"@{cc}"
            lines.append(f"CC: {cc_fmt}")

        if qa_lead:
            lines.append(f"_Signed by: {qa_lead}_")

        text = "\n".join(lines)

        payload = {
            "channel": self.channel,
            "text": text,
            # Use mrkdwn block so links and formatting render properly
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                }
            ],
        }
        data = self._post(payload)
        ts = data.get("ts", "")
        logger.info("Posted sign-off message to Slack (ts=%s)", ts)
        return ts


# ---------------------------------------------------------------------------
# Convenience helper (used by dashboard + test runner)
# ---------------------------------------------------------------------------

def post_results(result: TestRunResult) -> dict:
    """
    Post test results to Slack. Returns {"ok": bool, "ts": str, "error": str}.
    Safe to call — catches all exceptions and returns error dict instead of raising.
    """
    try:
        client = SlackClient()
        ts = client.post_test_results(result)
        return {"ok": True, "ts": ts, "error": ""}
    except ValueError as e:
        # Missing credentials — not configured yet
        return {"ok": False, "ts": "", "error": str(e)}
    except Exception as e:
        logger.exception("Slack post failed")
        return {"ok": False, "ts": "", "error": str(e)}


def post_signoff(
    release: str,
    verified_cards: list[dict],
    backlog_cards: list[str],
    mentions: list[str],
    cc: str = "",
    qa_lead: str = "",
    backlog_links: Optional[list] = None,  # [{"name": str, "url": str, "severity": str}]
) -> dict:
    """
    Post a QA sign-off message to Slack.
    Returns {"ok": bool, "ts": str, "error": str}.
    Safe to call — never raises.
    """
    try:
        client = SlackClient()
        ts = client.post_signoff_message(
            release=release,
            verified_cards=verified_cards,
            backlog_cards=backlog_cards,
            mentions=mentions,
            cc=cc,
            qa_lead=qa_lead,
            backlog_links=backlog_links,
        )
        return {"ok": True, "ts": ts, "error": ""}
    except ValueError as e:
        return {"ok": False, "ts": "", "error": str(e)}
    except Exception as e:
        logger.exception("Slack sign-off post failed")
        return {"ok": False, "ts": "", "error": str(e)}


def slack_configured() -> bool:
    """Return True if any Slack delivery method is configured."""
    webhook = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    token   = os.getenv("SLACK_BOT_TOKEN", "").strip()
    channel = os.getenv("SLACK_CHANNEL", "").strip()
    return bool(webhook) or bool(token and channel)


def dm_token_configured() -> bool:
    """Return True if a bot token is available (required for DMs and user search)."""
    return bool(os.getenv("SLACK_BOT_TOKEN", "").strip())


def search_slack_users(query: str) -> tuple[list[dict], str]:
    """
    Search Slack workspace members by name.

    Returns (results, error_message).
      - On success: (list of user dicts, "")
      - On failure: ([], human-readable error string)
    """
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if not token:
        return [], "SLACK_BOT_TOKEN is not set in .env"
    try:
        client = SlackClient(token=token, channel="dm-only-placeholder")
        results = client.search_users(query)
        return results, ""
    except Exception as e:
        logger.warning("Slack user search failed: %s", e)
        return [], str(e)


def list_slack_channels() -> tuple[list[dict], str, str]:
    """
    Fetch all Slack channels visible to the bot.

    Returns (channels, error_message, note).
      - channels:  list of {"id": str, "name": str, "is_private": bool}
      - error_msg: non-empty string on failure, "" on success
      - note:      informational message to show in the UI (always non-empty)

    Slack API limitation: private channels are ONLY returned if the bot has
    been invited to them (/invite @BotName inside the channel in Slack).
    The groups:read scope alone is not enough to list all private channels.
    Safe to call — never raises.
    """
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if not token:
        return [], "SLACK_BOT_TOKEN is not set in .env", ""
    try:
        channels: list[dict] = []
        cursor = ""
        while True:
            params: dict = {
                "types": "public_channel,private_channel",
                "exclude_archived": "true",
                "limit": 200,
            }
            if cursor:
                params["cursor"] = cursor

            resp = requests.get(
                f"{SLACK_API}/conversations.list",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("ok"):
                error = data.get("error", "unknown")
                if error == "missing_scope":
                    return [], (
                        "Bot token is missing the 'channels:read' scope. "
                        "Go to api.slack.com/apps → OAuth & Permissions → "
                        "Bot Token Scopes → add 'channels:read' (and 'groups:read' for private), "
                        "then reinstall the app."
                    ), ""
                return [], f"Slack conversations.list error: {error}", ""

            for ch in data.get("channels", []):
                channels.append({
                    "id":         ch["id"],
                    "name":       ch.get("name", ch["id"]),
                    "is_private": ch.get("is_private", False),
                })

            cursor = (data.get("response_metadata") or {}).get("next_cursor", "")
            if not cursor:
                break

        channels.sort(key=lambda c: c["name"])
        private_count = sum(1 for c in channels if c["is_private"])
        note = (
            f"Showing {len(channels)} channels ({private_count} private). "
            "🔒 To see a private channel here, open it in Slack and run `/invite @domainexpert`."
        )
        logger.info("Fetched %d Slack channels (%d private)", len(channels), private_count)
        return channels, "", note
    except Exception as exc:
        logger.debug("Slack channel list failed: %s", exc)
        return [], str(exc), ""


def post_content_to_slack_channel(
    channel_id: str,
    card_name: str,
    content_text: str,
    content_label: str = "Acceptance Criteria",
    card_url: str = "",
) -> dict:
    """
    Post formatted AC or Test Cases to a Slack channel.

    Args:
        channel_id:    Slack channel ID (C…)
        card_name:     Trello card name — shown in the header
        content_text:  The AC or TC markdown to post
        content_label: Human-readable label ("Acceptance Criteria" or "Test Cases")
        card_url:      Optional Trello card link shown in the post

    Returns {"ok": bool, "ts": str, "error": str}.
    Requires SLACK_BOT_TOKEN with chat:write scope and the bot being in the channel.
    Safe to call — never raises.
    """
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if not token:
        return {"ok": False, "ts": "", "error": "SLACK_BOT_TOKEN is not set"}
    try:
        header = f"📋 *{content_label} — {card_name}*"
        if card_url:
            header += f"\n🔗 <{card_url}|View Trello Card>"

        text = f"{header}\n\n{content_text}"

        blocks: list[dict] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{content_label} — {card_name}",
                    "emoji": True,
                },
            },
        ]
        if card_url:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"🔗 <{card_url}|View Trello Card>"}],
            })
        # Slack block text limit is 3000 chars — split if needed
        chunk1 = content_text[:2900]
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk1}})
        if len(content_text) > 2900:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": content_text[2900:]},
            })

        resp = requests.post(
            f"{SLACK_API}/chat.postMessage",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "channel": channel_id,
                "text": text,
                "blocks": blocks,
                "mrkdwn": True,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            error = data.get("error", "unknown")
            if error == "not_in_channel":
                return {
                    "ok": False, "ts": "",
                    "error": (
                        "Bot is not a member of that channel. "
                        "Open the channel in Slack → Details → Integrations → Add apps, "
                        "then try again."
                    ),
                }
            return {"ok": False, "ts": "", "error": f"Slack error: {error}"}
        ts = data.get("ts", "")
        logger.info("Posted %s to channel %s (ts=%s)", content_label, channel_id, ts)
        return {"ok": True, "ts": ts, "error": ""}
    except Exception as exc:
        logger.debug("post_content_to_slack_channel failed: %s", exc)
        return {"ok": False, "ts": "", "error": str(exc)}


def send_ac_dm(
    user_ids: "str | list[str]",
    card_name: str,
    ac_text: str,
    content_label: str = "Acceptance Criteria",
) -> dict:
    """
    Send generated AC or Test Cases for a card as a Slack DM.

    Args:
        user_ids:      One Slack user ID (str) or a list of user IDs.
                       Each user gets their own individual DM.
        card_name:     Trello card name — shown in the DM header
        ac_text:       The content to send (AC markdown or TC markdown)
        content_label: Human-readable label, e.g. "Acceptance Criteria" or "Test Cases"

    Returns {"ok": bool, "sent": int, "failed": int, "error": str}.
    Safe to call — never raises.
    """
    # Normalise to list
    ids: list[str] = [user_ids] if isinstance(user_ids, str) else list(user_ids)
    if not ids:
        return {"ok": False, "sent": 0, "failed": 0, "error": "No recipients specified"}

    try:
        token = os.getenv("SLACK_BOT_TOKEN", "").strip()
        if not token:
            return {"ok": False, "sent": 0, "failed": 0, "error": "SLACK_BOT_TOKEN is not set"}

        client = SlackClient(token=token, channel="dm-only-placeholder")
        text = (
            f"👋 *{content_label} — {card_name}*\n\n"
            f"{ac_text}\n\n"
            f"_Please review the {content_label.lower()} above._"
        )

        sent, failed, errors = 0, 0, []
        for uid in ids:
            try:
                client.send_dm(user_id=uid, text=text)
                sent += 1
                logger.info("DM sent to %s for card '%s'", uid, card_name)
            except Exception as e:
                failed += 1
                errors.append(f"{uid}: {e}")
                logger.warning("DM failed for %s: %s", uid, e)

        ok  = failed == 0
        err = "; ".join(errors) if errors else ""
        return {"ok": ok, "sent": sent, "failed": failed, "error": err}

    except Exception as e:
        logger.exception("DM send failed")
        return {"ok": False, "sent": 0, "failed": 0, "error": str(e)}


# ---------------------------------------------------------------------------
# Toggle Notification helpers
# ---------------------------------------------------------------------------

def detect_toggles(card_desc: str, card_name: str = "") -> list[str]:
    """
    Extract toggle / feature-flag names from a card description.

    Detects:
      - Explicit "toggle:" labels (case-insensitive)
      - Shopify webhook flags  (all.myshopify.com/shopify.webhook.*)
      - Common flag patterns   ("enable X toggle", "X flag", "X feature flag")

    Returns a deduplicated list of toggle names (human-readable).
    """
    import re
    toggles: list[str] = []
    seen: set[str] = set()

    text = f"{card_name}\n{card_desc}"

    # Pattern 1 — explicit "toggle: <name>" label (handles multi-line like the screenshot)
    for m in re.finditer(r'toggle[:\s]+([^\n"]{3,80})', text, re.IGNORECASE):
        name = m.group(1).strip().strip('"').strip("'").rstrip(",")
        if name and name.lower() not in seen:
            toggles.append(name)
            seen.add(name.lower())

    # Pattern 2 — Shopify webhook / feature flag JSON keys
    # e.g. "all.myshopify.com.shopify.webhook.products.with.more.than.100.variants.enabled"
    for m in re.finditer(
        r'"((?:all\.myshopify\.com\.)?shopify\.(?:webhook|feature)[^"]{5,120})"',
        text,
    ):
        raw = m.group(1)
        # Convert dot-notation to readable name
        readable = raw.replace("all.myshopify.com.", "").replace("shopify.webhook.", "").replace("shopify.feature.", "").replace(".", " ").strip()
        if readable.lower() not in seen:
            toggles.append(readable)
            seen.add(readable.lower())

    # Pattern 3 — "enable X toggle" / "X flag" / "X feature flag"
    for m in re.finditer(
        r'\b(?:enable|activate|turn on|add)\s+["\']?([A-Za-z0-9 _\-]{4,60}?)["\']?\s+(?:toggle|flag|feature flag)\b',
        text, re.IGNORECASE,
    ):
        name = m.group(1).strip()
        if name.lower() not in seen:
            toggles.append(name)
            seen.add(name.lower())

    return toggles


def notify_toggle_enablement(
    user_id: str,
    card_name: str,
    toggles: list[str],
    store_name: str,
    store_url: str = "",
) -> dict:
    """
    Send a Slack DM to a user (e.g. Ashok) asking them to enable
    specific feature toggles on a store before QA begins.

    Returns the message timestamp {"ts": str, "channel": str} so we
    can poll for their reply later, or {"error": str} on failure.
    """
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if not token:
        return {"ok": False, "error": "SLACK_BOT_TOKEN is not set"}

    if not user_id:
        return {"ok": False, "error": "No user_id provided"}

    toggle_lines = "\n".join(f"  • `{t}`" for t in toggles)
    admin_url = store_url or f"https://{store_name}.myshopify.com/admin"

    text = (
        f"🔧 *Toggle Enable Request — {card_name}*\n\n"
        f"QA is about to start on this card and requires the following "
        f"toggle(s) to be enabled on *{store_name}*:\n\n"
        f"{toggle_lines}\n\n"
        f"🔗 Store admin: {admin_url}\n\n"
        f"Please enable the toggle(s) above and *reply `done`* to this message "
        f"so the QA pipeline knows to proceed. Thanks! 🙏"
    )

    try:
        client = SlackClient(token=token, channel="dm-only-placeholder")

        # Open DM channel
        open_resp = requests.post(
            f"{SLACK_API}/conversations.open",
            headers=client._bot_headers(),
            json={"users": user_id},
            timeout=15,
        )
        open_resp.raise_for_status()
        open_data = open_resp.json()
        if not open_data.get("ok"):
            return {"ok": False, "error": f"conversations.open: {open_data.get('error')}"}
        dm_channel = open_data["channel"]["id"]

        # Post message
        msg_resp = requests.post(
            f"{SLACK_API}/chat.postMessage",
            headers=client._bot_headers(),
            json={"channel": dm_channel, "text": text, "mrkdwn": True},
            timeout=15,
        )
        msg_resp.raise_for_status()
        msg_data = msg_resp.json()
        if not msg_data.get("ok"):
            return {"ok": False, "error": f"chat.postMessage: {msg_data.get('error')}"}

        ts = msg_data.get("ts", "")
        logger.info("Toggle notification sent to %s (ts=%s channel=%s)", user_id, ts, dm_channel)
        return {"ok": True, "ts": ts, "channel": dm_channel}

    except Exception as e:
        logger.exception("notify_toggle_enablement failed")
        return {"ok": False, "error": str(e)}


def check_toggle_reply(channel_id: str, after_ts: str) -> dict:
    """
    Check if the recipient has replied with "done" (or similar) in the DM
    channel after the message at after_ts.

    Returns:
      {"confirmed": True,  "reply": "<text>", "ts": "<reply_ts>"}   — confirmed
      {"confirmed": False, "reply": "",        "ts": ""}             — no reply yet
      {"confirmed": False, "error": "<msg>"}                         — API error
    """
    import time as _time
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if not token:
        return {"confirmed": False, "error": "SLACK_BOT_TOKEN is not set"}

    _DONE_KEYWORDS = {"done", "yes", "enabled", "ok", "okay", "completed",
                      "toggled", "activated", "ready", "turned on", "✅", "👍"}

    try:
        resp = requests.get(
            f"{SLACK_API}/conversations.history",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "channel": channel_id,
                "oldest":  after_ts,   # only messages AFTER our notification
                "limit":   10,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("ok"):
            return {"confirmed": False, "error": data.get("error", "unknown")}

        for msg in data.get("messages", []):
            # Skip our own bot message (subtype = bot_message)
            if msg.get("subtype") == "bot_message":
                continue
            text = (msg.get("text") or "").strip().lower()
            if any(kw in text for kw in _DONE_KEYWORDS):
                return {
                    "confirmed": True,
                    "reply":     msg.get("text", ""),
                    "ts":        msg.get("ts", ""),
                }

        return {"confirmed": False, "reply": "", "ts": ""}

    except Exception as e:
        logger.warning("check_toggle_reply failed: %s", e)
        return {"confirmed": False, "error": str(e)}
