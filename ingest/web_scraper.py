import logging
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config

logger = logging.getLogger(__name__)


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 FedexDomainExpert/1.0"})
    return session


def _scrape_text(url: str, session: requests.Session) -> str:
    """Download a page and return its cleaned plain text."""
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup.find_all(["nav", "footer", "script", "style", "header"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except Exception as e:
        logger.warning("Failed to scrape %s: %s", url, e)
        return ""


def _get_same_domain_links(url: str, base_domain: str, session: requests.Session) -> list[str]:
    """Return all links on a page that stay within base_domain."""
    try:
        resp = session.get(url, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            full = urljoin(url, a["href"]).split("?")[0].split("#")[0]
            if urlparse(full).netloc == base_domain:
                links.append(full)
        return list(set(links))
    except Exception:
        return []


def _chunk_text(text: str, source_url: str, source_type: str) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )
    chunks = splitter.split_text(text)
    return [
        Document(
            page_content=chunk,
            metadata={
                "source": source_url,
                "source_url": source_url,
                "source_type": source_type,
                "chunk_index": i,
            },
        )
        for i, chunk in enumerate(chunks)
    ]


def scrape_pluginhive_docs() -> list[Document]:
    """Recursively crawl PluginHive docs and return chunked Documents."""
    logger.info("Scraping PluginHive docs...")
    session = _make_session()
    base_domain = urlparse(config.PLUGINHIVE_BASE_URL).netloc
    visited: set[str] = set()
    to_visit = [config.PLUGINHIVE_BASE_URL]
    documents: list[Document] = []

    while to_visit:
        url = to_visit.pop(0)
        if url in visited:
            continue
        visited.add(url)

        text = _scrape_text(url, session)
        if text and len(text) > 100:
            documents.extend(_chunk_text(text, url, "pluginhive_docs"))

        for link in _get_same_domain_links(url, base_domain, session):
            if link not in visited:
                to_visit.append(link)

        time.sleep(0.5)

    logger.info("PluginHive: %d chunks from %d pages", len(documents), len(visited))
    return documents


def scrape_fedex_api_docs() -> list[Document]:
    """Scrape FedEx API catalog page and return chunked Documents."""
    logger.info("Scraping FedEx API docs...")
    session = _make_session()
    text = _scrape_text(config.FEDEX_API_DOCS_URL, session)
    documents = _chunk_text(text, config.FEDEX_API_DOCS_URL, "fedex_api_docs") if text else []
    logger.info("FedEx API: %d chunks", len(documents))
    return documents
