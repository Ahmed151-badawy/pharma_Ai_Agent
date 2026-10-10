"""Knowledge base: FAISS vector search + BM25 keyword search, fused with Reciprocal Rank Fusion (RRF).

Documents (PDF / TXT / MD) are split into chunks that keep metadata (source file, page, ids), so every
answer can cite exactly where it came from. The index is persisted to disk (FAISS_INDEX_DIR).
"""
import hashlib
import io
import logging
import re
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document as LCDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document as DocumentRow

logger = logging.getLogger(__name__)
RRF_K = 60  # standard RRF constant
SEED_DOC_ID = "seed"


class IngestError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    source: str
    page: int | None
    text: str
    score: float

    def citation(self) -> dict:
        return {
            "type": "document",
            "source": self.source,
            "page": self.page,
            "doc_id": self.doc_id,
            "snippet": self.text[:300],
            "score": round(self.score, 4),
        }


def build_embeddings():
    settings = get_settings()
    if settings.embeddings_backend == "fake":  # deterministic, offline: used by tests
        from langchain_core.embeddings import DeterministicFakeEmbedding

        return DeterministicFakeEmbedding(size=64)
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=settings.embedding_model)


# ----------------------------------------------------------------- parsing / chunking
def extract_pages(filename: str, data: bytes) -> list[tuple[int | None, str]]:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        if not data.startswith(b"%PDF"):
            raise IngestError("File is not a valid PDF.")
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise IngestError("Encrypted PDFs are not supported.")
            if len(reader.pages) > get_settings().max_pdf_pages:
                raise IngestError(f"PDF has too many pages (max {get_settings().max_pdf_pages}).", 413)
            pages = [(i + 1, (p.extract_text() or "").strip()) for i, p in enumerate(reader.pages)]
        except IngestError:
            raise
        except Exception as exc:  # corrupt / unsupported PDF structure
            logger.warning("PDF parsing failed: %s", exc)
            raise IngestError("Could not read this PDF.") from exc
    elif ext in {".txt", ".md"}:
        pages = [(None, data.decode("utf-8", errors="replace").strip())]
    else:
        raise IngestError("Unsupported file type. Upload .pdf, .txt or .md files.", 415)

    pages = [(n, t) for n, t in pages if t]
    if not pages:
        raise IngestError("No extractable text found (scanned PDFs need OCR first).")
    return pages


def build_chunks(doc_id: str, source: str, pages: list[tuple[int | None, str]]) -> tuple[list[LCDocument], list[str]]:
    settings = get_settings()
    splitter = RecursiveCharacterTextSplitter(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    docs: list[LCDocument] = []
    ids: list[str] = []
    for page, text in pages:
        for piece in splitter.split_text(text):
            chunk_id = f"{doc_id}:{len(docs)}"
            docs.append(LCDocument(page_content=piece,
                                   metadata={"doc_id": doc_id, "chunk_id": chunk_id, "source": source, "page": page}))
            ids.append(chunk_id)
    return docs, ids


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


# ----------------------------------------------------------------- knowledge base
class KnowledgeBase:
    def __init__(self, index_dir: str, embeddings, retrieval_k: int) -> None:
        self._dir = Path(index_dir)
        self._embeddings = embeddings
        self._k = retrieval_k
        self._lock = threading.RLock()
        self._store: FAISS | None = None
        self._bm25: BM25Okapi | None = None
        self._bm25_docs: list[LCDocument] = []
        if (self._dir / "index.faiss").exists():
            self._store = FAISS.load_local(str(self._dir), embeddings, allow_dangerous_deserialization=True)

    # -- helpers
    def _all_docs(self) -> list[LCDocument]:
        return list(self._store.docstore._dict.values()) if self._store else []

    @property
    def chunk_count(self) -> int:
        with self._lock:
            return len(self._all_docs())

    def _persist(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._store.save_local(str(self._dir))
        self._bm25 = None  # rebuilt lazily on next search

    # -- writes
    def add(self, docs: list[LCDocument], ids: list[str]) -> None:
        with self._lock:
            if self._store is None:
                self._store = FAISS.from_documents(docs, self._embeddings, ids=ids)
            else:
                self._store.add_documents(docs, ids=ids)
            self._persist()

    def delete_document(self, doc_id: str) -> int:
        with self._lock:
            if self._store is None:
                return 0
            ids = [i for i, d in self._store.docstore._dict.items() if d.metadata.get("doc_id") == doc_id]
            if ids:
                self._store.delete(ids)
                self._persist()
            return len(ids)

    def ensure_seed(self) -> None:
        """Index the bundled sample guidelines on first start (when the index is empty)."""
        if self.chunk_count > 0:
            return
        path = Path(get_settings().seed_document_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        if not path.exists():
            logger.warning("Seed document %s not found; knowledge base is empty.", path)
            return
        docs, ids = build_chunks(SEED_DOC_ID, path.name, extract_pages(path.name, path.read_bytes()))
        self.add(docs, ids)
        logger.info("Indexed seed document %s (%d chunks).", path.name, len(docs))

    # -- reads
    def _bm25_search(self, query: str, n: int) -> list[LCDocument]:
        if self._bm25 is None:
            self._bm25_docs = self._all_docs()
            self._bm25 = BM25Okapi([_tokenize(d.page_content) or ["_"] for d in self._bm25_docs]) if self._bm25_docs else None
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(zip(scores, self._bm25_docs, strict=True), key=lambda pair: -pair[0])
        return [doc for score, doc in ranked[:n] if score > 0]

    def search(self, query: str, k: int | None = None) -> list[Hit]:
        k = k or self._k
        with self._lock:
            total = len(self._all_docs())
            if total == 0:
                return []
            fetch = min(max(k * 3, 10), total)
            vector_hits = [doc for doc, _ in self._store.similarity_search_with_score(query, k=fetch)]
            keyword_hits = self._bm25_search(query, fetch)

        scores: dict[str, float] = defaultdict(float)
        by_id: dict[str, LCDocument] = {}
        for hits in (vector_hits, keyword_hits):
            for rank, doc in enumerate(hits):
                cid = doc.metadata["chunk_id"]
                by_id[cid] = doc
                scores[cid] += 1.0 / (RRF_K + rank + 1)
        top = sorted(scores, key=scores.get, reverse=True)[:k]
        return [
            Hit(cid, by_id[cid].metadata["doc_id"], by_id[cid].metadata["source"], by_id[cid].metadata.get("page"),
                by_id[cid].page_content, scores[cid])
            for cid in top
        ]


@lru_cache
def get_kb() -> KnowledgeBase:
    settings = get_settings()
    return KnowledgeBase(settings.faiss_index_dir, build_embeddings(), settings.retrieval_k)


# ----------------------------------------------------------------- upload workflow
def ingest_document(session: Session, kb: KnowledgeBase, filename: str, data: bytes, uploaded_by: str) -> DocumentRow:
    safe_name = Path(filename).name[:255] or "document"
    sha = hashlib.sha256(data).hexdigest()
    if session.scalar(select(DocumentRow).where(DocumentRow.sha256 == sha)):
        raise IngestError("This document was already uploaded.", 409)

    pages = extract_pages(safe_name, data)
    doc_id = str(uuid.uuid4())
    docs, ids = build_chunks(doc_id, safe_name, pages)
    kb.add(docs, ids)
    try:
        row = DocumentRow(id=doc_id, filename=safe_name, sha256=sha, pages=len(pages), chunks=len(docs),
                          uploaded_by=uploaded_by)
        session.add(row)
        session.commit()
    except Exception:
        session.rollback()
        kb.delete_document(doc_id)  # do not leave orphan chunks in the index
        raise
    return row
