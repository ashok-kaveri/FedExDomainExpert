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
import logging
import os
from dataclasses import dataclass, field

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
        token: str | None = None,
        channel: str | None = None,
        webhook_url: str | None = None,
    ):
        self.webhook_url  = webhook_url  or os.getenv("SLACK_WEBHOOK_URL", "")
        self.token        = token        or os.getenv("SLACK_BOT_TOKEN", "")
        self.channel      = channel      or os.getenv("SLACK_CHANNEL", "")
        self.mention_on_fail = os.getenv("SLACK_MENTION_ON_FAIL", "")

        # Webhook is preferred — no channel needed
        if not self.webhook_url and not (self.token and self.channel):
            raise ValueError(
                "Slack credentials missing.\n"
                "Set SLACK_WEBHOOK_URL  OR  (SLACK_BOT_TOKEN + SLACK_CHANNEL) in .env"
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
        """Return True if SLACK_BOT_TOKEN and SLACK_CHANNEL are set."""
        return bool(self.token and self.channel)

    def post_signoff_message(
        self,
        release: str,
        verified_cards: list[dict],        # [{"name": str, "url": str}]
        backlog_cards: list[str],           # bug titles added to backlog
        mentions: list[str],               # Slack user IDs or "here" / "channel"
        cc: str = "",                       # single mention for CC line
        qa_lead: str = "",                  # name of QA lead signing off
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
        backlog_block = "\n".join(backlog_cards) if backlog_cards else ""

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
            lines.append("*Cards added to backlog :*")
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
