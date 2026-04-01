from unittest.mock import MagicMock
from langchain_core.documents import Document


def test_ask_returns_answer_and_sources():
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = {
        "answer": "Label generation creates a FedEx shipping label via the REST API.",
        "source_documents": [
            Document(
                page_content="Label generation workflow...",
                metadata={"source_url": "https://pluginhive.com/label-gen"},
            ),
            Document(
                page_content="FedEx API label endpoint...",
                metadata={"source_url": "https://pluginhive.com/label-gen"},
            ),
        ],
    }

    from rag.chain import ask

    result = ask("How does label generation work?", mock_chain)

    assert "answer" in result
    assert "sources" in result
    assert result["answer"] == "Label generation creates a FedEx shipping label via the REST API."
    assert "https://pluginhive.com/label-gen" in result["sources"]


def test_ask_deduplicates_sources():
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = {
        "answer": "Some answer.",
        "source_documents": [
            Document(page_content="chunk 1", metadata={"source_url": "https://same-url.com"}),
            Document(page_content="chunk 2", metadata={"source_url": "https://same-url.com"}),
        ],
    }

    from rag.chain import ask

    result = ask("Any question", mock_chain)
    assert result["sources"].count("https://same-url.com") == 1
