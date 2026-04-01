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


def test_chain_builds_history_across_turns():
    """Verify that _history grows with each turn and _condense_question sees it."""
    from rag.chain import SimpleConversationalChain
    from unittest.mock import MagicMock, patch

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = "mocked answer"

    with patch("rag.chain.search", return_value=[]):
        chain = SimpleConversationalChain(llm=mock_llm, memory_window=10)

        # First turn
        chain.invoke({"question": "How does label generation work?"})
        assert len(chain._history) == 1

        # Second turn — verify _condense_question was called with history
        chain.invoke({"question": "Tell me more"})
        assert len(chain._history) == 2

        # The LLM should have been called: once for Q1 answer, once for Q2 condense, once for Q2 answer
        assert mock_llm.invoke.call_count == 3
