from pathlib import Path


def test_loads_ts_and_md_files(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTOMATION_CODEBASE_PATH", str(tmp_path))

    (tmp_path / "example.spec.ts").write_text(
        "test('should generate label', async ({ pages }) => { expect(true).toBe(true); });"
    )
    (tmp_path / "README.md").write_text("# FedEx Automation\nThis is the Playwright E2E test suite for the FedEx Shopify app.")

    from ingest.codebase_loader import load_codebase

    docs = load_codebase()

    assert len(docs) >= 2
    assert all(d.metadata["source_type"] == "codebase" for d in docs)


def test_excludes_node_modules(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTOMATION_CODEBASE_PATH", str(tmp_path))

    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / "fake.ts").write_text("this should never appear in results")
    (tmp_path / "real.spec.ts").write_text("real test content here for the codebase loader")

    from ingest.codebase_loader import load_codebase

    docs = load_codebase()
    all_content = " ".join(d.page_content for d in docs)
    assert "this should never appear in results" not in all_content


def test_returns_empty_list_for_missing_path(monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTOMATION_CODEBASE_PATH", "/does/not/exist")

    from ingest.codebase_loader import load_codebase

    docs = load_codebase()
    assert docs == []
