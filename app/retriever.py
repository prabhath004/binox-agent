"""
Retriever: embeds sub-questions and searches Chroma for relevant chunks.

Includes a relevance filter that drops chunks below a similarity threshold
before they enter the memory system.
"""

from __future__ import annotations

import os
from typing import List

import chromadb
from chromadb.config import Settings

from app.budget import BudgetTracker
from app.memory import EvidenceChunk
from app.utils import logger

CHROMA_DIR = os.getenv("CHROMA_DIR", "./chroma_store")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "research_corpus")
RELEVANCE_THRESHOLD = 0.35  # cosine distance — lower is more similar


def _get_collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(
        path=CHROMA_DIR,
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def retrieve_for_subquestion(
    sub_question: str,
    budget: BudgetTracker,
    top_k: int = 5,
) -> List[EvidenceChunk]:
    """
    Query Chroma for chunks relevant to a single sub-question.
    Applies relevance filtering and respects the chunk budget.
    """
    available = budget.remaining_chunks()
    if available <= 0:
        logger.info("Retrieval skipped — chunk budget exhausted")
        return []

    k = min(top_k, available)
    collection = _get_collection()

    results = collection.query(
        query_texts=[sub_question],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )

    chunks: List[EvidenceChunk] = []
    docs = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []
    dists = results["distances"][0] if results["distances"] else []

    for doc, meta, dist in zip(docs, metas, dists):
        if dist > RELEVANCE_THRESHOLD:
            logger.debug(
                "Dropped chunk (distance %.3f > %.3f): %.60s…",
                dist, RELEVANCE_THRESHOLD, doc,
            )
            continue

        source = meta.get("source", "unknown")
        chunks.append(
            EvidenceChunk(
                sub_question=sub_question,
                text=doc,
                source=source,
                relevance_score=1.0 - dist,
            )
        )

    logger.info(
        "Retrieved %d/%d chunks for: %s",
        len(chunks), len(docs), sub_question[:80],
    )
    return chunks


def retrieve_all(
    sub_questions: List[str],
    budget: BudgetTracker,
    top_k: int = 3,
) -> List[EvidenceChunk]:
    """Retrieve evidence for every sub-question, respecting budget."""
    all_chunks: List[EvidenceChunk] = []
    for sq in sub_questions:
        if budget.remaining_chunks() <= 0:
            logger.info("Stopping retrieval — chunk budget hit")
            break
        if budget.is_over_budget():
            logger.info("Stopping retrieval — cost budget hit")
            break
        chunks = retrieve_for_subquestion(sq, budget, top_k=top_k)
        all_chunks.extend(chunks)
    return all_chunks
