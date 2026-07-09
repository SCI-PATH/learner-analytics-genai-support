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
    facts = retrieve_context("G7_S3_ELE_CURRENTS")
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_SYLLABUS_DIR = PROJECT_ROOT / "Data" / "Syllabi"
_SYLLABUS_PDF_SPECS: list[tuple[Path, int]] = [
    (_SYLLABUS_DIR / "science G-6 E (1).pdf", 6),
    (_SYLLABUS_DIR / "science G-7 P-I E.pdf", 7),
    (_SYLLABUS_DIR / "science G8 P-I E.pdf", 8),
    (_SYLLABUS_DIR / "science G-9 P-I E.pdf", 9),
]
_CHROMA_DIR = PROJECT_ROOT / ".chroma_science_g6_g9"
_COLLECTION = "science_syllabus_g6_g9"
_EMBED_MODEL = "all-MiniLM-L6-v2"
_CHROMA_ADD_BATCH = 256

# Topic IDs → retrieval / chunk-tagging keywords (grades 6–9).
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    # --- Grade 6 ---
    "G6_S1_ORG_CLASS": [
        "classification", "classify", "living things", "organism", "kingdom",
        "vertebrate", "invertebrate",
    ],
    "G6_S1_ORG_CHARS": [
        "characteristics", "living", "movement", "nutrition", "respiration",
        "reproduction", "growth", "excretion", "sensitivity",
    ],
    "G6_S2_MAT_PROPS": [
        "properties of matter", "density", "hardness", "solubility", "conductivity",
        "melting", "boiling", "malleability",
    ],
    "G6_S2_MAT_STATES": [
        "states of matter", "solid", "liquid", "gas", "particle", "melting",
        "freezing", "evaporation", "condensation",
    ],
    "G6_S4_ENE_SOURCES": [
        "energy", "source", "renewable", "non-renewable", "fuel", "fossil",
        "solar", "wind",
    ],
    "G6_S8_ELE_CIRCUITS": [
        "electric circuit", "circuit", "current", "switch", "bulb", "lamp", "cell",
        "battery", "wire", "series", "parallel",
    ],
    "G6_S8_ELE_CONDINS": [
        "conductor", "insulator", "conducting", "insulating", "metal", "plastic",
        "rubber", "wood",
    ],
    # --- Grade 7 ---
    "G7_S1_PLA_DIVER": [
        "morphological", "plant", "leaf", "root", "stem", "flower", "diversity",
        "features of plants",
    ],
    "G7_S1_PLA_CLASSIF": [
        "monocot", "dicot", "monocots", "dicots", "plant classification",
        "cotyledon", "seed leaf",
    ],
    "G7_S2_STA_CHARGES": [
        "static", "charging", "charge", "electrostatic", "friction", "rubbing",
        "static electricity",
    ],
    "G7_S2_STA_CAPACIT": [
        "capacitor", "capacitance", "static electricity", "store charge",
    ],
    "G7_S3_ELE_SOURCES": [
        "electricity generation", "power station", "generator", "hydro", "thermal",
        "solar panel", "wind turbine",
    ],
    "G7_S3_ELE_CURRENTS": [
        "electric current", "direct current", "alternating current", "dc", "ac",
        "ammeter", "flow of charge",
    ],
    "G7_S4_WAT_SOLVENT": [
        "universal solvent", "dissolve", "dissolving", "solute", "solution",
        "water as solvent",
    ],
    "G7_S4_WAT_COOLANT": [
        "coolant", "cooling", "thermal properties of water", "heat capacity",
    ],
    "G7_S5_ACI_IDENTIF": [
        "acid", "base", "alkali", "identify acid", "identify base", "litmus",
        "laboratory acid",
    ],
    "G7_S5_ACI_INDICAT": [
        "ph indicator", "indicator", "neutralization", "neutralise", "ph scale",
        "universal indicator",
    ],
    "G7_S6_ANI_CLASSIF": [
        "vertebrate", "invertebrate", "dichotomous", "classification key",
        "animal classification",
    ],
    "G7_S6_ANI_ADAPTAT": [
        "adaptation", "adapted", "habitat", "survive", "camouflage", "migration",
    ],
    "G7_S7_ENE_FORMS": [
        "kinetic energy", "potential energy", "thermal energy", "chemical energy",
        "forms of energy",
    ],
    "G7_S7_ENE_TRANSF": [
        "energy transformation", "energy transfer", "convert energy",
        "conservation of energy",
    ],
    "G7_S8_EAR_STRUCT": [
        "earth structure", "crust", "mantle", "core", "inner core", "outer core",
        "layers of the earth",
    ],
    "G7_S8_EAR_TECTON": [
        "tectonic", "plate", "plate movement", "earthquake", "volcano",
        "continental drift",
    ],
    "G7_S9_LIG_SHADOWS": [
        "shadow", "umbra", "penumbra", "opaque", "light source", "eclipse",
    ],
    "G7_S9_LIG_MIRRORS": [
        "mirror", "reflection", "plane mirror", "curved mirror", "image",
        "reflected light",
    ],
    "G7_S10_MIC_LIGHT": [
        "light microscope", "compound microscope", "magnification", "eyepiece",
        "objective lens",
    ],
    "G7_S10_MIC_ELECTR": [
        "electron microscope", "resolution", "electron beam", "microscope",
    ],
    # --- Grade 8 ---
    "G8_S1_BIO_DIVER": [
        "biodiversity", "diversity", "microorganism", "micro-organism", "species",
    ],
    "G8_S1_BIO_CLASSIF": [
        "binomial", "nomenclature", "taxonomy", "classification framework",
        "scientific name",
    ],
    "G8_S2_TIS_PLANT": [
        "plant tissue", "meristematic", "permanent tissue", "xylem", "phloem",
        "epidermis",
    ],
    "G8_S2_TIS_ANIMAL": [
        "animal tissue", "epithelial", "connective", "muscular", "nervous tissue",
    ],
    "G8_S3_PHO_PROCESS": [
        "photosynthesis", "chlorophyll", "carbon dioxide", "glucose", "starch",
        "light energy",
    ],
    "G8_S3_PHO_IMPORT": [
        "importance of photosynthesis", "food chain", "oxygen", "ecosystem",
        "producers",
    ],
    "G8_S4_MAT_ELEMENTS": [
        "element", "chemical symbol", "periodic table", "atom", "pure substance",
    ],
    "G8_S4_MAT_COMPOUNDS": [
        "compound", "chemical compound", "mixture", "molecule", "formula",
    ],
    "G8_S5_MAT_DENSITY": [
        "density", "mass per volume", "float", "sink", "relative density",
    ],
    "G8_S5_MAT_THERMAL": [
        "thermal conductivity", "electrical conductivity", "insulator", "conductor",
        "heat transfer",
    ],
    "G8_S6_CHA_PHYSICAL": [
        "physical change", "reversible change", "state change", "no new substance",
    ],
    "G8_S6_CHA_BURNING": [
        "combustion", "burning", "ignition", "bunsen burner", "flammable",
        "fire triangle",
    ],
    "G8_S7_FOR_TYPES": [
        "force", "gravitational", "magnetic", "friction", "contact force",
        "non-contact",
    ],
    "G8_S7_FOR_PRESSURE": [
        "pressure", "pascal", "force per area", "hydraulic", "atmospheric pressure",
    ],
    "G8_S8_STA_PHENOM": [
        "electrostatic attraction", "electrostatic repulsion", "charged object",
        "static discharge",
    ],
    "G8_S8_STA_LIGHTNG": [
        "lightning", "thunderstorm", "earthing", "lightning conductor", "static",
    ],
    # --- Grade 9 ---
    "G9_S1_SYS_DIGEST": [
        "digestive", "digestion", "enzyme", "stomach", "intestine", "oesophagus",
        "nutrient absorption",
    ],
    "G9_S1_SYS_CIRCUL": [
        "circulatory", "respiratory", "excretory", "heart", "blood", "lung",
        "kidney", "circulation",
    ],
    "G9_S2_RHY_EARTH": [
        "rotation", "revolution", "day and night", "seasons", "rhythmic",
        "earth cycle",
    ],
    "G9_S2_RHY_CLIMATE": [
        "climate", "monsoon", "ecosystem cycle", "rhythmic phenomenon",
        "weather pattern",
    ],
    "G9_S3_LIG_REFRAC": [
        "refraction", "refractive index", "critical angle", "total internal reflection",
        "bending of light",
    ],
    "G9_S3_LIG_LENSES": [
        "convex lens", "concave lens", "real image", "virtual image", "focal length",
        "magnification",
    ],
    "G9_S4_SOU_PROPAG": [
        "sound", "frequency", "amplitude", "wavelength", "propagation", "medium",
        "vibration",
    ],
    "G9_S4_SOU_HEARING": [
        "ear", "hearing", "auditory", "eardrum", "cochlea", "decibel", "ultrasound",
    ],
    "G9_S5_HEA_EXPANS": [
        "thermal expansion", "expand", "contract", "bimetallic", "gaps in railway",
    ],
    "G9_S5_HEA_TRANSF": [
        "conduction", "convection", "radiation", "heat transfer", "thermal physics",
    ],
    "G9_S6_NAT_ATOMS": [
        "atomic model", "subatomic", "proton", "neutron", "electron", "atomic number",
        "nucleus",
    ],
    "G9_S6_NAT_CONFIG": [
        "electronic configuration", "electron shell", "valence", "periodic table group",
    ],
    "G9_S7_ACI_SALTS": [
        "salt", "acid", "base", "indicator", "salt preparation", "neutralisation",
    ],
    "G9_S7_ACI_NEUTRAL": [
        "neutralization", "neutralisation", "antacid", "agricultural lime",
        "industrial acid",
    ],
}

_TOPIC_QUERY_BOOST: dict[str, str] = {
    # Grade 6
    "G6_S1_ORG_CLASS": "Organisation of living things: classification and grouping organisms.",
    "G6_S1_ORG_CHARS": "Characteristics of living things and life processes.",
    "G6_S2_MAT_PROPS": "Physical and chemical properties of matter.",
    "G6_S2_MAT_STATES": "States of matter, particles, and changes of state.",
    "G6_S4_ENE_SOURCES": "Energy types and energy sources including renewable and non-renewable.",
    "G6_S8_ELE_CIRCUITS": "Electric circuits, current, switches, cells, and lamps.",
    "G6_S8_ELE_CONDINS": "Conductors and insulators in electricity.",
    # Grade 7
    "G7_S1_PLA_DIVER": "Morphological features and diversity of plants.",
    "G7_S1_PLA_CLASSIF": "Plant classification: monocots versus dicots.",
    "G7_S2_STA_CHARGES": "Charging objects and static electric charges.",
    "G7_S2_STA_CAPACIT": "Capacitors and static electricity applications.",
    "G7_S3_ELE_SOURCES": "Sources of electricity generation.",
    "G7_S3_ELE_CURRENTS": "Electric currents: direct current versus alternating current.",
    "G7_S4_WAT_SOLVENT": "Water as a universal solvent.",
    "G7_S4_WAT_COOLANT": "Water as a coolant and thermal properties.",
    "G7_S5_ACI_IDENTIF": "Identification of acids and bases.",
    "G7_S5_ACI_INDICAT": "pH indicators and neutralization.",
    "G7_S6_ANI_CLASSIF": "Vertebrates, invertebrates, and dichotomous keys.",
    "G7_S6_ANI_ADAPTAT": "Animal adaptations to environments.",
    "G7_S7_ENE_FORMS": "Forms of energy: kinetic, potential, thermal, chemical.",
    "G7_S7_ENE_TRANSF": "Energy transformation and transfer.",
    "G7_S8_EAR_STRUCT": "Earth's internal structure and layers.",
    "G7_S8_EAR_TECTON": "Tectonic plates and plate movements.",
    "G7_S9_LIG_SHADOWS": "Formation of shadows: umbra and penumbra.",
    "G7_S9_LIG_MIRRORS": "Light reflection on plane and curved mirrors.",
    "G7_S10_MIC_LIGHT": "Compound light microscope structure and magnification.",
    "G7_S10_MIC_ELECTR": "Electron microscope resolution and characteristics.",
    # Grade 8
    "G8_S1_BIO_DIVER": "Diversity of microorganisms, plants, and animals.",
    "G8_S1_BIO_CLASSIF": "Classification frameworks and binomial nomenclature.",
    "G8_S2_TIS_PLANT": "Plant tissues: meristematic and permanent.",
    "G8_S2_TIS_ANIMAL": "Animal tissues: epithelial, connective, muscular, nervous.",
    "G8_S3_PHO_PROCESS": "Photosynthesis mechanism and raw materials.",
    "G8_S3_PHO_IMPORT": "Importance of photosynthesis to ecosystems.",
    "G8_S4_MAT_ELEMENTS": "Characteristics of elements and chemical symbols.",
    "G8_S4_MAT_COMPOUNDS": "Formation of compounds and chemical mixtures.",
    "G8_S5_MAT_DENSITY": "Density principles, measurement, and calculations.",
    "G8_S5_MAT_THERMAL": "Thermal and electrical conductivity of matter.",
    "G8_S6_CHA_PHYSICAL": "Physical versus chemical changes in matter.",
    "G8_S6_CHA_BURNING": "Combustion, ignition temperature, and burning.",
    "G8_S7_FOR_TYPES": "Contact and non-contact forces.",
    "G8_S7_FOR_PRESSURE": "Pressure calculation and applications.",
    "G8_S8_STA_PHENOM": "Electrostatic attraction and repulsion.",
    "G8_S8_STA_LIGHTNG": "Thunderstorms, static discharge, and lightning protection.",
    # Grade 9
    "G9_S1_SYS_DIGEST": "Human digestive system and digestion enzymes.",
    "G9_S1_SYS_CIRCUL": "Circulatory, respiratory, and excretory coordination.",
    "G9_S2_RHY_EARTH": "Rhythmic cycles from Earth's rotation and revolution.",
    "G9_S2_RHY_CLIMATE": "Rhythmic phenomena, ecosystems, and climate.",
    "G9_S3_LIG_REFRAC": "Refraction, critical angle, and total internal reflection.",
    "G9_S3_LIG_LENSES": "Convex and concave lenses; real and virtual images.",
    "G9_S4_SOU_PROPAG": "Sound frequency, amplitude, and propagation.",
    "G9_S4_SOU_HEARING": "Human ear anatomy and hearing.",
    "G9_S5_HEA_EXPANS": "Thermal expansion of solids, liquids, and gases.",
    "G9_S5_HEA_TRANSF": "Heat transfer: conduction, convection, radiation.",
    "G9_S6_NAT_ATOMS": "Atomic models, subatomic particles, atomic number.",
    "G9_S6_NAT_CONFIG": "Electronic configuration and periodic table grouping.",
    "G9_S7_ACI_SALTS": "Acids, bases, indicators, and salt preparation.",
    "G9_S7_ACI_NEUTRAL": "Neutralization applications in industry and agriculture.",
}


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
        raw_specs = pdf_specs or _SYLLABUS_PDF_SPECS
        self.pdf_specs = [(Path(p), int(g)) for p, g in raw_specs]
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

    def _ensure_collection_loaded(self) -> Any:
        if not self._index_ready():
            raise FileNotFoundError(
                f"No vector index at {self.persist_directory}. Run: python knowledge_base.py --rebuild"
            )
        return self._get_chroma_collection()

    def ensure_index(self, force_rebuild: bool = False) -> None:
        if force_rebuild or not self._index_ready():
            self.build_index(force_rebuild=force_rebuild)
        self._ensure_collection_loaded()

    def retrieve_context(self, topic_id: str, k: int = 5) -> dict[str, Any]:
        """Return syllabus excerpts for a curriculum topic_id (metadata-filtered when possible)."""
        self.ensure_index()
        col = self._ensure_collection_loaded()

        grade = _grade_from_topic_id(topic_id)
        boost = _TOPIC_QUERY_BOOST.get(
            topic_id,
            f"Grade {grade or ''} science. Topic code {topic_id}.",
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

        def _topic_where() -> dict[str, Any]:
            if grade is not None:
                return {"$and": [{"topic_id_primary": topic_id}, {"grade": grade}]}
            return {"topic_id_primary": topic_id}

        filtered_rows: list[tuple[str, dict[str, Any]]] = []
        try:
            fr = col.query(
                query_texts=[query],
                n_results=k,
                where=_topic_where(),
            )
            filtered_rows = _rows_from_chroma_result(fr)
        except Exception:
            filtered_rows = []

        if len(filtered_rows) < max(2, k // 2):
            broad_where: Optional[dict[str, Any]] = {"grade": grade} if grade is not None else None
            try:
                br = col.query(
                    query_texts=[query],
                    n_results=k,
                    where=broad_where,
                )
            except Exception:
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
    return get_knowledge_base().retrieve_context(topic_id, k=k)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or query local Grade 6–9 science RAG index.")
    parser.add_argument("--rebuild", action="store_true", help="Delete existing Chroma data and rebuild.")
    parser.add_argument(
        "--topic",
        type=str,
        default=None,
        help="If set, run retrieve_context(topic) after build (e.g. G8_S3_PHO_PROCESS).",
    )
    args = parser.parse_args()
    kb = LocalScienceKnowledgeBase()
    kb.ensure_index(force_rebuild=args.rebuild)
    print(f"Index ready at {kb.persist_directory} ({len(kb.pdf_specs)} PDFs)")
    if args.topic:
        out = kb.retrieve_context(args.topic, k=4)
        print("--- sample facts_text (truncated) ---")
        print(out["facts_text"][:1500] + ("..." if len(out["facts_text"]) > 1500 else ""))


if __name__ == "__main__":
    main()
