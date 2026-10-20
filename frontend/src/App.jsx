import { useState, useEffect } from "react";
import "./App.css";

const tabs = [
  { id: "overview", label: "Overview", icon: "⌂" },
  { id: "music", label: "Music", icon: "♫" },
  { id: "weather", label: "Weather", icon: "☀" },
  { id: "home", label: "Smart Home", icon: "⌂" },
  { id: "voice", label: "Voice Assistant", icon: "✧" },
];

function App() {
  const [activeTab, setActiveTab] = useState("overview");
  const [listening, setListening] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [lights, setLights] = useState(true);
  const [temperature, setTemperature] = useState(24);
  const [command, setCommand] = useState("");
  const [loading, setLoading] = useState(false);
  const [chatLog, setChatLog] = useState([
    { sender: "assistant", text: "Hello! I am your Alexa Assistant. How can I help you today?" }
  ]);
  const [tasks, setTasks] = useState([]);
  const [inventory, setInventory] = useState([]);

  const currentTab = tabs.find((tab) => tab.id === activeTab);

  // Sync tasks and inventory from backend
  const fetchTasksAndInventory = async () => {
    try {
      const [tRes, iRes] = await Promise.all([
        fetch("http://localhost:8000/api/tasks"),
        fetch("http://localhost:8000/api/inventory")
      ]);
      if (tRes.ok) {
        const tData = await tRes.json();
        setTasks(tData.tasks || []);
      }
      if (iRes.ok) {
        const iData = await iRes.json();
        setInventory(iData.items || []);
      }
    } catch {
      // Backend not reached or offline
    }
  };

  useEffect(() => {
    fetchTasksAndInventory();
  }, [activeTab]);

  // Voice input via browser Web Speech API
  const toggleSpeechRecognition = () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Voice input is not supported in this browser. Please use Google Chrome or Edge.");
      return;
    }

    if (!listening) {
      const recognition = new SpeechRecognition();
      recognition.lang = "en-US";
      recognition.interimResults = false;

      recognition.onstart = () => setListening(true);
      recognition.onend = () => setListening(false);
      recognition.onerror = () => setListening(false);

      recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        setCommand(transcript);
        processAgentRequest(transcript);
      };

      recognition.start();
    } else {
      setListening(false);
    }
  };

  // Dispatch message to FastAPI backend
  async function processAgentRequest(messageText) {
    if (!messageText.trim() || loading) return;

    const userMessage = messageText.trim();
    setCommand("");
    setChatLog((prev) => [...prev, { sender: "user", text: userMessage }]);
    setLoading(true);

    try {
      const response = await fetch("http://localhost:8000/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMessage }),
      });

      const data = await response.json();

      if (data.response) {
        const requiresConfirm = (data.events || []).some(
          (e) => e.status === "confirmation_required"
        );
        setChatLog((prev) => [
          ...prev,
          {
            sender: "assistant",
            text: data.response,
            needsConfirm: requiresConfirm,
          },
        ]);
        fetchTasksAndInventory();
      } else if (data.message) {
        setChatLog((prev) => [
          ...prev,
          { sender: "assistant", text: `Error: ${data.message}` },
        ]);
      }
    } catch {
      setChatLog((prev) => [
        ...prev,
        {
          sender: "assistant",
          text: "Could not reach the backend server. Make sure port 8000 and MCP server are running.",
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function sendCommand(e) {
    e.preventDefault();
    processAgentRequest(command);
  }

  return (
    <div className={`app ${activeTab}-theme`}>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">✧</div>
          <div>
            <h2>alexa</h2>
            <span>SMART ASSISTANT</span>
          </div>
        </div>

        <p className="nav-heading">MENU</p>

        <nav className="side-nav">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={`nav-item ${activeTab === tab.id ? "active" : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <span className="nav-icon">{tab.icon}</span>
              {tab.label}
              {activeTab === tab.id && <span className="active-dot">●</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="mini-orb">✧</div>
          <h3>Hey there!</h3>
          <p>Your personal assistant is ready to help.</p>
          <button
            className="small-action"
            onClick={() => setActiveTab("voice")}
          >
            Talk to Alexa ↗
          </button>
        </div>

        <div className="profile">
          <div className="avatar">A</div>
          <div>
            <strong>My Assistant</strong>
            <span>Home account</span>
          </div>
          <span className="profile-menu">•••</span>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumb">
            <span>Workspace</span>
            <span>/</span>
            <strong>{currentTab.label}</strong>
          </div>
          <div className="top-actions">
            <span className="online-status">
              <span className="green-dot"></span>
              System online
            </span>
            <button
              className="icon-button"
              title="Voice Assistant"
              onClick={() => setActiveTab("voice")}
            >
              ♫
            </button>
            <div className="avatar top-avatar">A</div>
          </div>
        </header>

        <section className="welcome">
          <div>
            <p className="eyebrow">YOUR PERSONAL AI COMPANION</p>
            <h1>
              {activeTab === "overview" && (
                <>Your world, <span>simplified.</span></>
              )}
              {activeTab === "music" && (
                <>Feel the <span>music.</span></>
              )}
              {activeTab === "weather" && (
                <>A brighter <span>forecast.</span></>
              )}
              {activeTab === "home" && (
                <>Your home, <span>your way.</span></>
              )}
              {activeTab === "voice" && (
                <>Just say <span>hello.</span></>
              )}
            </h1>
            <p className="welcome-text">
              {activeTab === "overview" &&
                "Everything you need, thoughtfully brought together."}
              {activeTab === "music" &&
                "Your favourite sounds, all in one happy place."}
              {activeTab === "weather" &&
                "A little sunshine helps you plan your day."}
              {activeTab === "home" &&
                "A smarter, cozier home starts right here."}
              {activeTab === "voice" &&
                "Ask, explore, and let your assistant help."}
            </p>
          </div>
          <div className="date-pill">✦ &nbsp; Your smart space</div>
        </section>

        {activeTab === "overview" && (
          <>
            <section className="hero-card">
              <div className="hero-copy">
                <span className="hero-label">✧ &nbsp; MEET YOUR ASSISTANT</span>
                <h2>Life feels lighter<br />with Alexa.</h2>
                <p>
                  Tasks, reminders, inventory and home controls — all
                  working together to make everyday easier.
                </p>
                <button
                  className="primary-button"
                  onClick={() => setActiveTab("voice")}
                >
                  <span>✧</span> Talk to Alexa <span>→</span>
                </button>
              </div>
              <div className="hero-art">
                <div className="orbit orbit-one"></div>
                <div className="orbit orbit-two"></div>
                <div className="hero-orb">
                  <div className="orb-shine"></div>
                  <span>✧</span>
                </div>
                <span className="floating-symbol symbol-one">♫</span>
                <span className="floating-symbol symbol-two">☀</span>
                <span className="floating-symbol symbol-three">⌂</span>
              </div>
              <div className="hero-decoration">✦</div>
            </section>

            <div className="section-heading">
              <div>
                <h2>Your live items &amp; tasks</h2>
                <p>Real-time data from your local agent database.</p>
              </div>
              <span className="section-tag">LIVE DB</span>
            </div>

            <section className="quick-grid">
              <div className="quick-card home-card">
                <div className="quick-icon">✓</div>
                <span className="quick-kicker">DATABASE TASKS</span>
                <h3>{tasks.length} Active Tasks</h3>
                <p>
                  {tasks.length > 0
                    ? tasks.slice(0, 2).map((t) => t.title).join(", ")
                    : "No active tasks recorded yet."}
                </p>
                <span className="quick-arrow" onClick={() => setActiveTab("voice")}>↗</span>
              </div>

              <div className="quick-card weather-card">
                <div className="quick-icon">📦</div>
                <span className="quick-kicker">INVENTORY ITEMS</span>
                <h3>{inventory.length} Tracked Items</h3>
                <p>
                  {inventory.length > 0
                    ? inventory.slice(0, 2).map((i) => `${i.item_name} (${i.quantity} ${i.unit})`).join(", ")
                    : "No inventory items added yet."}
                </p>
                <span className="quick-arrow" onClick={() => setActiveTab("voice")}>↗</span>
              </div>

              <button
                className="quick-card music-card"
                onClick={() => setActiveTab("voice")}
              >
                <div className="quick-icon">✧</div>
                <span className="quick-kicker">AUTONOMOUS AGENT</span>
                <h3>Agent Console</h3>
                <p>Issue voice &amp; text commands.</p>
                <span className="quick-arrow">↗</span>
              </button>
            </section>
          </>
        )}

        {activeTab === "voice" && (
          <section className="voice-layout">
            <div className="voice-card">
              <span className="hero-label">✧ &nbsp; VOICE ASSISTANT</span>
              <div className={`voice-orb ${listening ? "listening" : ""}`}>
                <div className="voice-orb-inner">✧</div>
              </div>
              <h2>{listening ? "I'm listening..." : "Hello, how can I help?"}</h2>
              <p>
                {listening
                  ? "Speak your request into the microphone..."
                  : "Your assistant is connected to the backend agent."}
              </p>
              <button
                className="primary-button"
                onClick={toggleSpeechRecognition}
              >
                {listening ? "Stop listening" : "✧ Speak with mic"}
              </button>

              {/* Live Chat History Window */}
              <div
                style={{
                  width: "100%",
                  maxHeight: "220px",
                  overflowY: "auto",
                  margin: "18px 0",
                  padding: "12px",
                  background: "rgba(255, 255, 255, 0.65)",
                  borderRadius: "12px",
                  border: "1px solid rgba(0, 0, 0, 0.08)",
                  display: "flex",
                  flexDirection: "column",
                  gap: "10px",
                }}
              >
                {chatLog.map((msg, index) => (
                  <div
                    key={index}
                    style={{
                      alignSelf: msg.sender === "user" ? "flex-end" : "flex-start",
                      background: msg.sender === "user" ? "#0284c7" : "#ffffff",
                      color: msg.sender === "user" ? "#ffffff" : "#1e293b",
                      padding: "8px 14px",
                      borderRadius: "10px",
                      maxWidth: "85%",
                      fontSize: "13px",
                      boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
                      whiteSpace: "pre-line",
                      textAlign: "left",
                    }}
                  >
                    <strong>{msg.sender === "user" ? "You: " : "Alexa: "}</strong>
                    {msg.text}

                    {/* Safeguard Confirmation Buttons */}
                    {msg.needsConfirm && (
                      <div style={{ marginTop: "8px", display: "flex", gap: "8px" }}>
                        <button
                          type="button"
                          style={{
                            background: "#0284c7",
                            color: "#fff",
                            border: "none",
                            borderRadius: "6px",
                            padding: "4px 10px",
                            fontSize: "12px",
                            cursor: "pointer",
                          }}
                          onClick={() => processAgentRequest("confirm")}
                        >
                          Confirm
                        </button>
                        <button
                          type="button"
                          style={{
                            background: "#e2e8f0",
                            color: "#0f172a",
                            border: "none",
                            borderRadius: "6px",
                            padding: "4px 10px",
                            fontSize: "12px",
                            cursor: "pointer",
                          }}
                          onClick={() => processAgentRequest("cancel")}
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </div>
                ))}
                {loading && (
                  <div style={{ fontSize: "12px", color: "#64748b", fontStyle: "italic" }}>
                    Agent is processing...
                  </div>
                )}
              </div>

              <form className="command-form" onSubmit={sendCommand}>
                <input
                  value={command}
                  onChange={(e) => setCommand(e.target.value)}
                  placeholder="e.g. Add a task to submit the project..."
                  aria-label="Enter an assistant command"
                />
                <button type="submit" disabled={loading}>
                  {loading ? "..." : "Send →"}
                </button>
              </form>
            </div>
          </section>
        )}

        {activeTab === "home" && (
          <section className="bottom-grid">
            <div className="content-card device-panel">
              <div className="device-row">
                <div className="device-icon">☼</div>
                <div className="device-info">
                  <strong>Living room lights</strong>
                  <span>{lights ? "Currently on" : "Currently off"}</span>
                </div>
                <button
                  className={`toggle ${lights ? "toggle-on" : ""}`}
                  onClick={() => setLights(!lights)}
                >
                  <span></span>
                </button>
              </div>
              <div className="device-row">
                <div className="device-icon temp-icon">♨</div>
                <div className="device-info">
                  <strong>Thermostat</strong>
                  <span>Adjust room temperature</span>
                </div>
                <strong className="temperature">{temperature}°C</strong>
              </div>
              <input
                type="range"
                min="16"
                max="30"
                value={temperature}
                onChange={(e) => setTemperature(Number(e.target.value))}
              />
            </div>
          </section>
        )}

        <footer className="footer">
          <span>✧ Alexa Smart Dashboard</span>
          <span>Connected to live Bedrock MCP Backend</span>
        </footer>
      </main>
    </div>
  );
}

export default App;