import logging
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config

logger = logging.getLogger(__name__)

INCLUDE_EXTENSIONS = {".ts", ".json", ".md"}
EXCLUDE_DIRS = {"node_modules", ".git", "test-results", "reports", ".vscode", "dist"}


def load_codebase() -> list[Document]:
    """
    Walk the Playwright automation codebase and return chunked Documents
    from TypeScript, JSON, and Markdown files.
    """
    logger.info("Loading automation codebase from %s", config.AUTOMATION_CODEBASE_PATH)
    base = Path(config.AUTOMATION_CODEBASE_PATH)

    if not base.exists():
        logger.warning("Codebase path not found: %s", base)
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )

    documents: list[Document] = []

    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in INCLUDE_EXTENSIONS:
            continue
        if any(exc in path.parts for exc in EXCLUDE_DIRS):
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if len(text) < 50:  # Skip near-empty files (e.g., auto-generated index files)
                continue

            relative = path.relative_to(base)
            for i, chunk in enumerate(splitter.split_text(text)):
                documents.append(
                    Document(
                        page_content=chunk,
                        metadata={
                            "source": str(relative),
                            "source_url": f"file://{path}",
                            "source_type": "codebase",
                            "file_type": path.suffix,
                            "chunk_index": i,
                        },
                    )
                )
        except Exception as e:
            logger.warning("Skipped %s: %s", path, e)

    logger.info("Codebase: %d chunks loaded", len(documents))
    return documents
