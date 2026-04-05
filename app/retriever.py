"""Vector retrieval from ChromaDB with deduplication and relevance filtering."""
from __future__ import annotations
import os
from typing import List, Set
import chromadb
from chromadb.config import Settings
from app.budget import BudgetTracker
from app.memory import EvidenceChunk
from app.utils import logger

CHROMA_DIR = os.getenv("CHROMA_DIR", "./chroma_store")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "research_corpus")
RELEVANCE_THRESHOLD = 0.75


def _get_collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(path=CHROMA_DIR, settings=Settings(anonymized_telemetry=False))
    return client.get_or_create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})


def get_corpus_count() -> int:
    try:
        return _get_collection().count()
    except Exception:
        return 0


def retrieve_for_subquestion(sub_question: str, budget: BudgetTracker, seen: Set[str], top_k: int = 5) -> List[EvidenceChunk]:
    available = budget.remaining_chunks()
    if available <= 0:
        return []

    results = _get_collection().query(
        query_texts=[sub_question], n_results=min(top_k + 3, available + 5),
        include=["documents", "metadatas", "distances"],
    )

    chunks: List[EvidenceChunk] = []
    docs = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []
    dists = results["distances"][0] if results["distances"] else []

    for doc, meta, dist in zip(docs, metas, dists):
        if len(chunks) >= min(top_k, available):
            break
        if dist > RELEVANCE_THRESHOLD:
            continue
        text_key = doc[:200]
        if text_key in seen:
            continue
        seen.add(text_key)
        chunks.append(EvidenceChunk(
            sub_question=sub_question, text=doc,
            source=meta.get("source", "unknown"), relevance_score=1.0 - dist,
        ))

    logger.info("Retrieved %d unique chunks for: %s", len(chunks), sub_question[:80])
    return chunks


def retrieve_all(sub_questions: List[str], budget: BudgetTracker, top_k: int = 5) -> List[EvidenceChunk]:
    all_chunks, seen = [], set()
    for sq in sub_questions:
        if budget.remaining_chunks() <= 0 or budget.is_over_budget():
            break
        all_chunks.extend(retrieve_for_subquestion(sq, budget, seen, top_k=top_k))
    return all_chunks
