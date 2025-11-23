"""Chunks patch notes and indexes them in ChromaDB for retrieval.

Each chunk is roughly one champion's section of a patch note, plus any
item/system changes as separate chunks. The PatchContextAgent queries
this to find relevant context for a given champion or draft situation.
"""
import logging
import re

import chromadb

from draft_analyst.config import CHROMA_DIR
from draft_analyst.domain.models import PatchNote

log = logging.getLogger(__name__)

COLLECTION_NAME = "patch_notes"


def _chunk_patch_notes(note: PatchNote) -> list[dict]:
    """Split a patch note into per-section chunks.

    Splits on champion names / section headers. Each chunk gets metadata
    with the patch version and which champion(s) it's about.
    """
    chunks = []
    content = note.content

    # split on blank lines followed by a capitalized header line
    # patch notes look like: \n\nAmbessa\nBase armor reduced...
    sections = re.split(r"\n\n(?=[A-Z][a-zA-Z'\- ]+\n)", content)

    for section in sections:
        section = section.strip()
        if not section or len(section) < 30:
            continue

        # first line is usually the champion/section name
        lines = section.split("\n", 1)
        header = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""

        if not body:
            continue

        # figure out what kind of section this is
        section_type = "general"
        mentioned_champs = []
        for champ in note.champions_mentioned:
            if champ.lower() in section.lower():
                mentioned_champs.append(champ)
                section_type = "champion"

        if any(kw in header.lower() for kw in ["items", "item", "systems", "baron", "dragon"]):
            section_type = "system"

        chunk_text = f"Patch {note.patch} - {header}\n{body}"

        chunks.append({
            "text": chunk_text,
            "metadata": {
                "patch": note.patch,
                "section": header,
                "type": section_type,
                "champions": ",".join(mentioned_champs) if mentioned_champs else "",
            },
        })

    # if we got no meaningful chunks, just store the whole thing as one chunk
    if not chunks and len(content) > 50:
        chunks.append({
            "text": f"Patch {note.patch}\n{content}",
            "metadata": {
                "patch": note.patch,
                "section": "full",
                "type": "general",
                "champions": ",".join(note.champions_mentioned),
            },
        })

    return chunks


class PatchIndex:
    def __init__(self, persist_dir: str | None = None):
        path = persist_dir or str(CHROMA_DIR)
        self.client = chromadb.PersistentClient(path=path)
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def index_notes(self, notes: list[PatchNote]) -> int:
        """Chunk and index a list of patch notes. Returns number of chunks added."""
        total = 0
        for note in notes:
            chunks = _chunk_patch_notes(note)
            if not chunks:
                continue

            ids = [f"{note.patch}_{i}" for i in range(len(chunks))]
            documents = [c["text"] for c in chunks]
            metadatas = [c["metadata"] for c in chunks]

            # upsert so re-indexing is idempotent
            self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
            total += len(chunks)
            log.info(f"indexed {len(chunks)} chunks for patch {note.patch}")

        log.info(f"total chunks indexed: {total}")
        return total

    def search(self, query: str, n_results: int = 5, patch: str | None = None) -> list[dict]:
        """Semantic search over patch notes. Returns matching chunks."""
        where = {"patch": patch} if patch else None
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
        )

        hits = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                dist = results["distances"][0][i] if results["distances"] else 0
                hits.append({
                    "text": doc,
                    "patch": meta.get("patch", ""),
                    "section": meta.get("section", ""),
                    "type": meta.get("type", ""),
                    "champions": meta.get("champions", ""),
                    "distance": dist,
                })

        return hits

    def search_champion(self, champion: str, n_results: int = 3) -> list[dict]:
        """Find patch note chunks mentioning a specific champion."""
        # semantic search using champion name, then filter results
        # that actually mention the champion (chroma's $contains doesn't
        # work for substring matching on string metadata, so we filter after)
        results = self.collection.query(
            query_texts=[f"{champion} changes buffs nerfs"],
            n_results=n_results * 2,  # fetch extra, filter down
        )

        hits = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                # only keep chunks that actually mention this champion
                if champion.lower() in doc.lower():
                    hits.append({
                        "text": doc,
                        "patch": meta.get("patch", ""),
                        "section": meta.get("section", ""),
                        "champions": meta.get("champions", ""),
                    })
                if len(hits) >= n_results:
                    break

        return hits

    def count(self) -> int:
        return self.collection.count()
