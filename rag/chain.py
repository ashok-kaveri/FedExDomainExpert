from __future__ import annotations
import logging
from collections import defaultdict

from langchain_anthropic import ChatAnthropic
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

import config
from rag.vectorstore import search
from rag.prompts import QA_PROMPT, CONDENSE_QUESTION_PROMPT

# Human-readable labels for each source_type stored in ChromaDB metadata.
# These appear as section headers in the context block Claude receives, so
# it can accurately cite where each fact came from.
_SOURCE_LABELS: dict[str, str] = {
    "wiki":             "Internal Wiki (Product, Engineering & Bug Knowledge)",
    "pluginhive_docs":  "PluginHive Official Documentation",
    "pluginhive_seeds": "PluginHive FAQ & Guides",
    "fedex_rest":       "FedEx REST API Reference",
    "pdf":              "Test Cases & Acceptance Criteria (PDF)",
    "codebase":         "Automation Codebase (Playwright / TypeScript)",
    "automation":       "Automation Codebase",
    "backend":          "Backend Source Code",
    "frontend":         "Frontend Source Code",
    "app":              "FedEx App UI Knowledge",
}

logger = logging.getLogger(__name__)

# Lazy singleton for LLM — created once, reused across calls
_llm_instance: ChatAnthropic | None = None


def get_llm() -> ChatAnthropic:
    global _llm_instance
    if _llm_instance is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set.\n"
                "Add it to your .env file:  ANTHROPIC_API_KEY=sk-ant-..."
            )
        _llm_instance = ChatAnthropic(
            model=config.DOMAIN_EXPERT_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=0.1,
            max_tokens=2048,
        )
    return _llm_instance


class SimpleConversationalChain:
    """
    Conversational RAG chain with two-step retrieval:
    1. Condense follow-up questions using chat history (CONDENSE_QUESTION_PROMPT)
    2. Retrieve context and answer using the condensed question (QA_PROMPT)
    """

    def __init__(self, llm: ChatAnthropic, memory_window: int = 10):
        self.llm = llm
        self.memory_window = memory_window
        self._history: list[dict] = []  # [{"question": str, "answer": str}, ...]

    def _format_history(self) -> str:
        """Format recent history as a string for the condense prompt."""
        if not self._history:
            return ""
        lines = []
        for turn in self._history[-self.memory_window:]:
            lines.append(f"Human: {turn['question']}")
            lines.append(f"Assistant: {turn['answer']}")
        return "\n".join(lines)

    def _invoke_llm(self, prompt: str) -> str:
        """Call Claude and return the string response."""
        response = self.llm.invoke([HumanMessage(content=prompt)])
        return response.content.strip()

    def _condense_question(self, question: str) -> str:
        """
        If there is history, use the LLM to rewrite the question as standalone.
        If no history, return the question unchanged (first turn).
        """
        history = self._format_history()
        if not history:
            return question

        condensed = self._invoke_llm(
            CONDENSE_QUESTION_PROMPT.format(
                chat_history=history,
                question=question,
            )
        )
        return condensed if condensed else question

    @staticmethod
    def _build_labeled_context(docs: list[Document]) -> str:
        """Group retrieved docs by source_type and add clear section headers.

        Instead of feeding Claude a single anonymous blob of text, we bucket
        each chunk into its source category and label it.  Claude can then
        accurately say "According to the PluginHive FAQ..." or "The internal
        wiki notes that..." in its answer.
        """
        groups: dict[str, list[Document]] = defaultdict(list)
        for doc in docs:
            source_type = doc.metadata.get("source_type", "unknown")
            groups[source_type].append(doc)

        sections: list[str] = []
        # Sort so the order is deterministic (wiki first, then docs, etc.)
        for source_type in sorted(groups):
            label = _SOURCE_LABELS.get(
                source_type,
                source_type.replace("_", " ").title(),
            )
            # For wiki chunks, also show the category (e.g. "Engineering & APIs")
            chunks_text = []
            for doc in groups[source_type]:
                cat = doc.metadata.get("category", "")
                prefix = f"[{cat}] " if cat else ""
                chunks_text.append(f"{prefix}{doc.page_content}")
            section_body = "\n\n".join(chunks_text)
            sections.append(f"### [{label}]\n{section_body}")

        return "\n\n---\n\n".join(sections)

    def invoke(self, inputs: dict) -> dict:
        question = inputs["question"]

        # Step 1: Rewrite ambiguous follow-up as standalone question
        standalone_question = self._condense_question(question)
        logger.debug("Original: %r → Standalone: %r", question, standalone_question)

        # Step 2: Retrieve context using the standalone question.
        # Use a slightly larger K so we get a spread across source types, then
        # label each section so Claude knows exactly where each fact comes from.
        docs = search(standalone_question, k=max(config.TOP_K_RESULTS, 12))
        context = self._build_labeled_context(docs)

        # Step 3: Answer using QA_PROMPT with labelled context
        prompt_text = QA_PROMPT.format(context=context, question=standalone_question)
        answer = self._invoke_llm(prompt_text)

        # Step 4: Update history
        self._history.append({"question": question, "answer": answer})
        if len(self._history) > self.memory_window:
            self._history = self._history[-self.memory_window:]

        return {"answer": answer, "source_documents": docs}


def build_chain(memory=None) -> SimpleConversationalChain:
    """
    Build and return a conversational RAG chain backed by ChromaDB.

    Note: The `memory` parameter is accepted for API compatibility but
    memory is managed internally via `_history`. Pass `None`.
    """
    llm = get_llm()
    return SimpleConversationalChain(llm=llm, memory_window=config.MEMORY_WINDOW)


def ask(question: str, chain: SimpleConversationalChain) -> dict:
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
