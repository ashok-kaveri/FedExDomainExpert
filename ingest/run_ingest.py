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


_DEFAULT_SOURCES = ["pluginhive", "shopify", "fedex", "codebase", "pdf"]
# "sheets" is excluded from the default run — the PDF master sheet covers the same data.
# Use --sources sheets to include it explicitly if needed.


def run_ingest(sources: list[str] | None = None) -> None:
    from rag.vectorstore import clear_collection, add_documents
    from ingest.web_scraper import scrape_pluginhive_docs, scrape_fedex_api_docs, scrape_shopify_app_store
    from ingest.codebase_loader import load_codebase
    from ingest.sheets_loader import load_test_cases
    from ingest.pdf_loader import load_pdf_test_cases

    active_sources = sources if sources is not None else _DEFAULT_SOURCES
    ingest_all = False  # always use the explicit source list
    start = time.time()

    print("=" * 60)
    print("FedEx Domain Expert — Knowledge Base Ingestion")
    print(f"Sources: {', '.join(active_sources)}")
    print("=" * 60)
    logger.info("Clearing existing knowledge base...")
    clear_collection()

    all_documents = []

    if "pluginhive" in active_sources:
        all_documents.extend(scrape_pluginhive_docs())

    if "shopify" in active_sources:
        all_documents.extend(scrape_shopify_app_store())

    if "fedex" in active_sources:
        all_documents.extend(scrape_fedex_api_docs())

    if "codebase" in active_sources:
        all_documents.extend(load_codebase())

    if "sheets" in active_sources:
        all_documents.extend(load_test_cases())

    if "pdf" in active_sources:
        all_documents.extend(load_pdf_test_cases())

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
        choices=["pluginhive", "shopify", "fedex", "codebase", "sheets", "pdf"],
        help="Which sources to ingest (default: all)",
    )
    args = parser.parse_args()
    run_ingest(args.sources)
