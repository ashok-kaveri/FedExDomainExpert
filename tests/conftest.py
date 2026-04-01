import pytest


@pytest.fixture
def temp_chroma(monkeypatch, tmp_path):
    """Point ChromaDB at a temp directory so tests don't pollute real data."""
    import config
    monkeypatch.setattr(config, "CHROMA_PATH", str(tmp_path / "chroma"))
    return str(tmp_path / "chroma")
