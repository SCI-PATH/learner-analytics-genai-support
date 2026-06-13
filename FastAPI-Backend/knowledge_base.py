"""
Local RAG pipeline for the Grade 6 Science syllabus PDF (Epic 2 prep).

Uses LangChain for PDF loading and paragraph-aware chunking, ChromaDB (persistent
client + local embeddings) for the vector store. No cloud API keys required.

Install (inside your project venv):
    pip install langchain langchain-community langchain-text-splitters
    pip install chromadb pypdf sentence-transformers

Build / refresh the index:
    python knowledge_base.py

Use from code:
    from knowledge_base import retrieve_context
    facts = retrieve_context("G6_S8_ELE_CIRCUITS")
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Optional

# --- Defaults (same folder as this file) ---
_DEFAULT_PDF = "science G-6 E (1).pdf"
_CHROMA_DIR = ".chroma_science_g6"
_COLLECTION = "science_g6_syllabus"
_EMBED_MODEL = "all-MiniLM-L6-v2"  # sentence-transformers id (Chroma embedding_fn)
_CHROMA_ADD_BATCH = 256

# Topic IDs used by the learner profile / Skill-Heirarchies → retrieval hints (syllabus-aligned).
# Chunks are tagged with the best-matching topic_id by keyword overlap on the chunk text.
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "G6_S1_ORG_CLASS": [
        "classification",
        "classify",
        "living things",
        "organism",
        "kingdom",
        "vertebrate",
        "invertebrate",
    ],
    "G6_S1_ORG_CHARS": [
        "characteristics",
        "living",
        "movement",
        "nutrition",
        "respiration",
        "reproduction",
        "growth",
        "excretion",
        "sensitivity",
    ],
    "G6_S2_MAT_PROPS": [
        "properties of matter",
        "density",
        "hardness",
        "solubility",
        "conductivity",
        "melting",
        "boiling",
    ],
    "G6_S2_MAT_STATES": [
        "states of matter",
        "solid",
        "liquid",
        "gas",
        "particle",
        "melting",
        "freezing",
        "evaporation",
        "condensation",
    ],
    "G6_S4_ENE_SOURCES": [
        "energy",
        "source",
        "renewable",
        "non-renewable",
        "fuel",
        "fossil",
        "solar",
        "wind",
    ],
    "G6_S8_ELE_CIRCUITS": [
        "electric circuit",
        "circuit",
        "current",
        "switch",
        "bulb",
        "lamp",
        "cell",
        "battery",
        "wire",
        "series",
        "parallel",
    ],
    "G6_S8_ELE_CONDINS": [
        "conductor",
        "insulator",
        "conducting",
        "insulating",
        "metal",
        "plastic",
        "rubber",
        "wood",
    ],
}

# Natural-language boost for semantic search when topic_id alone is sparse.
_TOPIC_QUERY_BOOST: dict[str, str] = {
    "G6_S1_ORG_CLASS": "Organisation of living things: classification and grouping organisms.",
    "G6_S1_ORG_CHARS": "Characteristics of living things and life processes.",
    "G6_S2_MAT_PROPS": "Physical and chemical properties of matter.",
    "G6_S2_MAT_STATES": "States of matter, particles, and changes of state.",
    "G6_S4_ENE_SOURCES": "Energy types and energy sources including renewable and non-renewable.",
    "G6_S8_ELE_CIRCUITS": "Electric circuits, current, switches, cells, and lamps.",
    "G6_S8_ELE_CONDINS": "Conductors and insulators in electricity.",
}


def _score_chunk_for_topic(text: str, keywords: list[str]) -> int:
    low = text.lower()
    score = 0
    for kw in keywords:
        if kw.lower() in low:
            score += low.count(kw.lower()) + 3  # bonus for any hit
    return score


def _infer_primary_topic_id(chunk_text: str) -> str:
    best_id = "G6_GENERAL"
    best_score = 0
    for topic_id, kws in _TOPIC_KEYWORDS.items():
        s = _score_chunk_for_topic(chunk_text, kws)
        if s > best_score:
            best_score = s
            best_id = topic_id
    return best_id


def _clean_page_text(text: str) -> str:
    # Collapse broken lines from PDF extraction; keep paragraph boundaries.
    text = re.sub(r"-\s*\n", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[^\S\n]+", " ", text)
    return text.strip()


def _chroma_safe_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Chroma metadata values must be str, int, float, or bool."""
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool)):
            out[str(k)] = v
        elif v is None:
            out[str(k)] = ""
        else:
            out[str(k)] = str(v)
    return out


class LocalScienceKnowledgeBase:
    """
    Loads the Grade 6 syllabus PDF, chunks it, embeds into a local Chroma store,
    and answers retrieve_context(topic_id) with similarity search + topic hints.
    """

    def __init__(
        self,
        pdf_path: Optional[Path | str] = None,
        persist_directory: Optional[Path | str] = None,
    ) -> None:
        self.base_dir = Path(__file__).resolve().parent
        self.pdf_path = Path(pdf_path) if pdf_path else self.base_dir / _DEFAULT_PDF
        self.persist_directory = Path(persist_directory) if persist_directory else self.base_dir / _CHROMA_DIR
        self._chroma_client: Any = None
        self._collection: Any = None
        self._embedding_fn: Any = None

    def _get_embedding_fn(self) -> Any:
        if self._embedding_fn is None:
            from chromadb.utils import embedding_functions

            self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=_EMBED_MODEL,
            )
        return self._embedding_fn

    def _reset_chroma_handles(self) -> None:
        self._chroma_client = None
        self._collection = None

    def _get_chroma_collection(self) -> Any:
        import chromadb

        if self._collection is not None:
            return self._collection
        self._chroma_client = chromadb.PersistentClient(path=str(self.persist_directory))
        self._collection = self._chroma_client.get_collection(
            name=_COLLECTION,
            embedding_function=self._get_embedding_fn(),
        )
        return self._collection

    def _index_ready(self) -> bool:
        p = self.persist_directory
        if not p.is_dir():
            return False
        return any(p.iterdir())

    def build_index(self, force_rebuild: bool = False) -> None:
        """
        Extract text from the PDF, split into paragraph-style chunks,
        attach topic metadata, embed, and persist Chroma locally.
        """
        if not self.pdf_path.is_file():
            raise FileNotFoundError(f"Syllabus PDF not found: {self.pdf_path}")

        import chromadb
        from langchain_community.document_loaders import PyPDFLoader
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        if force_rebuild and self.persist_directory.is_dir():
            import shutil

            shutil.rmtree(self.persist_directory, ignore_errors=True)

        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self._reset_chroma_handles()

        loader = PyPDFLoader(str(self.pdf_path))
        pages = loader.load()
        for doc in pages:
            doc.page_content = _clean_page_text(doc.page_content)

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1200,
            chunk_overlap=200,
            length_function=len,
            separators=["\n\n\n", "\n\n", "\n", ". ", " ", ""],
        )
        splits = splitter.split_documents(pages)

        for doc in splits:
            primary = _infer_primary_topic_id(doc.page_content)
            doc.metadata = dict(doc.metadata)
            doc.metadata["topic_id_primary"] = primary
            doc.metadata["source_pdf"] = self.pdf_path.name

        client = chromadb.PersistentClient(path=str(self.persist_directory))
        try:
            client.delete_collection(_COLLECTION)
        except Exception:
            pass
        col = client.get_or_create_collection(
            name=_COLLECTION,
            embedding_function=self._get_embedding_fn(),
        )

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for i, doc in enumerate(splits):
            ids.append(f"g6_chunk_{i:06d}")
            documents.append(doc.page_content)
            metadatas.append(_chroma_safe_metadata(doc.metadata))

        for start in range(0, len(ids), _CHROMA_ADD_BATCH):
            end = start + _CHROMA_ADD_BATCH
            col.add(ids=ids[start:end], documents=documents[start:end], metadatas=metadatas[start:end])

        self._chroma_client = client
        self._collection = col

    def _ensure_collection_loaded(self) -> Any:
        if not self._index_ready():
            raise FileNotFoundError(
                f"No vector index at {self.persist_directory}. Run: python knowledge_base.py"
            )
        return self._get_chroma_collection()

    def ensure_index(self, force_rebuild: bool = False) -> None:
        if force_rebuild or not self._index_ready():
            self.build_index(force_rebuild=force_rebuild)
        self._ensure_collection_loaded()

    def retrieve_context(self, topic_id: str, k: int = 5) -> dict[str, Any]:
        """
        Return the most relevant syllabus excerpts for a curriculum topic_id.

        Output is JSON-serializable (strings, ints, lists of dicts).
        """
        self.ensure_index()
        col = self._ensure_collection_loaded()

        boost = _TOPIC_QUERY_BOOST.get(
            topic_id,
            f"Grade 6 science. Topic code {topic_id}.",
        )
        query = f"{topic_id} {boost}"

        def _rows_from_chroma_result(res: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
            docs_batch = (res.get("documents") or [[]])[0] or []
            metas_batch = (res.get("metadatas") or [[]])[0] or []
            rows: list[tuple[str, dict[str, Any]]] = []
            for i, text in enumerate(docs_batch):
                meta = metas_batch[i] if i < len(metas_batch) else {}
                rows.append((text, dict(meta) if isinstance(meta, dict) else {}))
            return rows

        filtered_rows: list[tuple[str, dict[str, Any]]] = []
        try:
            fr = col.query(
                query_texts=[query],
                n_results=k,
                where={"topic_id_primary": topic_id},
            )
            filtered_rows = _rows_from_chroma_result(fr)
        except Exception:
            filtered_rows = []

        if len(filtered_rows) < max(2, k // 2):
            br = col.query(query_texts=[query], n_results=k)
            broad_rows = _rows_from_chroma_result(br)
            seen = {t for t, _ in filtered_rows}
            for text, meta in broad_rows:
                if text not in seen:
                    filtered_rows.append((text, meta))
                    seen.add(text)
                if len(filtered_rows) >= k:
                    break
        else:
            filtered_rows = filtered_rows[:k]

        contexts: list[dict[str, Any]] = []
        for rank, (page_content, doc_meta) in enumerate(filtered_rows[:k], start=1):
            meta = {
                str(a): (b if isinstance(b, (str, int, float, bool)) else str(b))
                for a, b in doc_meta.items()
            }
            contexts.append(
                {
                    "rank": rank,
                    "text": page_content,
                    "metadata": meta,
                }
            )

        merged_text = "\n\n---\n\n".join(c["text"] for c in contexts)

        return {
            "topic_id": topic_id,
            "query_used": query,
            "chunks_returned": len(contexts),
            "contexts": contexts,
            "facts_text": merged_text,
        }


_default_kb: Optional[LocalScienceKnowledgeBase] = None


def get_knowledge_base() -> LocalScienceKnowledgeBase:
    global _default_kb
    if _default_kb is None:
        _default_kb = LocalScienceKnowledgeBase()
    return _default_kb


def retrieve_context(topic_id: str, *, k: int = 5) -> dict[str, Any]:
    """
    Module-level helper for FastAPI / other modules.
    Builds the index on first use if `.chroma_science_g6` is missing.
    """
    return get_knowledge_base().retrieve_context(topic_id, k=k)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or query local Grade 6 science RAG index.")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete existing Chroma data and rebuild from PDF.",
    )
    parser.add_argument(
        "--topic",
        type=str,
        default=None,
        help="If set, run retrieve_context(topic) after build (e.g. G6_S8_ELE_CIRCUITS).",
    )
    args = parser.parse_args()
    kb = LocalScienceKnowledgeBase()
    kb.ensure_index(force_rebuild=args.rebuild)
    print(f"Index ready at {kb.persist_directory}")
    if args.topic:
        out = kb.retrieve_context(args.topic, k=4)
        print("--- sample facts_text (truncated) ---")
        print(out["facts_text"][:1500] + ("..." if len(out["facts_text"]) > 1500 else ""))


if __name__ == "__main__":
    main()
