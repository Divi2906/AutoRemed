
import { useState, useEffect } from "react";
import "./App.css";

const API_URL = "http://127.0.0.1:8000";

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
      <svg
        className="sparkline"
        viewBox="0 0 240 40"
        preserveAspectRatio="none"
        aria-label={`${title} trend`}
      >
        <polyline points={points} />
      </svg>
    </article>
  );
}

function App() {
  const [activePage, setActivePage] = useState("Overview");
  const [incidents, setIncidents] = useState([]);
  const [metrics, setMetrics] = useState({});
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const [activityLogs, setActivityLogs] = useState([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState("");

  // Fetch actual incidents from the backend
  async function fetchMonitorData() {
    try {
      const response = await fetch(`${API_URL}/api/v1/monitor`, {
        method: "POST",
        headers: {
          Accept: "application/json",
        },
      });

      if (!response.ok) {
        throw new Error(`Backend returned ${response.status}`);
      }

      const data = await response.json();

      // The monitor API returns current CPU, memory, and disk metrics separately
      // from the incident list. Metrics must not be inferred from incidents.
      setMetrics(data.metrics || {});

      const receivedIncidents = (data.incidents || []).map(
        (incident, index) => ({
          id: incident.id || `INC-${String(index + 1).padStart(3, "0")}`,
          name: incident.type || incident.name || "Unknown incident",
          metric: incident.metric,
          actual_value: incident.actual_value,
          threshold: incident.threshold,
          severity: incident.severity
            ? incident.severity.charAt(0).toUpperCase() +
              incident.severity.slice(1).toLowerCase()
            : "Unknown",
          time: incident.timestamp
            ? new Date(incident.timestamp).toLocaleTimeString()
            : new Date().toLocaleTimeString(),
          status: incident.status || "Open",
        })
      );

      setIncidents((current) =>
        receivedIncidents.map((incoming) => {
          const previous = current.find((item) => item.id === incoming.id);
          return {
            ...incoming,
            status: incoming.status !== "Open"
              ? incoming.status
              : previous?.status || "Open",
          };
        })
      );
      setConnected(true);
      setError("");
    } catch (err) {
      setConnected(false);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  // Fetch data when dashboard opens and refresh every 10 seconds
  useEffect(() => {
    fetchMonitorData();

    const interval = setInterval(() => {
      fetchMonitorData();
    }, 10000);

    return () => clearInterval(interval);
  }, []);

  const pending = incidents.filter(
    (incident) => incident.status === "Open"
  ).length;

  async function updateIncident(id, decision) {
    const incident = incidents.find((item) => item.id === id);
    if (!incident || actionLoading) return;

    setActionLoading(id);
    setNotice("");

    try {
      const response = await fetch(`${API_URL}/api/v1/approval`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          incident_id: incident.id,
          incident: {
            type: incident.name,
            metric: incident.metric,
            actual_value: incident.actual_value,
            threshold: incident.threshold,
            severity: incident.severity.toLowerCase(),
            service: "AutoRemed",
          },
          decision: decision.toLowerCase(),
        }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || data.message || `Backend returned ${response.status}`);
      }
      if (data.success === false) {
        throw new Error(data.message || "The backend could not process this decision.");
      }

      const newStatus =
        data.approval_status === "approved"
          ? "Approved (simulated)"
          : data.approval_status === "rejected"
            ? "Rejected"
            : data.approval_status || "Processed";

      setIncidents((current) =>
        current.map((item) =>
          item.id === id ? { ...item, status: newStatus } : item
        )
      );

      setNotice(data.message || `${id}: ${decision} processed by backend.`);
      await fetchActivityLogs();
    } catch (err) {
      setNotice(`Could not process ${decision.toLowerCase()}: ${err.message}`);
    } finally {
      setActionLoading("");
    }
  }

  async function fetchActivityLogs() {
    setLogsLoading(true);
    try {
      const response = await fetch(`${API_URL}/api/v1/activity-logs`, {
        headers: { Accept: "application/json" },
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || `Backend returned ${response.status}`);
      }
      setActivityLogs(data.logs || []);
    } catch (err) {
      setNotice(`Could not load activity logs: ${err.message}`);
    } finally {
      setLogsLoading(false);
    }
  }

  useEffect(() => {
    if (activePage === "Activity Logs") {
      fetchActivityLogs();
    }
  }, [activePage]);

  // Read current resource values directly from the backend metrics object.
  // A metric can be healthy and therefore have no incident; it should still display.
  function getMetricValue(metric) {
    const value = metrics?.[metric];
    const numericValue = Number(value);

    if (value === undefined || value === null || !Number.isFinite(numericValue)) {
      return "N/A";
    }

    return `${Number(numericValue.toFixed(1))}%`;
  }

  const cpuPoints =
    "0,29 18,25 35,28 53,18 70,21 88,12 106,18 123,9 141,22 158,17 176,25 194,16 212,20 240,12";

  const memoryPoints =
    "0,30 18,20 35,23 53,12 70,16 88,8 106,15 123,11 141,18 158,7 176,14 194,10 212,16 240,5";

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
              className={`nav-item ${
                activePage === item.name ? "active" : ""
              }`}
              onClick={() => {
                setActivePage(item.name);
                setNotice("");
              }}
            >
              <span className="nav-icon">{item.icon}</span>
              <span>{item.name}</span>

              {item.name === "Incidents" && (
                <span className="nav-count">
                  {incidents.length}
                </span>
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

        <div className="sidebar-footer">
          AutoRemed v0.1 · Prototype
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <span className="breadcrumb">
            DevOps / {activePage}
          </span>

          <span className="simulation-badge">
            <span className="live-dot" />
            {connected ? "BACKEND CONNECTED" : "CONNECTING"}
          </span>
        </header>

        <section className="page-content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">MONITORING CONSOLE</p>

              <h2>
                {activePage === "Overview"
                  ? "System Overview"
                  : activePage}
              </h2>

              <p className="subtitle">
                Monitor incidents and remediation in one place.
              </p>
            </div>

            <span className="demo-label">
              {connected
                ? "Connected to AutoRemed backend"
                : "Backend connection unavailable"}
            </span>
          </div>

          <div className="notice" role="status">
            {loading
              ? "Connecting to backend..."
              : connected
                ? `Backend connected. ${incidents.length} incidents received.`
                : `Backend error: ${error}`}
            <button
              className="text-button"
              onClick={fetchMonitorData}
            >
              Refresh
            </button>
          </div>

          {notice && (
            <div className="notice" role="status">
              <span>✓</span> {notice}
              <button onClick={() => setNotice("")}>
                ×
              </button>
            </div>
          )}

          {activePage === "Overview" && (
            <>
              <div className="metrics-grid">
                <MetricCard
                  icon="⌁"
                  title="CPU Usage"
                  value={getMetricValue("cpu")}
                  change="Live backend metrics"
                  color="cyan"
                  points={cpuPoints}
                />

                <MetricCard
                  icon="▤"
                  title="Memory Usage"
                  value={getMetricValue("memory")}
                  change="Live backend metrics"
                  color="purple"
                  points={memoryPoints}
                />

                <MetricCard
                  icon="▱"
                  title="Disk Usage"
                  value={getMetricValue("disk")}
                  change="Live backend metrics"
                  color="blue"
                  points={cpuPoints}
                />

                <MetricCard
                  icon="✓"
                  title="Active Incidents"
                  value={incidents.length}
                  change={`${pending} pending`}
                  color="green"
                  points={memoryPoints}
                />
              </div>

              <div className="charts-grid">
                <section className="panel resource-panel">
                  <div className="panel-heading">
                    <h3>Resource utilization</h3>
                    <div className="legend">
                      <span>CPU · Memory</span>
                    </div>
                  </div>

                  <div className="empty-state">
                    Resource history is not currently provided
                    by the monitor API.
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
                      <p>
                        Critical
                        <strong>
                          {incidents.filter(
                            (i) => i.severity === "Critical"
                          ).length}
                        </strong>
                      </p>

                      <p>
                        High
                        <strong>
                          {incidents.filter(
                            (i) => i.severity === "High"
                          ).length}
                        </strong>
                      </p>

                      <p>
                        Medium
                        <strong>
                          {incidents.filter(
                            (i) => i.severity === "Medium"
                          ).length}
                        </strong>
                      </p>

                      <p>
                        Low
                        <strong>
                          {incidents.filter(
                            (i) => i.severity === "Low"
                          ).length}
                        </strong>
                      </p>
                    </div>
                  </div>
                </section>
              </div>
            </>
          )}

          {(activePage === "Overview" ||
            activePage === "Incidents") && (
            <section className="panel incidents-panel">
              <div className="panel-heading">
                <h3>Recent incidents</h3>

                <button
                  className="text-button"
                  onClick={() => setActivePage("Incidents")}
                >
                  View incidents →
                </button>
              </div>

              {loading ? (
                <p>Loading incidents...</p>
              ) : incidents.length === 0 ? (
                <div className="empty-state">
                  No active incidents detected by the backend.
                </div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Incident</th>
                        <th>Severity</th>
                        <th>Detected value</th>
                        <th>Threshold</th>
                        <th>Status</th>
                        <th>Action</th>
                      </tr>
                    </thead>

                    <tbody>
                      {incidents.map((incident) => (
                        <tr key={incident.id}>
                          <td>
                            <span className="incident-name">
                              {incident.name}
                            </span>
                            <span className="incident-id">
                              {incident.id}
                            </span>
                          </td>

                          <td>
                            <span
                              className={`pill ${incident.severity.toLowerCase()}`}
                            >
                              {incident.severity}
                            </span>
                          </td>

                          <td>{incident.actual_value}</td>
                          <td>{incident.threshold}</td>

                          <td>
                            <span className={`status ${
                              incident.status.toLowerCase().replaceAll(" ", "-")
                            }`}>
                              {incident.status}
                            </span>
                          </td>

                          <td>
                            <button
                              className="small-button"
                              onClick={() => {
                                setActivePage("Remediation");
                                setNotice(
                                  `Selected ${incident.id}: ${incident.name}`
                                );
                              }}
                            >
                              Details
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {(activePage === "Overview" ||
            activePage === "Remediation") && (
            <section className="panel remediation-panel">
              <div className="panel-heading">
                <h3>Remediation queue</h3>
                <span className="queue-count">
                  {pending} pending
                </span>
              </div>

              {incidents.filter(
                (i) => i.status === "Open"
              ).length === 0 ? (
                <div className="empty-state">
                  <span>✓</span>
                  <strong>No pending approvals</strong>
                  <p>
                    No incidents are waiting for review.
                  </p>
                </div>
              ) : (
                incidents
                  .filter((i) => i.status === "Open")
                  .map((incident) => (
                    <article
                      className="remediation-item"
                      key={incident.id}
                    >
                      <div className="remediation-top">
                        <div>
                          <strong>{incident.name}</strong>
                          <p>
                            Proposed action: Review and investigate
                            detected incident.
                          </p>
                          <small>
                            {incident.id} · {incident.metric}
                          </small>
                        </div>

                        <span
                          className={`pill ${incident.severity.toLowerCase()}`}
                        >
                          {incident.severity}
                        </span>
                      </div>

                      <div className="approval-actions">
                        <button
                          className="approve-button"
                          disabled={actionLoading === incident.id}
                          onClick={() => updateIncident(incident.id, "Approve")}
                        >
                          {actionLoading === incident.id ? "Processing..." : "✓ Approve"}
                        </button>

                        <button
                          className="reject-button"
                          disabled={actionLoading === incident.id}
                          onClick={() => updateIncident(incident.id, "Reject")}
                        >
                          {actionLoading === incident.id ? "Processing..." : "× Reject"}
                        </button>
                      </div>
                    </article>
                  ))
              )}

              <div className="simulation-note">
                <span>ⓘ</span>
                Decisions are sent to the backend. Approved actions must remain
                simulation-only; no real infrastructure is changed.
              </div>
            </section>
          )}

          {activePage === "Activity Logs" && (
            <section className="panel">
              <div className="panel-heading">
                <h3>Activity logs</h3>
                <button className="text-button" onClick={fetchActivityLogs}>
                  Refresh logs
                </button>
              </div>

              {logsLoading ? (
                <p>Loading activity logs...</p>
              ) : activityLogs.length === 0 ? (
                <div className="empty-state">
                  No activity log records returned by the backend.
                </div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>Incident</th>
                        <th>Action</th>
                        <th>Approval</th>
                        <th>Execution</th>
                        <th>Message</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activityLogs.map((log, index) => (
                        <tr key={`${log.timestamp || "log"}-${index}`}>
                          <td>{log.timestamp ? new Date(log.timestamp).toLocaleString() : "—"}</td>
                          <td>{log.incident_type || log.type || "—"}</td>
                          <td>{log.proposed_action || "—"}</td>
                          <td>{log.approval_status || "—"}</td>
                          <td>{log.execution_status || "—"}</td>
                          <td>{log.message || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {activePage === "Settings" && (
            <section className="panel">
              <div className="panel-heading">
                <h3>Project settings</h3>
              </div>

              <div className="settings-row">
                <span>Environment</span>
                <strong>Local development</strong>
              </div>

              <div className="settings-row">
                <span>Backend connection</span>
                <strong className="muted-status">
                  {connected ? "Connected" : "Disconnected"}
                </strong>
              </div>

              <div className="settings-row">
                <span>Automatic real-world actions</span>
                <strong>Disabled</strong>
              </div>
            </section>
          )}

          <footer className="page-footer">
            AutoRemed · Academic prototype · Backend monitoring
          </footer>
        </section>
      </main>
    </div>
  );
}

export default App;
