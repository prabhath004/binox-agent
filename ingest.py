"""Ingest markdown files from data/ into ChromaDB with smart chunking."""
from __future__ import annotations
import argparse, glob, os, re, hashlib
import chromadb
from chromadb.config import Settings

MIN_CHUNK_CHARS = 200


def extract_doc_title(text: str) -> str:
    """Pull the H1 title to use as a prefix for all chunks from this doc."""
    match = re.match(r"^#\s+(.+)", text.strip())
    if match:
        title = match.group(1).strip()
        if "—" in title:
            return title.split("—")[0].strip()
        return title
    return ""


def chunk_markdown(text: str, max_chars: int = 1200) -> list[str]:
    """
    Split by H2 headings, merge small sections, prepend doc title.
    Every chunk starts with the company/doc name for embedding quality.
    """
    title = extract_doc_title(text)
    sections = re.split(r"\n(?=## )", text)
    raw_chunks = []

    for section in sections:
        section = section.strip()
        if not section:
            continue
        if section.startswith("# ") and len(section) < 150:
            continue
        raw_chunks.append(section)

    merged: list[str] = []
    buffer = ""
    for chunk in raw_chunks:
        if buffer and len(buffer) + len(chunk) + 2 <= max_chars:
            buffer = buffer + "\n\n" + chunk
        elif buffer and len(buffer) < MIN_CHUNK_CHARS:
            buffer = buffer + "\n\n" + chunk
        else:
            if buffer:
                merged.append(buffer)
            buffer = chunk
    if buffer:
        merged.append(buffer)

    final = []
    for chunk in merged:
        if title and not chunk.startswith(title) and not chunk.startswith("# "):
            chunk = f"[{title}]\n{chunk}"
        if len(chunk) > max_chars:
            words = chunk.split()
            current, current_len = [], 0
            for word in words:
                if current_len + len(word) + 1 > max_chars and current:
                    final.append(" ".join(current))
                    overlap = current[-20:]
                    current = list(overlap)
                    current_len = sum(len(w) + 1 for w in current)
                current.append(word)
                current_len += len(word) + 1
            if current:
                final.append(" ".join(current))
        else:
            final.append(chunk)

    return final


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

    sizes = [len(d) for d in all_docs]
    print(f"Chunk sizes: min={min(sizes)}, max={max(sizes)}, avg={sum(sizes)//len(sizes)} chars")
    print(f"Chunks <200 chars: {sum(1 for s in sizes if s < 200)} (should be 0)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="./data")
    p.add_argument("--chroma-dir", default="./chroma_store")
    args = p.parse_args()
    ingest(args.data_dir, args.chroma_dir)
