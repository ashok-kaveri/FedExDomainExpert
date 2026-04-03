"""
RAG Updater  —  Post-approval Knowledge Base Sync
==================================================
After every card cycle (approve → write to Trello + Sheet), embed the card
content into ChromaDB so future validations benefit from accumulated knowledge.

Each card contributes up to 3 logical document groups:
  • {card_id}__description  → feature title + description + release
  • {card_id}__ac           → acceptance criteria
  • {card_id}__test_cases   → approved test cases (all types)

Documents are chunked with the same splitter used by the full ingest pipeline
so they rank consistently with existing knowledge base content.

Re-running for the same card_id replaces the previous entries (upsert semantics):
  delete old chunks for that card → add new chunks with stable prefixed IDs.
"""
import logging
from datetime import datetime, timezone

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config
from rag.vectorstore import upsert_documents

logger = logging.getLogger(__name__)

_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=config.CHUNK_SIZE,
    chunk_overlap=config.CHUNK_OVERLAP,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_rag_from_card(
    card_id: str,
    card_name: str,
    description: str,
    acceptance_criteria: str,
    test_cases: str,
    release: str = "",
) -> dict:
    """
    Embed an approved Trello card into the RAG knowledge base.

    Replaces any previous embedding for the same ``card_id`` (upsert).

    Args:
        card_id:              Trello card ID (stable unique key)
        card_name:            Card title (e.g. "Dry Ice – Additional Services")
        description:          Card body / feature description
        acceptance_criteria:  AC text from the card
        test_cases:           Approved test cases in markdown
        release:              Release label (e.g. "FedExapp 2.3.115")

    Returns:
        {"chunks_added": N, "card_name": card_name, "error": ""}
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        base_meta: dict = {
            "source": "trello_card",
            "card_id": card_id,
            "card_name": card_name,
            "release": release,
            "ingested_at": now,
        }

        # ── Build raw source documents ─────────────────────────────────────
        raw_docs: list[tuple[str, Document]] = []  # (id_base, doc)

        if description and description.strip():
            raw_docs.append((
                f"{card_id}__description",
                Document(
                    page_content=(
                        f"Feature: {card_name}\n"
                        f"Release: {release}\n\n"
                        f"Description:\n{description.strip()}"
                    ),
                    metadata={**base_meta, "doc_type": "description"},
                ),
            ))

        if acceptance_criteria and acceptance_criteria.strip():
            raw_docs.append((
                f"{card_id}__ac",
                Document(
                    page_content=(
                        f"Feature: {card_name}\n\n"
                        f"Acceptance Criteria:\n{acceptance_criteria.strip()}"
                    ),
                    metadata={**base_meta, "doc_type": "acceptance_criteria"},
                ),
            ))

        if test_cases and test_cases.strip():
            raw_docs.append((
                f"{card_id}__test_cases",
                Document(
                    page_content=(
                        f"Feature: {card_name}\n\n"
                        f"Approved Test Cases:\n{test_cases.strip()}"
                    ),
                    metadata={**base_meta, "doc_type": "test_cases"},
                ),
            ))

        if not raw_docs:
            return {"chunks_added": 0, "card_name": card_name, "error": "No content to embed"}

        # ── Split into chunks (same as ingest pipeline) ────────────────────
        all_chunks: list[Document] = []
        all_ids: list[str] = []

        for id_base, doc in raw_docs:
            chunks = _SPLITTER.split_documents([doc])
            for i, chunk in enumerate(chunks):
                all_chunks.append(chunk)
                all_ids.append(f"{id_base}_c{i}")

        # ── Upsert into ChromaDB (delete old → add new) ────────────────────
        upsert_documents(all_chunks, all_ids)

        logger.info(
            "RAG updated for card '%s' [%s] — %d chunk(s) from %d document(s)",
            card_name, release, len(all_chunks), len(raw_docs),
        )
        return {"chunks_added": len(all_chunks), "card_name": card_name, "error": ""}

    except Exception as exc:
        logger.exception("RAG update failed for card '%s': %s", card_name, exc)
        return {"chunks_added": 0, "card_name": card_name, "error": str(exc)}
