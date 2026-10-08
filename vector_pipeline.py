from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
import os

def create_vector_store():
    print("1. Loading unstructured document...")
    loader = TextLoader("fda_guidelines.txt")
    documents = loader.load()

    print("2. Chunking text into smaller segments...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=300, 
        chunk_overlap=50
    )
    docs = text_splitter.split_documents(documents)

    print(f"   Created {len(docs)} document chunks.")

    print("3. Initializing Embedding Model (SentenceTransformers)...")
    # Using a fast, lightweight open-source embedding model
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    print("4. Generating Vectors and Building FAISS Index...")
    vector_store = FAISS.from_documents(docs, embeddings)

    # Save the index locally so the agent can load it later without regenerating
    vector_store.save_local("faiss_index")
    print("✓ Vector store successfully saved to local 'faiss_index' folder!")

if __name__ == "__main__":
    create_vector_store()