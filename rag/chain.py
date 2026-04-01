import logging
from langchain_core.documents import Document
from langchain_ollama import OllamaLLM

import config
from rag.vectorstore import search
from rag.prompts import QA_PROMPT

logger = logging.getLogger(__name__)


class SimpleConversationalChain:
    """Simple conversational chain with memory, backed by ChromaDB search."""

    def __init__(self, llm: OllamaLLM, memory_window: int = 10):
        self.llm = llm
        self.memory_window = memory_window
        self._history: list[dict] = []

    def invoke(self, inputs: dict) -> dict:
        question = inputs["question"]

        # Retrieve context
        docs = search(question, k=config.TOP_K_RESULTS)
        context = "\n\n".join(doc.page_content for doc in docs)

        # Build prompt
        prompt_text = QA_PROMPT.format(context=context, question=question)

        # Call LLM
        answer = self.llm.invoke(prompt_text)

        # Update history (keep last N turns)
        self._history.append({"question": question, "answer": answer})
        if len(self._history) > self.memory_window:
            self._history = self._history[-self.memory_window:]

        return {"answer": answer, "source_documents": docs}


def get_llm() -> OllamaLLM:
    return OllamaLLM(
        model=config.DOMAIN_EXPERT_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=0.1,
    )


def build_chain(memory=None) -> SimpleConversationalChain:
    """Build and return a conversational chain backed by ChromaDB."""
    llm = get_llm()
    return SimpleConversationalChain(llm=llm, memory_window=config.MEMORY_WINDOW)


def ask(question: str, chain) -> dict:
    """
    Ask a question and return the answer with deduplicated source URLs.

    Returns:
        {"answer": str, "sources": list[str]}
    """
    result = chain.invoke({"question": question})
    source_docs: list[Document] = result.get("source_documents", [])
    sources = list(
        {
            doc.metadata.get("source_url", doc.metadata.get("source", "Unknown"))
            for doc in source_docs
        }
    )
    return {"answer": result["answer"], "sources": sources}
