from __future__ import annotations
import logging
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config

logger = logging.getLogger(__name__)

# ── Defaults for the automation codebase ─────────────────────────────────────
_DEFAULT_EXTENSIONS: set[str] = {".ts", ".json", ".md"}
_DEFAULT_EXCLUDE_DIRS: set[str] = {
    "node_modules", ".git", "test-results", "reports", ".vscode", "dist",
    ".claude",          # excludes worktrees (duplicate files) + agent/skill .md definitions
}
_DEFAULT_EXCLUDE_FILES: set[str] = {
    "package-lock.json",   # npm dependency tree — no QA value, 500 chunks
    "auth.json",           # session tokens — no QA value
    "test-history.json",   # test run records — low signal
    "yarn.lock",           # yarn lockfile — no QA value
}
_DEFAULT_EXCLUDE_MD_PATTERNS: set[str] = {
    "fedExSkill.md",       # Claude skill definitions, not app knowledge
    "fedExDebugSkill.md",
}


def _load_code_directory(
    base: Path,
    source_type: str,
    extensions: set[str],
    exclude_dirs: set[str],
    exclude_files: set[str],
    exclude_md_patterns: set[str],
) -> list[Document]:
    """Generic code directory walker — shared by all code loaders."""
    if not base.exists():
        logger.warning("Code path not found: %s — skipping", base)
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )

    documents: list[Document] = []

    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in extensions:
            continue
        if any(exc in path.parts for exc in exclude_dirs):
            continue
        if path.name in exclude_files:
            continue
        if path.name in exclude_md_patterns:
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if len(text) < 50:
                continue

            relative = path.relative_to(base)
            for i, chunk in enumerate(splitter.split_text(text)):
                documents.append(
                    Document(
                        page_content=chunk,
                        metadata={
                            "source":      str(relative),
                            "source_url":  f"file://{path}",
                            "source_type": source_type,
                            "file_type":   path.suffix,
                            "file_path":   str(path),
                            "chunk_index": i,
                        },
                    )
                )
        except Exception as e:
            logger.warning("Skipped %s: %s", path, e)

    return documents


def load_codebase(
    path: str | None = None,
    source_type: str = "codebase",
    extensions: list[str] | None = None,
    exclude_dirs: list[str] | None = None,
) -> list[Document]:
    """Walk a code directory and return chunked LangChain Documents.

    Default behaviour (no args) loads the Playwright automation codebase
    using the preset extension/exclusion lists.

    Args:
        path:         Root directory to walk. If omitted, uses AUTOMATION_CODEBASE_PATH.
        source_type:  ChromaDB ``source_type`` tag. Defaults to ``"codebase"``.
        extensions:   File extensions to include (e.g. [".js", ".json"]).
                      Defaults to {".ts", ".json", ".md"}.
        exclude_dirs: Directory names to skip (in addition to default excludes).
    """
    if path is not None:
        base_path = path
    else:
        base_path = config.AUTOMATION_CODEBASE_PATH or ""
    if not base_path:
        logger.warning("No codebase path configured for source_type=%s — skipping.", source_type)
        return []

    base = Path(base_path)
    logger.info("Loading %s from %s", source_type, base)

    exts = set(extensions) if extensions else _DEFAULT_EXTENSIONS
    ex_dirs = _DEFAULT_EXCLUDE_DIRS | set(exclude_dirs or [])

    docs = _load_code_directory(
        base=base,
        source_type=source_type,
        extensions=exts,
        exclude_dirs=ex_dirs,
        exclude_files=_DEFAULT_EXCLUDE_FILES,
        exclude_md_patterns=_DEFAULT_EXCLUDE_MD_PATTERNS,
    )

    logger.info("%s: %d chunks loaded from %s", source_type, len(docs), base)
    return docs
