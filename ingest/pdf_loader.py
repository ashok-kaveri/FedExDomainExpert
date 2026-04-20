"""
PDF Test Cases Loader
Extracts test case data from a PDF file (e.g. FedExApp Master sheet) and returns
LangChain Documents ready to embed into ChromaDB.

Handles two extraction modes:
  1. Table mode  — pdfplumber table extraction (preserves row structure)
  2. Text mode   — raw page text fallback when no tables are detected

Both modes chunk the output with RecursiveCharacterTextSplitter.
"""
from __future__ import annotations
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_to_text(table: list[list[str | None]], page_num: int) -> str:
    """Convert a pdfplumber table (list of rows) to a readable text block."""
    lines: list[str] = []
    headers: list[str] = []

    for row_idx, row in enumerate(table):
        # Normalise cells
        cells = [str(c).strip() if c is not None else "" for c in row]
        if not any(cells):
            continue

        # First non-empty row is treated as the header row
        if row_idx == 0 or not headers:
            headers = cells
            lines.append("Columns: " + " | ".join(headers))
            continue

        # Build a readable key-value string for each data row
        parts: list[str] = []
        for col_name, cell_val in zip(headers, cells):
            if cell_val:
                parts.append(f"{col_name}: {cell_val}")
        if parts:
            lines.append("; ".join(parts))

    return "\n".join(lines)


def _clean_text(text: str) -> str:
    """Remove excessive whitespace / newlines while keeping paragraph breaks."""
    import re
    # Collapse repeated spaces
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ consecutive newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

def load_pdf_test_cases(pdf_path: str | None = None) -> list[Document]:
    """
    Extract test case content from the master sheet PDF and return chunked Documents.

    Args:
        pdf_path: Path to the PDF file. If omitted, uses PDF_TEST_CASES_PATH.

    Returns:
        List of LangChain Documents ready for ChromaDB ingestion.
    """
    try:
        import pdfplumber  # noqa: PLC0415 – optional dependency
    except ImportError as exc:
        raise ImportError(
            "pdfplumber is required for PDF ingestion.\n"
            "Install it with:  pip install pdfplumber"
        ) from exc

    pdf_source = (pdf_path or config.PDF_TEST_CASES_PATH or "").strip()
    if not pdf_source:
        logger.warning("PDF_TEST_CASES_PATH is not set — skipping PDF ingestion.")
        return []

    path = Path(pdf_source)
    if not path.exists():
        logger.warning("PDF not found at %s — skipping PDF ingestion.", path)
        return []

    logger.info("Loading PDF test cases from %s", path)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )

    all_docs: list[Document] = []
    loaded_at = datetime.now(timezone.utc).isoformat()
    source_uri = path.as_uri()

    with pdfplumber.open(path) as pdf:
        total_pages = len(pdf.pages)
        logger.info("PDF has %d pages", total_pages)

        for page_num, page in enumerate(pdf.pages, start=1):
            page_label = f"Page {page_num}/{total_pages}"

            # ── Try table extraction first ──────────────────────────────────
            tables = page.extract_tables()
            if tables:
                for tbl_idx, table in enumerate(tables):
                    raw = _table_to_text(table, page_num)
                    raw = _clean_text(raw)
                    if len(raw) < 30:
                        continue

                    chunks = splitter.split_text(raw)
                    for chunk in chunks:
                        all_docs.append(
                            Document(
                                page_content=chunk,
                                metadata={
                                    "source": source_uri,
                                    "source_type": "pdf_test_cases",
                                    "file_name": path.name,
                                    "page": page_num,
                                    "table_index": tbl_idx,
                                    "loaded_at": loaded_at,
                                },
                            )
                        )
            else:
                # ── Fallback: raw page text ─────────────────────────────────
                raw = page.extract_text() or ""
                raw = _clean_text(raw)
                if len(raw) < 30:
                    logger.debug("%s — no usable text, skipping.", page_label)
                    continue

                chunks = splitter.split_text(raw)
                for chunk in chunks:
                    all_docs.append(
                        Document(
                            page_content=chunk,
                            metadata={
                                "source": source_uri,
                                "source_type": "pdf_test_cases",
                                "file_name": path.name,
                                "page": page_num,
                                "loaded_at": loaded_at,
                            },
                        )
                    )

    logger.info("PDF loader produced %d chunks from %d pages.", len(all_docs), total_pages)
    return all_docs
