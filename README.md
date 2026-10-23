# Alexa+ Agent: Autonomous Next-Gen AI Assistant

An agentic personal assistant built for the **Amazon Developer Hackathon** that elevates conversational voice and text interactions into reliable, structured real-world household actions. The architecture decouples LLM reasoning from actual tool and database execution using a **FastAPI** gateway, an isolated **Model Context Protocol (MCP)** tool server, a deterministic **Human-in-the-Loop** confirmation safety guardrail, and an interactive **React** dashboard.

---

## 🏛 Architecture Overview

```text
       ┌────────────────────────┐         ┌────────────────────────┐
       │   Alexa Custom Skill   │         │   React Web Frontend   │
       │     (ASK SDK/Voice)    │         │ (Web Speech API / Vite)│
       └───────────┬────────────┘         └───────────┬────────────┘
                   │                                  │
                   ▼                                  ▼
        POST /api/alexa                        POST /api/chat
       ┌───────────────────────────────────────────────────────────┐
       │                 FastAPI Gateway (Port 8000)               │
       │    - Agent Orchestration Loop                             │
       │    - Amazon Bedrock Converse API / Deterministic Mock     │
       │    - Human-in-the-Loop Confirmation Guardrail Engine      │
       └─────────────────────────────┬─────────────────────────────┘
                                     │ Streamable HTTP
                                     ▼
       ┌───────────────────────────────────────────────────────────┐
       │                MCP Tool Server (Port 8765)                │
       │    - Sandboxed Tool Declarations & Execution              │
       │    - Isolated Mutation Layer                              │
       └─────────────────────────────┬─────────────────────────────┘
                                     │ WAL Mode
                                     ▼
       ┌───────────────────────────────────────────────────────────┐
       │                     SQLite3 Database                      │
       │    - Tasks, Inventory, Reminders, Pending Action State    │
       └───────────────────────────────────────────────────────────┘


📁 Project Structure

       Alexa-Agent/
├── backend/
│   ├── app/
│   │   ├── agent.py               # Conversational agent loop & confirmation tracking
│   │   ├── alexa_handler.py       # ASK SDK intent handlers & response formatting
│   │   ├── bedrock_client.py      # Bedrock Converse client & MockBedrockClient planner
│   │   ├── config.py              # Application settings & environment parsing
│   │   ├── database.py            # SQLite schema initialization & connection helpers
│   │   ├── main.py                # FastAPI endpoints (/api/chat, /api/alexa, /health)
│   │   ├── mcp_client.py          # HTTP transport client communicating with MCP server
│   │   └── routes/                # Sub-routers for chat, health checks, and task reads
│   ├── mcp_server/
│   │   ├── server.py              # FastMCP server exposing tools over port 8765
│   │   └── tools/                 # Tool logic (tasks, inventory, reminders, weather)
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.jsx                # Main dashboard UI, voice input & chat loop
│   │   ├── App.css                # Component styling & layouts
│   │   └── main.jsx
│   ├── index.html
│   └── package.json
└── README.md


🚀 Setup & Installation

1. Backend Configuration
cd backend
python -m venv .venv

# On Windows:
.venv\Scripts\activate

pip install -r requirements.txt


Code snippet
APP_ENV=development
LOG_LEVEL=INFO
MOCK_MODE=true
MCP_SERVER_URL=http://localhost:8765
SQLITE_DB_PATH=data/alexa_agent.db

# Optional for live AWS Bedrock mode:
# AWS_REGION=us-east-1
# BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0


2. Frontend Configuration
cd ../frontend
npm install


🖥 Running the Application Locally

Terminal 1: MCP Tool Server
cd backend
.venv\Scripts\activate
python -m mcp_server.server

Terminal 2: FastAPI Backend Gateway
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000

Terminal 3: React Vite Frontend
cd frontend
npm run dev