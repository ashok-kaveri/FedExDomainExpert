import chromadb
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document

import config


def get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(
        model=config.EMBEDDING_MODEL,
        base_url=config.OLLAMA_BASE_URL,
    )


def get_vectorstore() -> Chroma:
    return Chroma(
        collection_name=config.CHROMA_COLLECTION,
        embedding_function=get_embeddings(),
        persist_directory=config.CHROMA_PATH,
    )


def add_documents(documents: list[Document]) -> None:
    """Embed and store documents in ChromaDB."""
    vectorstore = get_vectorstore()
    vectorstore.add_documents(documents)


def clear_collection() -> None:
    """Delete and recreate the ChromaDB collection."""
    client = chromadb.PersistentClient(path=config.CHROMA_PATH)
    try:
        client.delete_collection(config.CHROMA_COLLECTION)
    except Exception:
        pass  # Collection didn't exist — that's fine


def search(query: str, k: int = 5) -> list[Document]:
    """Return top-k documents most relevant to the query. Returns [] if collection is empty."""
    try:
        vectorstore = get_vectorstore()
        return vectorstore.similarity_search(query, k=k)
    except Exception:
        return []
