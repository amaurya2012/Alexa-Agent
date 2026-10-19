# Next-Gen Alexa+ Agent — Backend

FastAPI backend that receives chat messages from the React frontend, lets an Amazon Bedrock model
(Converse API) decide which tools to call, runs those tools through a **real MCP server**
(official Python SDK, Streamable HTTP) backed by SQLite, and returns the final answer plus concise
operational events. Includes a clearly-labelled **demo mode** that needs no AWS credentials.

## Architecture

```
React frontend ──HTTP/JSON──▶ FastAPI  (app/, port 8000)
                              │  /api/chat → Agent loop ──▶ Bedrock Converse   (or MockBedrockClient in demo mode)
                              │                 │  toolUse / toolResult
                              │                 ▼
                              │            MCP client ──Streamable HTTP /mcp (+ bearer token)──▶ MCP server (mcp_server/, port 8765)
                              │                                                                  8 tools, validate, confirm, SQLite writes
                              └─ GET /api/tasks|reminders|inventory  ──read-only──▶ SQLite file (WAL, shared by both processes)
```

Two processes: the **MCP server** (tools + writes) and the **FastAPI app** (API + agent). The model never
touches SQLite or the network; it can only request the 8 MCP tools, and every request is validated again
by the tool itself.

## API contract (kept compatible with the frontend)

Base URL `http://127.0.0.1:8000` · Swagger UI `/docs` · OpenAPI `/openapi.json`

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | `{"status":"ok"\|"degraded","mode":"mock"\|"bedrock","database":"ok"\|"error","mcp_server":"ok"\|"unreachable","version":"1.0.0"}` (always HTTP 200) |
| POST | `/api/chat` | request `{"message":"..."}` → `{"response":"...","events":[{"tool":"add_task","status":"success","message":"Task created"}]}` |
| GET | `/api/tasks` | `{"tasks":[{id,title,notes,priority,due_date,status,created_at,completed_at}],"count":n}` |
| GET | `/api/reminders` | `{"reminders":[{id,text,remind_at,status,created_at}],"count":n,"notice":"Reminders are stored only..."}` |
| GET | `/api/inventory` | `{"items":[{id,item_name,quantity,unit,low_stock_threshold,low_stock,updated_at}],"count":n}` |
| GET | `/api/tools` | `{"tools":[{name,description,input_schema,read_only,requires_confirmation}],"count":n}` |

`event.status` is one of `success`, `error`, `confirmation_required`.
Messages: 1–2000 characters (`MAX_MESSAGE_CHARS`); unknown extra request fields are ignored.
Timestamps are UTC ISO 8601. There is **no endpoint that executes a tool directly**.

Errors always look like `{"error":"<code>","message":"...","details":[{field,message}]?,"request_id":"..."}`:
422 `validation_error`, 401 `unauthorized`, 502/503/504 model errors (`model_access_denied`, `model_throttled`,
`aws_credentials_missing`, `model_timeout`, …), 503 `tool_server_unavailable`, 504 `agent_timeout`,
500 `internal_error` (never contains stack traces). Every response carries `X-Request-ID`.

### Additions beyond the original contract (all additive, none change existing fields)
- `event.status = "confirmation_required"` (see below). Frontends that only know `success`/`error` should treat it as "pending".
- Envelope objects for the list endpoints (`{"tasks":[...],"count":n}` etc.), the `/health` fields, and the error body shape above.
- Optional `X-API-Key` header, enforced only if `API_KEY` is set. `/health` never needs it.
Tell the frontend developer before changing or removing anything here.

### Confirmation for destructive / consequential actions
`delete_task` and `update_inventory` with `remove`/`set` are **not executed** on first request. The chat reply
asks the user to answer **"confirm"** (or "yes", "go ahead", …) or **"cancel"**; the event shows
`confirmation_required`. A bare confirmation message executes the pending action directly (the model is not
involved); any other message cancels pending actions. Pending actions expire after `CONFIRMATION_TTL_SECONDS`.
The `confirm` argument is hidden from the model's tool schema and stripped from anything the model sends, and the
MCP tool independently refuses to act without it.
*Frontend tip: show a pending event as "waiting for confirmation" and let the user simply type or tap "confirm" / "cancel".*

### Reminders do not notify
Reminders are **stored only**. Nothing sends a push, SMS, email or voice notification unless a notification
provider is integrated later. Tool results, `/api/reminders` (`notice`) and the model's system prompt all say so.

## Windows PowerShell — install and run

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env           # demo mode is on by default (MOCK_MODE=true)
```

Terminal 1 — MCP tool server (keep running):
```powershell
cd backend; .\.venv\Scripts\Activate.ps1
python -m mcp_server.server           # http://127.0.0.1:8765/mcp
```
Terminal 2 — FastAPI backend:
```powershell
cd backend; .\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --reload-dir app --port 8000
```
Quick checks (Terminal 3):
```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/api/tools
$body = @{ message = "add a task to buy milk; remind me to call mom in 2 hours" } | ConvertTo-Json
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/chat -ContentType "application/json" -Body $body
Invoke-RestMethod http://127.0.0.1:8000/api/tasks
Start-Process http://127.0.0.1:8000/docs
```
Run the tests (no AWS, no cost — AWS sessions are blocked in the test suite):
```powershell
pytest -q
```

### Demo mode phrases (MOCK_MODE=true)
`add a task to buy milk` · `list my tasks` · `complete task 1` · `delete task 1` · `remind me to call mom in 2 hours` ·
`remind me to submit report tomorrow at 9am` · `show reminders` · `do we have eggs` · `show inventory` ·
`add 6 eggs to inventory` · `remove 2 milk from inventory` · `set rice stock to 10`. Join several with `;`.
Demo replies start with `[DEMO MODE - mock model, no AWS call]`. Only the language model is simulated:
the MCP server and SQLite are real, so demo data persists.

### Real Amazon Bedrock mode
1. Enable model access in the Bedrock console and get the exact model / inference-profile ID (IDs change; list them with
   `aws bedrock list-inference-profiles --region <region>`).
2. Configure credentials via the normal AWS chain, e.g. `aws sso login --profile my-profile` (never put keys in `.env`).
   The identity needs `bedrock:InvokeModel` permission for that model/profile (the Converse API uses it).
3. In `.env`: `MOCK_MODE=false`, `BEDROCK_MODEL_ID=<id>`, `AWS_REGION=<region>`, `AWS_PROFILE=my-profile` (optional). Restart FastAPI.
4. `GET /health` should report `"mode":"bedrock"`. Real calls are billed by AWS.

## Connecting the frontend
- API base URL: `http://127.0.0.1:8000`. Add the dev-server origin to `CORS_ORIGINS` (defaults: `http://localhost:5173`, `http://localhost:3000`; no cookies/credentials).
- Minimal call:
```js
const res = await fetch("http://127.0.0.1:8000/api/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: "add a task to buy milk" }),
});
const { response, events } = await res.json();   // on errors: res.ok === false and body.error / body.message
```
- Open `http://127.0.0.1:8000/docs`, expand **POST /api/chat → Try it out** to test without the UI.
- After a chat turn, refresh `/api/tasks`, `/api/reminders`, `/api/inventory` to update lists.

## Layout
```
backend/
  app/            main.py config.py agent.py bedrock_client.py mcp_client.py database.py schemas.py
                  logging_config.py errors.py deps.py  routes/{chat,health,tools}.py
  mcp_server/     server.py  tools/{__init__,tasks,reminders,inventory}.py
  tests/          conftest.py test_database.py test_mcp_tools.py test_agent.py test_api_routes.py
  requirements.txt  .env.example  pytest.ini  README.md
```
(`errors.py`, `deps.py`, `tools/__init__.py`, `pytest.ini` and the `__init__.py` files are small additions to the required structure.
`routes/tools.py` also serves the read-only `/api/tasks|reminders|inventory` views.)

## Security summary
No code/shell/SQL/URL tools exist; the model can only call 8 allow-listed MCP tools. Inputs are validated twice (MCP layer + Pydantic in each tool; strict
ints/bools, length limits, control-character rejection, parameterised SQL only). MCP server binds to loopback, supports a bearer token
(`MCP_AUTH_TOKEN`, mandatory for non-loopback hosts), and must not be exposed publicly. Errors are mapped to safe messages; logs contain tool names,
statuses and timings (not message text) and redact key/token patterns. CORS is an allow-list. Optional `API_KEY` guards `/api/*`.

## Known limitations
- Single-user demo: pending confirmations are global (not per session) and there is no conversation history — each chat message is independent.
  Add authentication + a `session_id` before multi-user use.
- No rate limiting; `API_KEY` is a shared secret, not user auth.
- The demo planner is rule-based and understands only the phrases above.
- Pinned to `mcp==2.3.0` (new `MCPServer`/`Client` API). Code written for the 1.x `FastMCP` API will not drop in.
- Verified with Python 3.11.17 and 3.12.3 on Linux with the pinned requirements; real Bedrock calls were not made (no AWS access in the build environment).
