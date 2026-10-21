# Alexa-Inspired Smart Dashboard

A smart-assistant dashboard inspired by Amazon Alexa. It brings music controls, smart home automation, weather updates and a voice assistant together in one clean, responsive interface.

Built with **React.js, JavaScript, HTML, CSS and Vite**.

> 📸 **Screenshots:** add 2–3 images here (dashboard home, smart home panel, voice assistant), e.g.
> `![Dashboard](./docs/dashboard.png)`

---

## Features

| Feature | What it does |
|---|---|
| 🎵 **Music controls** | Play / pause, next / previous, volume and other music options from the dashboard |
| 🏠 **Smart home automation** | An interface to view and control smart home devices (lights, fans, etc.) |
| ⛅ **Weather updates** | A weather section that shows current conditions and key weather information |
| 🎙️ **Voice assistant** | Voice-assistant functionality so you can talk to the dashboard like a smart speaker |

---

## Tech Stack

- **React.js** – component-based UI
- **JavaScript (ES6+)** – application logic
- **HTML5 + CSS3** – structure and styling
- **Vite** – fast dev server and build tool

---

## Getting Started

### Prerequisites
- [Node.js](https://nodejs.org/) 20 or newer (LTS recommended)
- npm (comes with Node.js)

Check your versions:
```bash
node -v
npm -v
```

### Installation
```bash
# 1. Clone the repository
git clone <your-repo-url>
cd <your-repo-folder>/frontend      # use the actual name of your frontend folder

# 2. Install dependencies
npm install

# 3. Start the development server
npm run dev
```

Open the URL printed in the terminal. Vite's default is **http://localhost:5173**.

### Available scripts

| Command | Description |
|---|---|
| `npm run dev` | Start the development server with hot reload |
| `npm run build` | Create an optimized production build in `dist/` |
| `npm run preview` | Preview the production build locally |

---

## Connecting to the Backend (optional)

The dashboard can talk to the project's FastAPI backend (Amazon Bedrock + MCP tools) so the voice/chat assistant can manage tasks, reminders and inventory.

### 1. Start the backend first
Follow the backend README. In short, run the MCP server and FastAPI (`uvicorn app.main:app --port 8000`) from the `backend` folder. The backend runs at **http://127.0.0.1:8000** and works in demo mode without any AWS credentials.

### 2. Set the API address in the frontend
Create a file named `.env` in the frontend folder:
```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```
Restart `npm run dev` after changing `.env`. In code, read it with `import.meta.env.VITE_API_BASE_URL`. Only variables that start with `VITE_` are visible to the browser, so **never put passwords or API keys in this file**.

### 3. Call the chat endpoint
```js
const API = import.meta.env.VITE_API_BASE_URL;

export async function sendMessage(message) {
  const res = await fetch(`${API}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.message || "Something went wrong");
  return data; // { response: "...", events: [{ tool, status, message }] }
}
```

### Backend API summary

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check that the backend is running |
| POST | `/api/chat` | Send `{ "message": "..." }`, get `{ "response", "events" }` |
| GET | `/api/tasks` | List tasks |
| GET | `/api/reminders` | List reminders (stored only, no notifications are sent) |
| GET | `/api/inventory` | List inventory items |
| GET | `/api/tools` | List available assistant tools |

Interactive API docs: **http://127.0.0.1:8000/docs**

### Handling events
Each chat reply includes `events`, one per tool the assistant used. `status` is one of:
- `success` – the action worked
- `error` – the action failed (`message` explains why)
- `confirmation_required` – a risky action (like deleting a task) is **waiting for the user**. Show it as "waiting for confirmation" and let the user reply `confirm` or `cancel`.

In demo mode, assistant replies start with `[DEMO MODE ...]`.

---

## Project Structure

> Adjust this to match your actual folders.

```
frontend/
├── public/              # Static files
├── src/
│   ├── components/      # Reusable UI pieces (music, smart home, weather, voice)
│   ├── assets/          # Images and icons
│   ├── App.jsx          # Main app component
│   ├── main.jsx         # React entry point
│   └── index.css        # Global styles
├── index.html
├── package.json
└── vite.config.js
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `npm install` fails | Check `node -v` is 20 or newer, then delete `node_modules` and retry |
| Browser shows a **CORS error** | Add your frontend address (e.g. `http://localhost:5173`) to `CORS_ORIGINS` in the backend `.env`, then restart the backend |
| Chat shows "Failed to fetch" | The backend is not running, or `VITE_API_BASE_URL` is wrong |
| Backend replies **503** `tool_server_unavailable` | Start the MCP server (`python -m mcp_server.server`) in the backend folder |
| Voice assistant does not hear you | Allow microphone access in the browser, and use a browser that supports speech features (e.g. Chrome or Edge) |
| Changed `.env` but nothing changed | Stop and restart `npm run dev` |

---

## Future Improvements
- Connect every dashboard card (music, devices, weather) to live data
- Show assistant `events` as an activity feed
- Add confirm / cancel buttons for risky actions
- Dark / light theme toggle