"""
Ingest markdown documents from data/ into ChromaDB.

Splits each file into ~300-token chunks with overlap,
embeds them using Chroma's default embedding model,
and stores them with source metadata.

Usage:
    python ingest.py
    python ingest.py --data-dir ./data --chroma-dir ./chroma_store
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import hashlib

import chromadb
from chromadb.config import Settings


def chunk_markdown(text: str, max_chars: int = 1200, overlap: int = 200) -> list[str]:
    """
    Split markdown by headings first, then by size.
    Overlap ensures cross-boundary context is preserved.
    """
    sections = re.split(r"\n(?=##?\s)", text)
    chunks: list[str] = []

    for section in sections:
        section = section.strip()
        if not section:
            continue

        if len(section) <= max_chars:
            chunks.append(section)
        else:
            words = section.split()
            current: list[str] = []
            current_len = 0
            for word in words:
                if current_len + len(word) + 1 > max_chars and current:
                    chunks.append(" ".join(current))
                    overlap_words = current[-(overlap // 6) :]
                    current = list(overlap_words)
                    current_len = sum(len(w) + 1 for w in current)
                current.append(word)
                current_len += len(word) + 1
            if current:
                chunks.append(" ".join(current))

    return chunks


def ingest(data_dir: str = "./data", chroma_dir: str = "./chroma_store") -> None:
    client = chromadb.PersistentClient(
        path=chroma_dir,
        settings=Settings(anonymized_telemetry=False),
    )

    try:
        client.delete_collection("research_corpus")
        print("Deleted existing collection")
    except Exception:
        pass

    collection = client.get_or_create_collection(
        name="research_corpus",
        metadata={"hnsw:space": "cosine"},
    )

    md_files = sorted(glob.glob(os.path.join(data_dir, "*.md")))
    if not md_files:
        print(f"No .md files found in {data_dir}")
        return

    all_docs: list[str] = []
    all_ids: list[str] = []
    all_metas: list[dict] = []

    for filepath in md_files:
        filename = os.path.basename(filepath)
        with open(filepath) as f:
            text = f.read()

        chunks = chunk_markdown(text)
        print(f"  {filename}: {len(chunks)} chunks")

        for i, chunk in enumerate(chunks):
            doc_id = hashlib.md5(f"{filename}:{i}:{chunk[:50]}".encode()).hexdigest()
            all_docs.append(chunk)
            all_ids.append(doc_id)
            all_metas.append({"source": filename, "chunk_index": i})

    collection.add(documents=all_docs, ids=all_ids, metadatas=all_metas)
    print(f"\nIngested {len(all_docs)} chunks from {len(md_files)} files")
    print(f"Chroma store: {os.path.abspath(chroma_dir)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest markdown into ChromaDB")
    parser.add_argument("--data-dir", default="./data")
    parser.add_argument("--chroma-dir", default="./chroma_store")
    args = parser.parse_args()
    ingest(args.data_dir, args.chroma_dir)
