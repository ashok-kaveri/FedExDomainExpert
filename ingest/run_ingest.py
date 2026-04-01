#!/usr/bin/env python3
"""
Master ingestion pipeline.
Clears the knowledge base and rebuilds it from all configured sources.

Usage:
    python ingest/run_ingest.py                    # Ingest all sources
    python ingest/run_ingest.py --sources codebase # Only index codebase
    python ingest/run_ingest.py --sources pluginhive fedex
"""
import argparse
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def run_ingest(sources: list[str] | None = None) -> None:
    from rag.vectorstore import clear_collection, add_documents
    from ingest.web_scraper import scrape_pluginhive_docs, scrape_fedex_api_docs
    from ingest.codebase_loader import load_codebase
    from ingest.sheets_loader import load_test_cases

    ingest_all = sources is None
    start = time.time()

    print("=" * 60)
    print("FedEx Domain Expert — Knowledge Base Ingestion")
    print("=" * 60)
    logger.info("Clearing existing knowledge base...")
    clear_collection()

    all_documents = []

    if ingest_all or "pluginhive" in sources:
        all_documents.extend(scrape_pluginhive_docs())

    if ingest_all or "fedex" in sources:
        all_documents.extend(scrape_fedex_api_docs())

    if ingest_all or "codebase" in sources:
        all_documents.extend(load_codebase())

    if ingest_all or "sheets" in sources:
        all_documents.extend(load_test_cases())

    if not all_documents:
        logger.error("No documents loaded. Check your sources and try again.")
        sys.exit(1)

    logger.info("Embedding and storing %d chunks in ChromaDB...", len(all_documents))
    add_documents(all_documents)

    elapsed = time.time() - start
    print(f"\n✅ Done: {len(all_documents)} chunks indexed in {elapsed:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rebuild FedEx Domain Expert knowledge base")
    parser.add_argument(
        "--sources",
        nargs="*",
        choices=["pluginhive", "fedex", "codebase", "sheets"],
        help="Which sources to ingest (default: all)",
    )
    args = parser.parse_args()
    run_ingest(args.sources)
