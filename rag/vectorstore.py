import logging

import chromadb
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document

import config

logger = logging.getLogger(__name__)


def get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(
        model=config.EMBEDDING_MODEL,
        base_url=config.OLLAMA_BASE_URL,
    )


_vectorstore_instance: Chroma | None = None


def get_vectorstore() -> Chroma:
    global _vectorstore_instance
    if _vectorstore_instance is None:
        # collection_metadata configures the HNSW index.
        # hnsw:space=cosine is correct for nomic-embed-text (normalised embeddings).
        # Without explicit settings, Python 3.14 + chromadb allocates a huge
        # link_lists.bin sparse file (60-150GB) due to an integer-overflow in
        # hnswlib's max_elements calculation — this config keeps it sane.
        _vectorstore_instance = Chroma(
            collection_name=config.CHROMA_COLLECTION,
            embedding_function=get_embeddings(),
            persist_directory=config.CHROMA_PATH,
            collection_metadata={
                "hnsw:space": "cosine",
                "hnsw:construction_ef": 100,
                "hnsw:search_ef": 100,
                "hnsw:M": 16,
                "hnsw:batch_size": 100,
                "hnsw:sync_threshold": 1000,
            },
        )
    return _vectorstore_instance


def _reset_vectorstore() -> None:
    """Reset the cached vectorstore instance (used after clear_collection())."""
    global _vectorstore_instance
    _vectorstore_instance = None


# Smaller batch size prevents ChromaDB HNSW from pre-allocating huge link_lists.bin
# (Python 3.14 + chromadb bug: large batches trigger oversized HNSW allocation)
_CHROMA_BATCH_SIZE = 500


def add_documents(documents: list[Document]) -> None:
    """Embed and store documents in ChromaDB, batching to respect ChromaDB limits."""
    if not documents:
        logger.debug("add_documents called with empty list — skipping")
        return
    vectorstore = get_vectorstore()
    total = len(documents)
    for start in range(0, total, _CHROMA_BATCH_SIZE):
        batch = documents[start: start + _CHROMA_BATCH_SIZE]
        vectorstore.add_documents(batch)
        logger.info(
            "Embedded batch %d–%d / %d",
            start + 1,
            min(start + _CHROMA_BATCH_SIZE, total),
            total,
        )
    logger.info("Added %d documents to ChromaDB", total)


def clear_collection() -> None:
    """Delete and recreate the ChromaDB collection."""
    global _vectorstore_instance
    client = chromadb.PersistentClient(path=config.CHROMA_PATH)
    try:
        client.delete_collection(config.CHROMA_COLLECTION)
        logger.info("Cleared ChromaDB collection: %s", config.CHROMA_COLLECTION)
    except Exception:
        logger.debug("Collection %s did not exist — nothing to clear", config.CHROMA_COLLECTION)
    _reset_vectorstore()


def upsert_documents(documents: list[Document], ids: list[str]) -> None:
    """
    Add or replace documents by stable ID.

    Deletes any existing documents with the given IDs first (safe to call even
    if the IDs do not exist yet), then re-adds all documents with those IDs.
    This gives upsert semantics without requiring direct ChromaDB collection access.

    Args:
        documents: LangChain Document objects to embed and store.
        ids:       Stable string IDs, one per document (must be same length).
    """
    if not documents:
        logger.debug("upsert_documents called with empty list — skipping")
        return
    if len(documents) != len(ids):
        raise ValueError(
            f"upsert_documents: len(documents)={len(documents)} != len(ids)={len(ids)}"
        )
    vectorstore = get_vectorstore()
    # Delete previous versions (silently ignore if IDs don't exist)
    try:
        vectorstore.delete(ids=ids)
        logger.debug("Deleted %d existing document(s) before upsert", len(ids))
    except Exception as exc:
        logger.debug("Delete before upsert raised (OK on first run): %s", exc)
    # Add with stable IDs so the next upsert can find and replace them
    vectorstore.add_documents(documents, ids=ids)
    logger.info("Upserted %d document(s) into ChromaDB", len(documents))


def search(query: str, k: int = 5) -> list[Document]:
    """Return top-k documents most relevant to the query. Returns [] if collection is empty."""
    try:
        vectorstore = get_vectorstore()
        return vectorstore.similarity_search(query, k=k)
    except Exception as e:
        # Empty collection raises various errors depending on ChromaDB version
        err_str = str(e).lower()
        if "does not exist" in err_str or "collection" in err_str or "no documents" in err_str:
            return []
        logger.exception("Vector store search failed for query: %r", query)
        raise
