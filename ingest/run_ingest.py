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


_DEFAULT_SOURCES = ["pluginhive", "shopify", "fedex", "fedex_rest", "app", "codebase", "pdf"]
# fedex_rest  — FedEx REST API knowledge: rate/label requests, special handles, error codes
# app         — Live browser capture of every FedEx app page + structured UI knowledge
# sheets      — excluded from default (PDF master sheet covers same data); use --sources sheets


def run_ingest(sources: list[str] | None = None) -> None:
    from rag.vectorstore import clear_collection, add_documents
    from ingest.web_scraper import scrape_pluginhive_docs, scrape_fedex_api_docs, scrape_shopify_app_store
    from ingest.codebase_loader import load_codebase
    from ingest.sheets_loader import load_test_cases
    from ingest.pdf_loader import load_pdf_test_cases
    from ingest.fedex_rest_api import load_fedex_rest_api_knowledge
    from ingest.app_navigator import load_app_knowledge

    active_sources = sources if sources is not None else _DEFAULT_SOURCES
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

    if "fedex_rest" in active_sources:
        logger.info("Loading FedEx REST API knowledge…")
        all_documents.extend(load_fedex_rest_api_knowledge())

    if "app" in active_sources:
        logger.info("Loading FedEx Shopify App UI knowledge (browser capture)…")
        all_documents.extend(load_app_knowledge())

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
        choices=["pluginhive", "shopify", "fedex", "fedex_rest", "app", "codebase", "sheets", "pdf"],
        help="Which sources to ingest (default: all)",
    )
    args = parser.parse_args()
    run_ingest(args.sources)
