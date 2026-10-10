import io

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from app.rag import IngestError, KnowledgeBase, build_chunks, extract_pages


def make_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    body = (
        "%PDF-1.4\n"
        "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        "/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        f"4 0 obj<</Length {len(stream)}>>stream\n{stream}\nendstream endobj\n"
        "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        "trailer<</Root 1 0 R/Size 6>>\nstartxref\n0\n%%EOF\n"
    )
    return body.encode()


@pytest.fixture
def kb(tmp_path):
    return KnowledgeBase(str(tmp_path / "idx"), DeterministicFakeEmbedding(size=64), retrieval_k=3)


def add_text(kb, doc_id, source, text):
    docs, ids = build_chunks(doc_id, source, [(None, text)])
    kb.add(docs, ids)


def test_chunks_keep_metadata():
    docs, ids = build_chunks("d1", "label.pdf", [(1, "alpha " * 400), (2, "beta " * 50)])
    assert len(docs) > 2 and len(docs) == len(ids)
    assert docs[0].metadata["source"] == "label.pdf" and docs[0].metadata["page"] == 1
    assert docs[-1].metadata["page"] == 2
    assert len(set(ids)) == len(ids)


def test_keyword_match_ranks_first_even_with_meaningless_embeddings(kb):
    add_text(kb, "a", "amox.txt", "Amoxicillin must be stored below 25 degrees and protected from moisture.")
    add_text(kb, "b", "ibu.txt", "Ibuprofen should not be combined with aspirin or taken on an empty stomach.")
    add_text(kb, "c", "met.txt", "Metformin is contraindicated in severe renal impairment.")
    hits = kb.search("Amoxicillin storage")
    assert hits[0].source == "amox.txt"
    assert hits[0].citation()["type"] == "document"


def test_delete_document_removes_its_chunks(kb):
    add_text(kb, "a", "amox.txt", "Amoxicillin storage information.")
    add_text(kb, "b", "ibu.txt", "Ibuprofen interaction information.")
    assert kb.delete_document("a") == 1
    assert all(h.doc_id != "a" for h in kb.search("Amoxicillin"))
    assert kb.chunk_count == 1


def test_index_is_persisted_to_disk(kb, tmp_path):
    add_text(kb, "a", "amox.txt", "Amoxicillin storage information.")
    reloaded = KnowledgeBase(str(tmp_path / "idx"), DeterministicFakeEmbedding(size=64), retrieval_k=3)
    assert reloaded.chunk_count == 1
    assert reloaded.search("Amoxicillin")[0].source == "amox.txt"


def test_empty_index_returns_no_hits(kb):
    assert kb.search("anything") == []


def test_extract_text_and_markdown():
    assert extract_pages("a.txt", b"hello") == [(None, "hello")]
    assert extract_pages("a.md", "# Titre é".encode()) == [(None, "# Titre é")]


def test_extract_pdf_pages_with_page_numbers():
    pages = extract_pages("label.pdf", make_pdf("Warfarin label text"))
    assert pages == [(1, "Warfarin label text")]


@pytest.mark.parametrize("name,data", [
    ("a.exe", b"x"), ("a.txt", b"   "), ("a.pdf", b"not a pdf"), ("a.pdf", b"%PDF-1.4 garbage"),
])
def test_bad_uploads_are_rejected(name, data):
    with pytest.raises(IngestError):
        extract_pages(name, data)


def test_blank_pdf_without_text_is_rejected():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(IngestError, match="extractable"):
        extract_pages("scan.pdf", buffer.getvalue())
