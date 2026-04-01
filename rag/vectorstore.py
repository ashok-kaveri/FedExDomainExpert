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
        _vectorstore_instance = Chroma(
            collection_name=config.CHROMA_COLLECTION,
            embedding_function=get_embeddings(),
            persist_directory=config.CHROMA_PATH,
        )
    return _vectorstore_instance


def _reset_vectorstore() -> None:
    """Reset the cached vectorstore instance (used after clear_collection())."""
    global _vectorstore_instance
    _vectorstore_instance = None


def add_documents(documents: list[Document]) -> None:
    """Embed and store documents in ChromaDB."""
    if not documents:
        logger.debug("add_documents called with empty list — skipping")
        return
    vectorstore = get_vectorstore()
    vectorstore.add_documents(documents)
    logger.info("Added %d documents to ChromaDB", len(documents))


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
