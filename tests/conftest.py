import pytest


class FakeEmbeddings:
    """Small deterministic embedding function for vectorstore tests."""

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def embed_query(self, text):
        return self._embed(text)

    @staticmethod
    def _embed(text):
        value = sum(ord(ch) for ch in text)
        return [
            float(len(text) % 101),
            float(value % 103),
            float(text.lower().count("fedex")),
            float(text.lower().count("label")),
        ]


@pytest.fixture
def temp_chroma(monkeypatch, tmp_path):
    """Point ChromaDB at a temp directory so tests don't pollute real data."""
    import config
    monkeypatch.setattr(config, "CHROMA_PATH", str(tmp_path / "chroma"))
    # Reset the singleton so it picks up the new CHROMA_PATH
    import rag.vectorstore as vs
    monkeypatch.setattr(vs, "get_embeddings", lambda: FakeEmbeddings())
    monkeypatch.setattr(vs, "_vectorstore_instance", None)
    yield str(tmp_path / "chroma")
    monkeypatch.setattr(vs, "_vectorstore_instance", None)
