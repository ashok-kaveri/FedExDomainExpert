"""
Feature Detector  —  Step 5.0 of the Delivery Pipeline
=======================================================
Determines whether a card describes a NEW feature or a change to an
EXISTING feature, and returns the list of related test files.

Strategy:
  1. Vector search ChromaDB with the card's acceptance criteria
  2. Check if any matching chunks come from the Playwright codebase
  3. Claude classifies NEW / EXISTING with confidence + reasoning
  4. Return related test file paths for the test writer to use

Usage:
    from pipeline.feature_detector import detect_feature
    result = detect_feature(card_name, acceptance_criteria)
    # result.kind      → "new" | "existing"
    # result.confidence → 0.0–1.0
    # result.related_files → ["tests/labels/...", ...]
    # result.reasoning    → explanation string
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from textwrap import dedent

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config
from rag.vectorstore import search

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class DetectionResult:
    kind: str                              # "new" or "existing"
    confidence: float                      # 0.0 – 1.0
    reasoning: str                         # Claude's explanation
    related_files: list[str] = field(default_factory=list)  # spec file paths
    related_chunks: list[str] = field(default_factory=list) # raw chunk snippets


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

DETECTOR_PROMPT = dedent("""\
    You are a test automation expert for the FedEx Shopify App.

    Below are the top {k} most relevant chunks retrieved from the existing
    test codebase and knowledge base for the feature described.

    FEATURE:
    {feature_summary}

    RETRIEVED CONTEXT:
    {context}

    Based on the retrieved context, answer:

    1. Is this a NEW feature (no existing test coverage) or an EXISTING
       feature (tests already exist that cover this area)?

    2. If EXISTING — which specific test files are most relevant?

    Respond in this exact JSON format (no markdown, no extra text):
    {{
      "kind": "new" | "existing",
      "confidence": 0.0-1.0,
      "reasoning": "one paragraph explanation",
      "related_files": ["path/to/spec.ts", ...]
    }}
""")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def detect_feature(
    card_name: str,
    acceptance_criteria: str,
    top_k: int = 10,
) -> DetectionResult:
    """
    Classify a feature as new or existing using vector search + Claude.

    Args:
        card_name:            Short title of the feature
        acceptance_criteria:  The full AC markdown from the card processor
        top_k:                How many chunks to retrieve for classification

    Returns:
        DetectionResult with kind, confidence, reasoning, and related_files
    """
    # Step 1: Build a concise feature summary for the search query
    query = f"{card_name}\n{acceptance_criteria[:500]}"

    # Step 2: Vector search — retrieve codebase + docs chunks
    docs = search(query, k=top_k)
    if not docs:
        logger.warning("No chunks retrieved — defaulting to 'new' feature")
        return DetectionResult(
            kind="new",
            confidence=0.9,
            reasoning="No similar content found in knowledge base.",
        )

    # Step 3: Extract related spec files from codebase chunks
    codebase_files = []
    for doc in docs:
        src = doc.metadata.get("source", "")
        if src.endswith(".ts") and "/tests/" in src:
            # normalise to relative path
            if "/fedex-test-automation/" in src:
                rel = src.split("/fedex-test-automation/")[-1]
            else:
                rel = src
            codebase_files.append(rel)

    related_files = list(dict.fromkeys(codebase_files))  # dedup, preserve order

    # Step 4: Build context string for Claude
    context_parts = []
    for i, doc in enumerate(docs, 1):
        src = doc.metadata.get("source", "unknown")
        src_type = doc.metadata.get("source_type", "")
        context_parts.append(
            f"[{i}] ({src_type}) {src}\n{doc.page_content[:400]}"
        )
    context = "\n\n".join(context_parts)

    # Step 5: Ask Claude to classify
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    claude = ChatAnthropic(
        model=config.CLAUDE_HAIKU_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.0,
        max_tokens=1024,
    )

    prompt = DETECTOR_PROMPT.format(
        k=top_k,
        feature_summary=query,
        context=context,
    )

    response = claude.invoke([HumanMessage(content=prompt)])
    raw = response.content.strip()

    # Step 6: Parse JSON response
    import json, re
    try:
        # Strip markdown code fences if present
        json_text = re.sub(r"```(?:json)?\n?", "", raw).strip().rstrip("`")
        data = json.loads(json_text)
        return DetectionResult(
            kind=data.get("kind", "new"),
            confidence=float(data.get("confidence", 0.5)),
            reasoning=data.get("reasoning", ""),
            related_files=data.get("related_files", related_files),
            related_chunks=[doc.page_content[:200] for doc in docs[:3]],
        )
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Could not parse detector response: %s\nRaw: %s", e, raw)
        # Fallback: if we found codebase files, assume existing; otherwise new
        kind = "existing" if related_files else "new"
        return DetectionResult(
            kind=kind,
            confidence=0.6,
            reasoning=f"JSON parse failed — inferred from file matches: {related_files}",
            related_files=related_files,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 3:
        print("Usage: python -m pipeline.feature_detector '<card name>' '<acceptance criteria>'")
        sys.exit(1)

    result = detect_feature(sys.argv[1], sys.argv[2])
    print(f"\nKind:       {result.kind.upper()}  (confidence: {result.confidence:.0%})")
    print(f"Reasoning:  {result.reasoning}")
    print(f"Files:      {result.related_files or '— none found'}")
