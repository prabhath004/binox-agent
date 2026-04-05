"""Ingest markdown files from data/ into ChromaDB."""
from __future__ import annotations
import argparse, glob, os, re, hashlib
import chromadb
from chromadb.config import Settings


def chunk_markdown(text: str, max_chars: int = 1200, overlap: int = 200) -> list[str]:
    sections = re.split(r"\n(?=##?\s)", text)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= max_chars:
            chunks.append(section)
        else:
            words, current, current_len = section.split(), [], 0
            for word in words:
                if current_len + len(word) + 1 > max_chars and current:
                    chunks.append(" ".join(current))
                    current = list(current[-(overlap // 6):])
                    current_len = sum(len(w) + 1 for w in current)
                current.append(word)
                current_len += len(word) + 1
            if current:
                chunks.append(" ".join(current))
    return chunks


def ingest(data_dir="./data", chroma_dir="./chroma_store"):
    client = chromadb.PersistentClient(path=chroma_dir, settings=Settings(anonymized_telemetry=False))
    try:
        client.delete_collection("research_corpus")
    except Exception:
        pass

    collection = client.get_or_create_collection(name="research_corpus", metadata={"hnsw:space": "cosine"})
    md_files = sorted(glob.glob(os.path.join(data_dir, "*.md")))
    if not md_files:
        print(f"No .md files found in {data_dir}")
        return

    all_docs, all_ids, all_metas = [], [], []
    for filepath in md_files:
        filename = os.path.basename(filepath)
        with open(filepath) as f:
            text = f.read()
        chunks = chunk_markdown(text)
        print(f"  {filename}: {len(chunks)} chunks")
        for i, chunk in enumerate(chunks):
            all_docs.append(chunk)
            all_ids.append(hashlib.md5(f"{filename}:{i}:{chunk[:50]}".encode()).hexdigest())
            all_metas.append({"source": filename, "chunk_index": i})

    collection.add(documents=all_docs, ids=all_ids, metadatas=all_metas)
    print(f"\nIngested {len(all_docs)} chunks from {len(md_files)} files into {os.path.abspath(chroma_dir)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="./data")
    p.add_argument("--chroma-dir", default="./chroma_store")
    args = p.parse_args()
    ingest(args.data_dir, args.chroma_dir)
