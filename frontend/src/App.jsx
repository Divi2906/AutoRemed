
import { useState } from "react";
import "./App.css";

const initialIncidents = [
  { id: "INC-101", name: "High CPU usage", severity: "High", time: "10:24 AM", status: "Open" },
  { id: "INC-102", name: "Service unavailable", severity: "Medium", time: "09:50 AM", status: "In Progress" },
  { id: "INC-103", name: "Disk usage critical", severity: "Medium", time: "09:32 AM", status: "Open" },
  { id: "INC-104", name: "Memory usage high", severity: "Low", time: "08:47 AM", status: "Resolved" },
];

const navigation = [
  { name: "Overview", icon: "⌂" },
  { name: "Incidents", icon: "⚠" },
  { name: "Remediation", icon: "⚙" },
  { name: "Activity Logs", icon: "▤" },
  { name: "Settings", icon: "☷" },
];

function MetricCard({ icon, title, value, change, color, points }) {
  return (
    <article className="metric-card">
      <div className={`metric-icon ${color}`}>{icon}</div>
      <div className="metric-content">
        <p>{title}</p>
        <h2>{value}</h2>
        <span className="metric-change">{change}</span>
      </div>
      <svg className="sparkline" viewBox="0 0 240 40" preserveAspectRatio="none" aria-label={`${title} trend`}>
        <polyline points={points} />
      </svg>
    </article>
  );
}

function App() {
  const [activePage, setActivePage] = useState("Overview");
  const [incidents, setIncidents] = useState(initialIncidents);
  const [notice, setNotice] = useState("");

  const pending = incidents.filter(
    (incident) => incident.status === "Open"
  ).length;

  function updateIncident(id, decision) {
    setIncidents((current) =>
      current.map((incident) =>
        incident.id === id
          ? {
              ...incident,
              status: decision === "Approve" ? "Approved (simulated)" : "Rejected",
            }
          : incident
      )
    );

    setNotice(
      `${id}: ${decision.toLowerCase()} recorded in simulation. No real server was changed.`
    );
  }

  const cpuPoints = "0,29 18,25 35,28 53,18 70,21 88,12 106,18 123,9 141,22 158,17 176,25 194,16 212,20 240,12";
  const memoryPoints = "0,30 18,20 35,23 53,12 70,16 88,8 106,15 123,11 141,18 158,7 176,14 194,10 212,16 240,5";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">A</div>
          <div>
            <h1>AutoRemed</h1>
            <p>AI-Powered DevOps Remediation</p>
          </div>
        </div>

        <nav className="navigation">
          {navigation.map((item) => (
            <button
              key={item.name}
              className={`nav-item ${activePage === item.name ? "active" : ""}`}
              onClick={() => {
                setActivePage(item.name);
                setNotice("");
              }}
            >
              <span className="nav-icon">{item.icon}</span>
              <span>{item.name}</span>
              {item.name === "Incidents" && (
                <span className="nav-count">{incidents.length}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="safety-card">
          <span className="safety-icon">✓</span>
          <div>
            <strong>Safe simulation</strong>
            <p>No real infrastructure is affected.</p>
          </div>
        </div>

        <div className="sidebar-footer">AutoRemed v0.1 · Prototype</div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <span className="breadcrumb">DevOps / {activePage}</span>
          <span className="simulation-badge">
            <span className="live-dot" />
            SIMULATION MODE
          </span>
        </header>

        <section className="page-content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">MONITORING CONSOLE</p>
              <h2>{activePage === "Overview" ? "System Overview" : activePage}</h2>
              <p className="subtitle">
                Monitor incidents and remediation in one place.
              </p>
            </div>
            <span className="demo-label">Demo data · Not connected to a live server</span>
          </div>

          {notice && (
            <div className="notice" role="status">
              <span>✓</span> {notice}
              <button onClick={() => setNotice("")} aria-label="Dismiss notice">×</button>
            </div>
          )}

          {activePage === "Overview" && (
            <>
              <div className="metrics-grid">
                <MetricCard
                  icon="⌁"
                  title="CPU Usage"
                  value="42%"
                  change="↓ 12% vs last hour"
                  color="cyan"
                  points={cpuPoints}
                />
                <MetricCard
                  icon="▤"
                  title="Memory Usage"
                  value="61%"
                  change="↑ 5% vs last hour"
                  color="purple"
                  points={memoryPoints}
                />
                <MetricCard
                  icon="▱"
                  title="Disk Usage"
                  value="48%"
                  change="↓ 8% vs last hour"
                  color="blue"
                  points={cpuPoints}
                />
                <MetricCard
                  icon="✓"
                  title="Services Healthy"
                  value="5/6"
                  change="1 service needs attention"
                  color="green"
                  points={memoryPoints}
                />
              </div>

              <div className="charts-grid">
                <section className="panel resource-panel">
                  <div className="panel-heading">
                    <h3>Resource utilization</h3>
                    <div className="legend">
                      <span><i className="legend-cyan" /> CPU</span>
                      <span><i className="legend-purple" /> Memory</span>
                    </div>
                  </div>
                  <div className="chart-area">
                    {[0, 25, 50, 75, 100].map((tick) => (
                      <div className="chart-gridline" key={tick}>
                        <span>{tick}%</span>
                        <div />
                      </div>
                    ))}
                    <svg viewBox="0 0 500 150" preserveAspectRatio="none" className="main-chart">
                      <polyline className="chart-cpu" points="0,105 35,94 70,100 105,75 140,82 175,50 210,80 245,100 280,85 315,90 350,58 385,72 420,65 455,92 500,78" />
                      <polyline className="chart-memory" points="0,65 35,58 70,70 105,45 140,55 175,25 210,43 245,65 280,52 315,55 350,30 385,42 420,35 455,48 500,32" />
                    </svg>
                  </div>
                  <div className="chart-times">
                    <span>10:00</span><span>10:05</span><span>10:10</span>
                    <span>10:15</span><span>10:20</span><span>10:25</span>
                  </div>
                </section>

                <section className="panel distribution-panel">
                  <div className="panel-heading">
                    <h3>Incident distribution</h3>
                  </div>
                  <div className="distribution-content">
                    <div className="donut">
                      <div>
                        <strong>{incidents.length}</strong>
                        <span>Total incidents</span>
                      </div>
                    </div>
                    <div className="distribution-legend">
                      <p><i className="severity-high-dot" /> High <strong>{incidents.filter(i => i.severity === "High").length}</strong></p>
                      <p><i className="severity-medium-dot" /> Medium <strong>{incidents.filter(i => i.severity === "Medium").length}</strong></p>
                      <p><i className="severity-low-dot" /> Low <strong>{incidents.filter(i => i.severity === "Low").length}</strong></p>
                    </div>
                  </div>
                </section>
              </div>
            </>
          )}

          {(activePage === "Overview" || activePage === "Incidents") && (
            <section className="panel incidents-panel">
              <div className="panel-heading">
                <h3>Recent incidents</h3>
                <button className="text-button" onClick={() => setActivePage("Incidents")}>
                  View incidents →
                </button>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Incident</th>
                      <th>Severity</th>
                      <th>Detected</th>
                      <th>Status</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {incidents.map((incident) => (
                      <tr key={incident.id}>
                        <td>
                          <span className="incident-name">{incident.name}</span>
                          <span className="incident-id">{incident.id}</span>
                        </td>
                        <td><span className={`pill ${incident.severity.toLowerCase()}`}>{incident.severity}</span></td>
                        <td>{incident.time}</td>
                        <td><span className={`status ${incident.status.startsWith("Approved") ? "approved" : incident.status.toLowerCase().replaceAll(" ", "-").replace(/[()]/g, "")}`}>{incident.status}</span></td>
                        <td>
                          <button className="small-button" onClick={() => {
                            setActivePage("Remediation");
                            setNotice(`Selected ${incident.id}: ${incident.name}`);
                          }}>Details</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {(activePage === "Overview" || activePage === "Remediation") && (
            <section className="panel remediation-panel">
              <div className="panel-heading">
                <h3>Remediation queue</h3>
                <span className="queue-count">{pending} pending</span>
              </div>
              {incidents.filter(i => i.status === "Open").length === 0 ? (
                <div className="empty-state">
                  <span>✓</span>
                  <strong>No pending approvals</strong>
                  <p>All current remediation requests have been reviewed.</p>
                </div>
              ) : incidents.filter(i => i.status === "Open").map((incident) => (
                <article className="remediation-item" key={incident.id}>
                  <div className="remediation-top">
                    <div>
                      <strong>{incident.name}</strong>
                      <p>Proposed action: Review and investigate simulated incident</p>
                      <small>{incident.id} · Detected at {incident.time}</small>
                    </div>
                    <span className={`pill ${incident.severity.toLowerCase()}`}>{incident.severity}</span>
                  </div>
                  <div className="approval-actions">
                    <button className="approve-button" onClick={() => updateIncident(incident.id, "Approve")}>✓ Approve (simulation)</button>
                    <button className="reject-button" onClick={() => updateIncident(incident.id, "Reject")}>× Reject</button>
                  </div>
                </article>
              ))}
              <div className="simulation-note">
                <span>ⓘ</span>
                Approval buttons only update demo state. They do not execute real remediation.
              </div>
            </section>
          )}

          {activePage === "Activity Logs" && (
            <section className="panel">
              <div className="panel-heading"><h3>Activity logs</h3></div>
              <p className="empty-description">Prototype initialized. Incident decisions and approval changes are currently held in browser memory. Persistent backend audit logging will be connected later.</p>
            </section>
          )}

          {activePage === "Settings" && (
            <section className="panel">
              <div className="panel-heading"><h3>Project settings</h3></div>
              <div className="settings-row"><span>Environment</span><strong>Local simulation</strong></div>
              <div className="settings-row"><span>Backend connection</span><strong className="muted-status">Not connected</strong></div>
              <div className="settings-row"><span>Automatic real-world actions</span><strong>Disabled</strong></div>
            </section>
          )}

          <footer className="page-footer">
            AutoRemed · Academic prototype · All displayed metrics are simulated
          </footer>
        </section>
      </main>
    </div>
  );
}

export default App;
