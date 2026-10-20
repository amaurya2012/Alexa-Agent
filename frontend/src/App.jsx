import { useState } from "react";
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

  const currentTab = tabs.find((tab) => tab.id === activeTab);

  function sendCommand(e) {
    e.preventDefault();
    if (command.trim()) {
      alert("Alexa received: " + command);
      setCommand("");
    }
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
              className={`nav-item ${
                activeTab === tab.id ? "active" : ""
              }`}
              onClick={() => setActiveTab(tab.id)}
            >
              <span className="nav-icon">{tab.icon}</span>
              {tab.label}
              {activeTab === tab.id && (
                <span className="active-dot">●</span>
              )}
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
                  Music, weather and home controls — all
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
                <h2>Your everyday essentials</h2>
                <p>A little overview of your smart world.</p>
              </div>
              <span className="section-tag">QUICK ACCESS</span>
            </div>

            <section className="quick-grid">
              <button
                className="quick-card music-card"
                onClick={() => setActiveTab("music")}
              >
                <div className="quick-icon">♫</div>
                <span className="quick-kicker">YOUR SOUNDTRACK</span>
                <h3>Music &amp; vibes</h3>
                <p>Make the moment yours.</p>
                <span className="quick-arrow">↗</span>
                <div className="music-notes">♪ ♫</div>
              </button>

              <button
                className="quick-card weather-card"
                onClick={() => setActiveTab("weather")}
              >
                <div className="quick-icon">☀</div>
                <span className="quick-kicker">OUTSIDE TODAY</span>
                <h3>Weather</h3>
                <p>Plan your day with ease.</p>
                <span className="quick-arrow">↗</span>
                <div className="weather-cloud">☁</div>
              </button>

              <button
                className="quick-card home-card"
                onClick={() => setActiveTab("home")}
              >
                <div className="quick-icon">⌂</div>
                <span className="quick-kicker">YOUR SPACE</span>
                <h3>Smart home</h3>
                <p>Comfort at your fingertips.</p>
                <span className="quick-arrow">↗</span>
                <div className="home-decoration">⌂</div>
              </button>
            </section>

            <section className="bottom-grid">
              <div className="content-card now-playing">
                <div className="section-heading compact">
                  <div>
                    <h2>Music corner</h2>
                    <p>Set the mood for today.</p>
                  </div>
                  <span className="round-icon">♫</span>
                </div>
                <div className="song-row">
                  <div className="album-art">♫</div>
                  <div className="song-info">
                    <strong>Your happy playlist</strong>
                    <span>Ready when you are</span>
                  </div>
                  <button
                    className="play-button"
                    onClick={() => setPlaying(!playing)}
                  >
                    {playing ? "Ⅱ" : "▶"}
                  </button>
                </div>
                <div className="music-progress">
                  <span></span>
                </div>
                <div className="progress-labels">
                  <span>{playing ? "Playing demo" : "Ready to play"}</span>
                  <span>♡</span>
                </div>
              </div>

              <div className="content-card home-status">
                <div className="section-heading compact">
                  <div>
                    <h2>Home at a glance</h2>
                    <p>Your comfort, your control.</p>
                  </div>
                  <span className="round-icon green-icon">⌂</span>
                </div>
                <div className="device-row">
                  <div className="device-icon">☼</div>
                  <div className="device-info">
                    <strong>Living room lights</strong>
                    <span>{lights ? "Lights are on" : "Lights are off"}</span>
                  </div>
                  <button
                    className={`toggle ${lights ? "toggle-on" : ""}`}
                    onClick={() => setLights(!lights)}
                    aria-label="Toggle living room lights"
                  >
                    <span></span>
                  </button>
                </div>
                <div className="device-row">
                  <div className="device-icon temp-icon">♨</div>
                  <div className="device-info">
                    <strong>Room temperature</strong>
                    <span>Comfort setting</span>
                  </div>
                  <strong className="temperature">{temperature}°</strong>
                </div>
              </div>
            </section>
          </>
        )}

        {activeTab === "music" && (
          <section className="feature-layout">
            <div className="feature-card music-feature">
              <span className="hero-label">♫ &nbsp; MUSIC STUDIO</span>
              <div className="music-visual">
                <span>♫</span>
                <span>♪</span>
                <span>♬</span>
                <span>♪</span>
                <span>♫</span>
              </div>
              <h2>Find your rhythm.</h2>
              <p>Every moment deserves its own soundtrack.</p>
              <button
                className="primary-button"
                onClick={() => setPlaying(!playing)}
              >
                {playing ? "Ⅱ  Pause demo" : "▶  Play demo"}
              </button>
              <p className="demo-note">
                {playing
                  ? "Demo mode is active — no audio stream connected."
                  : "Connect a music service to play real songs."}
              </p>
            </div>
            <div className="content-card playlist-card">
              <h2>Made for your mood</h2>
              <p>Pick a vibe to brighten your day.</p>
              {[
                ["☀", "Morning sunshine", "Fresh & uplifting"],
                ["☁", "Slow afternoons", "Calm & cozy"],
                ["✦", "Focus mode", "Clear your mind"],
                ["♡", "Feel-good favourites", "Songs you love"],
              ].map((item) => (
                <button
                  className="playlist-row"
                  key={item[1]}
                  onClick={() => setPlaying(true)}
                >
                  <span className="playlist-icon">{item[0]}</span>
                  <span className="playlist-info">
                    <strong>{item[1]}</strong>
                    <small>{item[2]}</small>
                  </span>
                  <span>→</span>
                </button>
              ))}
            </div>
          </section>
        )}

        {activeTab === "weather" && (
          <>
            <section className="weather-hero">
              <div>
                <span className="hero-label">☀ &nbsp; WEATHER SNAPSHOT</span>
                <p className="weather-location">Your local weather</p>
                <h2>Make today a good day.</h2>
                <p>Connect a weather API for your live local forecast.</p>
                <div className="weather-placeholder">
                  <span>☀</span>
                  <div>
                    <strong>Weather preview</strong>
                    <small>Live temperature not connected</small>
                  </div>
                </div>
              </div>
              <div className="sun-art">
                <span>☀</span>
                <div className="cloud-art">☁</div>
              </div>
            </section>
            <section className="quick-grid weather-stats">
              {[
                ["☁", "Humidity", "Connect API"],
                ["↗", "Wind speed", "Connect API"],
                ["☀", "UV index", "Connect API"],
              ].map((item) => (
                <div className="content-card stat-card" key={item[1]}>
                  <span className="stat-icon">{item[0]}</span>
                  <p>{item[1]}</p>
                  <h3>{item[2]}</h3>
                </div>
              ))}
            </section>
          </>
        )}

        {activeTab === "home" && (
          <>
            <section className="home-banner">
              <span className="hero-label">⌂ &nbsp; YOUR CONNECTED SPACE</span>
              <h2>A home that feels like you.</h2>
              <p>Manage your comfort with simple controls.</p>
              <span className="big-home-art">⌂</span>
            </section>
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
                  aria-label="Room temperature"
                  type="range"
                  min="16"
                  max="30"
                  value={temperature}
                  onChange={(e) => setTemperature(Number(e.target.value))}
                />
                <p className="range-label">16°C <span>30°C</span></p>
              </div>
              <div className="content-card comfort-card">
                <div className="comfort-orb">✧</div>
                <h2>Comfort mode</h2>
                <p>Make your space feel just right.</p>
                <span className="connected-label">
                  <span className="green-dot"></span> Demo controls active
                </span>
              </div>
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
              <h2>{listening ? "I'm listening!" : "Hello, how can I help?"}</h2>
              <p>
                {listening
                  ? "This is a visual demo. Type your request below."
                  : "Your assistant is ready for your next request."}
              </p>
              <button
                className="primary-button"
                onClick={() => setListening(!listening)}
              >
                {listening ? "Stop listening" : "✧ Start assistant"}
              </button>
              <form className="command-form" onSubmit={sendCommand}>
                <input
                  value={command}
                  onChange={(e) => setCommand(e.target.value)}
                  placeholder="Try: Turn on the lights..."
                  aria-label="Enter an assistant command"
                />
                <button type="submit">Send →</button>
              </form>
              <small className="demo-note">
                Text commands show a demo response. Voice recognition is not connected.
              </small>
            </div>
          </section>
        )}

        <footer className="footer">
          <span>✧ Alexa Smart Dashboard</span>
          <span>Designed for a little more everyday magic.</span>
        </footer>
      </main>
    </div>
  );
}

export default App;