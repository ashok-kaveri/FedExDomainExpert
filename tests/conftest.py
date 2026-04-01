import pytest


@pytest.fixture
def temp_chroma(monkeypatch, tmp_path):
    """Point ChromaDB at a temp directory so tests don't pollute real data."""
    import config
    monkeypatch.setattr(config, "CHROMA_PATH", str(tmp_path / "chroma"))
    # Reset the singleton so it picks up the new CHROMA_PATH
    import rag.vectorstore as vs
    monkeypatch.setattr(vs, "_vectorstore_instance", None)
    yield str(tmp_path / "chroma")
