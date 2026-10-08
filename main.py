from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from agent_core import get_pharma_agent

app = FastAPI(
    title="Pharma AI Agent Microservice", 
    version="1.0.0",
    description="Backend API running a LangGraph ReAct agent with SQL and FAISS RAG tools."
)

# Enable CORS for desktop/client connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the agent once at startup
pharma_agent = get_pharma_agent()

# Pydantic Schemas for Request & Response
class QueryRequest(BaseModel):
    query: str

class QueryResponse(BaseModel):
    query: str
    response: str

@app.get("/health")
def health_check():
    """Health check endpoint for Docker & AWS ECS load balancers."""
    return {"status": "healthy", "service": "pharma-agent-backend"}

@app.post("/api/v1/chat", response_model=QueryResponse)
async def process_pharmacist_query(request: QueryRequest):
    """Processes natural language queries via the ReAct agent."""
    try:
        inputs = {"messages": [("user", request.query)]}
        
        # Run agent stream and capture the final AI response
        final_answer = ""
        for chunk in pharma_agent.stream(inputs, stream_mode="values"):
            message = chunk["messages"][-1]
            if message.type == "ai" and message.content:
                final_answer = message.content

        if not final_answer:
            final_answer = "Agent completed execution but produced no final text response."

        return QueryResponse(query=request.query, response=final_answer)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent Processing Error: {str(e)}")