from __future__ import annotations
import csv
import io
import logging
from pathlib import Path

import requests
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _fetch_public_csv(sheet_id: str) -> list[list[str]]:
    """Download sheet as CSV (works when sheet is publicly readable)."""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        raise ValueError(
            f"Expected CSV but received HTML — sheet may be private or require sign-in. "
            f"Content-Type: {content_type}"
        )
    reader = csv.reader(io.StringIO(resp.text))
    return list(reader)


def _fetch_with_service_account(sheet_id: str, creds_path: str) -> list[list[str]]:
    """Load sheet via service account JSON (for private sheets)."""
    from google.oauth2.service_account import Credentials
    import gspread

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.Client(auth=creds)
    spreadsheet = client.open_by_key(sheet_id)
    all_rows: list[list[str]] = []
    for worksheet in spreadsheet.worksheets():
        all_rows.extend(worksheet.get_all_values())
    return all_rows


def load_test_cases() -> list[Document]:
    """
    Load test cases from Google Sheets.
    Tries service account first, falls back to public CSV export.
    """
    logger.info("Loading Google Sheets test cases...")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )

    rows: list[list[str]] = []
    creds_path = Path(config.GOOGLE_CREDENTIALS_PATH)

    try:
        if creds_path.exists():
            logger.info("Using service account credentials from %s", creds_path)
            rows = _fetch_with_service_account(config.GOOGLE_SHEETS_ID, str(creds_path))
        else:
            logger.info("No credentials.json — trying public CSV access...")
            rows = _fetch_public_csv(config.GOOGLE_SHEETS_ID)
    except Exception as e:
        logger.warning("Primary method failed (%s) — trying public CSV fallback...", e)
        try:
            rows = _fetch_public_csv(config.GOOGLE_SHEETS_ID)
        except Exception as e2:
            logger.error("Both methods failed: %s. Skipping sheets.", e2)
            return []

    # Convert rows to plain text (join cells with " | ")
    text_lines = [
        " | ".join(cell.strip() for cell in row if cell.strip())
        for row in rows
    ]
    full_text = "\n".join(line for line in text_lines if line)

    if not full_text.strip():
        logger.warning("Sheet appears empty — skipping.")
        return []

    sheet_url = f"https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEETS_ID}"
    documents = [
        Document(
            page_content=chunk,
            metadata={
                "source": f"Google Sheets: {config.GOOGLE_SHEETS_ID}",
                "source_url": sheet_url,
                "source_type": "test_cases",
                "chunk_index": i,
            },
        )
        for i, chunk in enumerate(splitter.split_text(full_text))
    ]

    logger.info("Sheets: %d chunks loaded from test cases", len(documents))
    return documents
