"""
Trello Client
Thin wrapper around the Trello REST API for reading cards and writing
acceptance criteria back to them.

Required .env vars:
    TRELLO_API_KEY   — from https://trello.com/power-ups/admin
    TRELLO_TOKEN     — OAuth token for your account
    TRELLO_BOARD_ID  — the board that holds the delivery pipeline lists
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

TRELLO_BASE = "https://api.trello.com/1"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class TrelloCard:
    id: str
    name: str                       # Raw feature title / one-liner
    desc: str                       # Current card description
    list_id: str
    list_name: str
    labels: list[str] = field(default_factory=list)
    url: str = ""


@dataclass
class TrelloList:
    id: str
    name: str


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class TrelloClient:
    def __init__(
        self,
        api_key: str | None = None,
        token: str | None = None,
        board_id: str | None = None,
    ):
        self.api_key = api_key or os.getenv("TRELLO_API_KEY", "")
        self.token = token or os.getenv("TRELLO_TOKEN", "")
        self.board_id = board_id or os.getenv("TRELLO_BOARD_ID", "")

        if not all([self.api_key, self.token, self.board_id]):
            raise ValueError(
                "Trello credentials missing.\n"
                "Set TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_BOARD_ID in .env"
            )

    # -- helpers -----------------------------------------------------------

    @property
    def _auth(self) -> dict[str, str]:
        return {"key": self.api_key, "token": self.token}

    def _get(self, path: str, **params) -> Any:
        resp = requests.get(
            f"{TRELLO_BASE}/{path}",
            params={**self._auth, **params},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, **data) -> Any:
        resp = requests.put(
            f"{TRELLO_BASE}/{path}",
            params=self._auth,
            json=data,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, **data) -> Any:
        resp = requests.post(
            f"{TRELLO_BASE}/{path}",
            params=self._auth,
            json=data,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    # -- board/list queries ------------------------------------------------

    def get_lists(self) -> list[TrelloList]:
        """Return all lists on the board."""
        raw = self._get(f"boards/{self.board_id}/lists", filter="open")
        return [TrelloList(id=l["id"], name=l["name"]) for l in raw]

    def get_list_by_name(self, name: str) -> TrelloList | None:
        """Find a list by exact name (case-insensitive)."""
        for lst in self.get_lists():
            if lst.name.strip().lower() == name.strip().lower():
                return lst
        return None

    # -- card queries ------------------------------------------------------

    def get_cards_in_list(self, list_id: str) -> list[TrelloCard]:
        """Return all open cards in a list."""
        raw = self._get(f"lists/{list_id}/cards", filter="open")
        cards = []
        for c in raw:
            cards.append(TrelloCard(
                id=c["id"],
                name=c["name"],
                desc=c.get("desc", ""),
                list_id=list_id,
                list_name="",
                labels=[lb["name"] for lb in c.get("labels", [])],
                url=c.get("url", ""),
            ))
        return cards

    def get_backlog_cards(self, list_name: str = "Iteration Backlog") -> list[TrelloCard]:
        """Return cards from the iteration backlog list."""
        lst = self.get_list_by_name(list_name)
        if lst is None:
            logger.warning("List %r not found on board. Available lists: %s",
                           list_name, [l.name for l in self.get_lists()])
            return []
        cards = self.get_cards_in_list(lst.id)
        logger.info("Found %d cards in '%s'", len(cards), list_name)
        return cards

    def get_card(self, card_id: str) -> TrelloCard:
        """Fetch a single card by ID."""
        c = self._get(f"cards/{card_id}")
        return TrelloCard(
            id=c["id"],
            name=c["name"],
            desc=c.get("desc", ""),
            list_id=c["idList"],
            list_name="",
            labels=[lb["name"] for lb in c.get("labels", [])],
            url=c.get("url", ""),
        )

    # -- card mutations ----------------------------------------------------

    def update_card_description(self, card_id: str, new_desc: str) -> None:
        """Overwrite the card description (where AC lives)."""
        self._put(f"cards/{card_id}", desc=new_desc)
        logger.info("Updated description on card %s", card_id)

    def add_comment(self, card_id: str, text: str) -> None:
        """Add a comment to a card (e.g. pipeline status updates)."""
        self._post(f"cards/{card_id}/actions/comments", text=text)
        logger.info("Added comment to card %s", card_id)

    def add_label(self, card_id: str, label_color: str, label_name: str) -> None:
        """Add a coloured label to a card."""
        # Get or create label on the board
        labels = self._get(f"boards/{self.board_id}/labels")
        label_id = None
        for lb in labels:
            if lb.get("name") == label_name and lb.get("color") == label_color:
                label_id = lb["id"]
                break
        if not label_id:
            new_label = self._post(
                f"boards/{self.board_id}/labels",
                name=label_name,
                color=label_color,
            )
            label_id = new_label["id"]
        self._post(f"cards/{card_id}/idLabels", value=label_id)
        logger.info("Added label '%s' to card %s", label_name, card_id)

    def move_card_to_list(self, card_id: str, list_name: str) -> None:
        """Move a card to a different list by name."""
        lst = self.get_list_by_name(list_name)
        if lst is None:
            raise ValueError(f"List '{list_name}' not found on board.")
        self._put(f"cards/{card_id}", idList=lst.id)
        logger.info("Moved card %s to '%s'", card_id, list_name)
