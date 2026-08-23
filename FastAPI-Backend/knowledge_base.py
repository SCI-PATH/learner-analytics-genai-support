"""
Local RAG pipeline for Grade 6–9 Science syllabus PDFs.

Uses LangChain for PDF loading and paragraph-aware chunking, ChromaDB (persistent
client + local embeddings) for the vector store. No cloud API keys required.

Install (inside your project venv):
    pip install langchain langchain-community langchain-text-splitters
    pip install chromadb pypdf sentence-transformers

Build / refresh the index:
    python knowledge_base.py --rebuild

Use from code:
    from knowledge_base import retrieve_context
    facts = retrieve_context("G8_C11_PHO_PROCESS")
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Any, Optional

from curriculum_topics import (
    FALLBACK_TOPIC_ID,
    TOPIC_KEYWORDS,
    TOPIC_QUERY_BOOST,
    normalize_topic_id,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_SYLLABUS_DIR = PROJECT_ROOT / "Data" / "Syllabi"
_SYLLABUS_PDF_SPECS: list[tuple[Path, int]] = [
    (_SYLLABUS_DIR / "Grade 6" / "science G-6 E (1).pdf", 6),
    (_SYLLABUS_DIR / "Grade 7" / "science G-7 P-I E.pdf", 7),
    (_SYLLABUS_DIR / "Grade 7" / "Grade_7_TextBook_English_Part_2.pdf", 7),
    (_SYLLABUS_DIR / "Grade 8" / "science G8 P-I E.pdf", 8),
    (_SYLLABUS_DIR / "Grade 8" / "science G-8 P-II E.pdf", 8),
    (_SYLLABUS_DIR / "Grade 9" / "science G-9 P-I E.pdf", 9),
    (_SYLLABUS_DIR / "Grade 9" / "Science Part II English G-9.pdf", 9),
]
_LEGACY_PDF_SPECS: list[tuple[Path, int]] = [
    (_SYLLABUS_DIR / "science G-6 E (1).pdf", 6),
    (_SYLLABUS_DIR / "science G-7 P-I E.pdf", 7),
    (_SYLLABUS_DIR / "science G8 P-I E.pdf", 8),
    (_SYLLABUS_DIR / "science G-9 P-I E.pdf", 9),
]

_TEXTBOOK_DIR = Path(
    os.environ.get("TEXTBOOK_PDF_ROOT", "").strip()
    or str(_SYLLABUS_DIR / "textbooks")
)
_TEXTBOOK_PDF_SPECS: list[tuple[Path, int]] = [
    (_TEXTBOOK_DIR / "science G-6 E.pdf", 6),
    (_TEXTBOOK_DIR / "science G-7 P-I E.pdf", 7),
    (_TEXTBOOK_DIR / "science G-7 P-II E.pdf", 7),
    (_TEXTBOOK_DIR / "science G8 P-I E.pdf", 8),
    (_TEXTBOOK_DIR / "science G-8 P-II E.pdf", 8),
    (_TEXTBOOK_DIR / "science G-9 P-I E.pdf", 9),
    (_TEXTBOOK_DIR / "Science Part II English G-9.pdf", 9),
]
_CHROMA_DIR = PROJECT_ROOT / ".chroma_science_g6_g9"
_COLLECTION = "science_syllabus_g6_g9"
_EMBED_MODEL = "all-MiniLM-L6-v2"
_CHROMA_ADD_BATCH = 256

# Re-export for modules that import keyword maps from knowledge_base.
_TOPIC_KEYWORDS = TOPIC_KEYWORDS
_TOPIC_QUERY_BOOST = TOPIC_QUERY_BOOST


def _resolve_pdf_specs() -> list[tuple[Path, int]]:
    for resolver in (_SYLLABUS_PDF_SPECS, _TEXTBOOK_PDF_SPECS, _LEGACY_PDF_SPECS):
        specs = [(p, g) for p, g in resolver if p.is_file()]
        if specs:
            return specs
    raise FileNotFoundError(
        "No syllabus PDFs found under Data/Syllabi (Grade folders, textbooks mount, or root copies)."
    )


def _grade_from_topic_id(topic_id: str) -> Optional[int]:
    match = re.match(r"^G(\d+)_", topic_id)
    if not match:
        return None
    return int(match.group(1))


def _score_chunk_for_topic(text: str, keywords: list[str]) -> int:
    low = text.lower()
    score = 0
    for kw in keywords:
        if kw.lower() in low:
            score += low.count(kw.lower()) + 3
    return score


def _infer_primary_topic_id(chunk_text: str, *, grade: Optional[int] = None) -> str:
    """Tag a chunk with the best-matching curriculum topic (optionally same grade only)."""
    best_id = f"G{grade}_GENERAL" if grade else "SCIENCE_GENERAL"
    best_score = 0
    for topic_id, kws in _TOPIC_KEYWORDS.items():
        if grade is not None:
            topic_grade = _grade_from_topic_id(topic_id)
            if topic_grade != grade:
                continue
        score = _score_chunk_for_topic(chunk_text, kws)
        if score > best_score:
            best_score = score
            best_id = topic_id
    return best_id


def _clean_page_text(text: str) -> str:
    text = re.sub(r"-\s*\n", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[^\S\n]+", " ", text)
    return text.strip()


def _chroma_safe_metadata(meta: dict[str, Any]) -> dict[str, Any]:
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
    Loads Grade 6–9 syllabus PDFs, chunks them, embeds into a local Chroma store,
    and answers retrieve_context(topic_id) with similarity search + metadata filters.
    """

    def __init__(
        self,
        pdf_specs: Optional[list[tuple[Path | str, int]]] = None,
        persist_directory: Optional[Path | str] = None,
    ) -> None:
        self.base_dir = PROJECT_ROOT
        if pdf_specs is None:
            raw_specs = _resolve_pdf_specs()
        else:
            raw_specs = [(Path(p), int(g)) for p, g in pdf_specs]
        self.pdf_specs = raw_specs
        self.persist_directory = Path(persist_directory) if persist_directory else _CHROMA_DIR
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
        """Extract all syllabus PDFs, chunk, tag metadata, embed, and persist Chroma."""
        import chromadb
        from langchain_community.document_loaders import PyPDFLoader
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        if not self.pdf_specs:
            raise FileNotFoundError("No syllabus PDF specs configured.")
        for pdf_path, _grade in self.pdf_specs:
            if not pdf_path.is_file():
                raise FileNotFoundError(f"Syllabus PDF not found: {pdf_path}")

        if force_rebuild and self.persist_directory.is_dir():
            import shutil

            shutil.rmtree(self.persist_directory, ignore_errors=True)

        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self._reset_chroma_handles()

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1200,
            chunk_overlap=200,
            length_function=len,
            separators=["\n\n\n", "\n\n", "\n", ". ", " ", ""],
        )

        all_splits: list[Any] = []
        for pdf_path, grade in self.pdf_specs:
            loader = PyPDFLoader(str(pdf_path))
            pages = loader.load()
            for doc in pages:
                doc.page_content = _clean_page_text(doc.page_content)

            splits = splitter.split_documents(pages)
            for doc in splits:
                primary = _infer_primary_topic_id(doc.page_content, grade=grade)
                doc.metadata = dict(doc.metadata)
                doc.metadata["topic_id_primary"] = primary
                doc.metadata["source_pdf"] = pdf_path.name
                doc.metadata["grade"] = grade
            all_splits.extend(splits)
            print(f"  chunked {pdf_path.name}: {len(splits)} chunks (grade {grade})")

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
        for i, doc in enumerate(all_splits):
            grade = doc.metadata.get("grade", 0)
            ids.append(f"g{grade}_chunk_{i:06d}")
            documents.append(doc.page_content)
            metadatas.append(_chroma_safe_metadata(doc.metadata))

        for start in range(0, len(ids), _CHROMA_ADD_BATCH):
            end = start + _CHROMA_ADD_BATCH
            col.add(ids=ids[start:end], documents=documents[start:end], metadatas=metadatas[start:end])

        self._chroma_client = client
        self._collection = col
        print(f"Indexed {len(ids)} chunks from {len(self.pdf_specs)} PDFs -> {self.persist_directory}")

    def _ensure_collection_loaded(self) -> Any:
        if not self._index_ready():
            raise FileNotFoundError(
                f"No vector index at {self.persist_directory}. Run: python knowledge_base.py --rebuild"
            )
        return self._get_chroma_collection()

    def ensure_index(self, force_rebuild: bool = False) -> None:
        if force_rebuild or not self._index_ready():
            self.build_index(force_rebuild=True)

    def retrieve_context(self, topic_id: str, k: int = 5) -> dict[str, Any]:
        """Return syllabus excerpts for a curriculum topic_id (metadata-filtered when possible)."""
        topic_id = normalize_topic_id(topic_id)
        col = self._ensure_collection_loaded()
        grade = _grade_from_topic_id(topic_id)
        boost = _TOPIC_QUERY_BOOST.get(
            topic_id,
            f"Grade {grade or ''} science. Topic code {topic_id}.",
        )
        query = f"{topic_id} {boost}"

        def _where_filter() -> Optional[dict[str, Any]]:
            if grade is not None:
                return {"$and": [{"topic_id_primary": topic_id}, {"grade": grade}]}
            return {"topic_id_primary": topic_id}

        try:
            res = col.query(
                query_texts=[query],
                n_results=max(k * 3, 8),
                where=_where_filter(),
            )
        except Exception:
            res = col.query(query_texts=[query], n_results=max(k * 3, 8))

        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        filtered_rows: list[tuple[str, dict[str, Any]]] = []
        for text, meta in zip(docs, metas):
            filtered_rows.append((text or "", dict(meta or {})))

        if not filtered_rows and grade is not None:
            try:
                res2 = col.query(
                    query_texts=[query],
                    n_results=max(k * 3, 8),
                    where={"grade": grade},
                )
                docs2 = (res2.get("documents") or [[]])[0]
                metas2 = (res2.get("metadatas") or [[]])[0]
                for text, meta in zip(docs2, metas2):
                    filtered_rows.append((text or "", dict(meta or {})))
            except Exception:
                pass

        if not filtered_rows:
            res3 = col.query(query_texts=[query], n_results=k)
            docs3 = (res3.get("documents") or [[]])[0]
            metas3 = (res3.get("metadatas") or [[]])[0]
            for text, meta in zip(docs3, metas3):
                filtered_rows.append((text or "", dict(meta or {})))

        contexts: list[dict[str, Any]] = []
        for rank, (page_content, doc_meta) in enumerate(filtered_rows[:k], start=1):
            meta = {
                str(a): (b if isinstance(b, (str, int, float, bool)) else str(b))
                for a, b in doc_meta.items()
            }
            contexts.append({"rank": rank, "text": page_content, "metadata": meta})

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
    """Module-level helper; builds index on first use if `.chroma_science_g6_g9` is missing."""
    return get_knowledge_base().retrieve_context(normalize_topic_id(topic_id), k=k)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or query local Grade 6–9 science RAG index.")
    parser.add_argument("--rebuild", action="store_true", help="Delete existing Chroma data and rebuild.")
    parser.add_argument(
        "--topic",
        type=str,
        default=None,
        help="If set, run retrieve_context(topic) after build (e.g. G8_C11_PHO_PROCESS).",
    )
    args = parser.parse_args()
    kb = LocalScienceKnowledgeBase()
    kb.ensure_index(force_rebuild=args.rebuild)
    print(f"Index ready at {kb.persist_directory} ({len(kb.pdf_specs)} PDFs)")
    if args.topic:
        out = kb.retrieve_context(args.topic, k=4)
        print("--- sample facts_text (truncated) ---")
        print(out["facts_text"][:1500] + ("..." if len(out["facts_text"]) > 1500 else ""))
    else:
        print(f"Fallback topic: {FALLBACK_TOPIC_ID}")


if __name__ == "__main__":
    main()
