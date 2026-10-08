import os
import psycopg2
from langchain_core.tools import tool
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_groq import ChatGroq
from langgraph.prebuilt import create_react_agent

# The Groq API key is read from the GROQ_API_KEY environment variable.
# Never hard-code it here (it would be baked into the Docker image).

# ------------------------------------------------------------------
# Tool 1: PostgreSQL SQL Tool (Structured Data)
# ------------------------------------------------------------------
@tool
def check_inventory_sql(query: str) -> str:
    """Executes a SQL SELECT query against the pharma_inventory database.
    Use this to check medicine stock, batch numbers, and expiration dates.
    Input must be a valid SQL SELECT statement.
    """
    try:
        conn = psycopg2.connect(
            host="host.docker.internal",
            database="pharma_inventory",
            user="postgres",
            password="postgres"
        )
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return f"SQL Query Results: {rows}"
    except Exception as e:
        return f"Database Error: {str(e)}"

# ------------------------------------------------------------------
# Tool 2: FAISS Vector RAG Tool (Unstructured Data)
# ------------------------------------------------------------------
@tool
def query_fda_guidelines(query: str) -> str:
    """Searches official FDA guidelines and storage requirements for medicines.
    Use this for storage temp, contraindications, and drug interaction questions.
    Input should be a search query string.
    """
    try:
        embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        vector_store = FAISS.load_local(
            "faiss_index", 
            embeddings, 
            allow_dangerous_deserialization=True
        )
        docs = vector_store.similarity_search(query, k=2)
        results = "\n---\n".join([doc.page_content for doc in docs])
        return f"FDA Guidelines Found:\n{results}"
    except Exception as e:
        return f"Vector Search Error: {str(e)}"

# ------------------------------------------------------------------
# Agent Initialization
# ------------------------------------------------------------------
def get_pharma_agent():
    # Initialize Llama 3 via Groq
    llm = ChatGroq(model_name="openai/gpt-oss-120b", temperature=0)
    
    tools = [check_inventory_sql, query_fda_guidelines]
    
    # System prompt ensuring strict compliance behavior
    system_prompt = (
        "You are an expert Pharmaceutical Assistant AI. "
        "You have access to a PostgreSQL database for inventory and a FAISS RAG index for FDA guidelines. "
        "Always use the appropriate tools to answer user questions accurately. "
        "Do not invent stock counts or drug interactions without querying the tools."
    )
    
    agent = create_react_agent(llm, tools, prompt=system_prompt)
    return agent

if __name__ == "__main__":
    print("Testing Agent with a hybrid query...")
    agent = get_pharma_agent()
    
    # Test multi-tool intent: needs BOTH SQL stock query AND RAG guideline query
    test_query = "What is the stock level of Amoxicillin batch AMX-2026, and what are its storage requirements?"
    
    inputs = {"messages": [("user", test_query)]}
    for chunk in agent.stream(inputs, stream_mode="values"):
        message = chunk["messages"][-1]
        print(f"\n[{message.type.upper()}]: {message.content}")