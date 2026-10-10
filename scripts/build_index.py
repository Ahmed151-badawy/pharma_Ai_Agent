"""Build (or top up) the FAISS index. Run at image build time: it also pre-downloads the embedding model."""
from app.rag import get_kb

if __name__ == "__main__":
    kb = get_kb()
    kb.ensure_seed()
    print(f"✓ Knowledge base ready: {kb.chunk_count} chunks.")
