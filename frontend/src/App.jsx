import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { usePoll } from './hooks.js'
import { Badge, ToastProvider, useAction } from './components/ui.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Monitoring from './pages/Monitoring.jsx'
import Incidents from './pages/Incidents.jsx'
import Remediation from './pages/Remediation.jsx'
import Logs from './pages/Logs.jsx'
import Demo from './pages/Demo.jsx'

const PAGES = [
  ['dashboard', 'Dashboard', Dashboard], ['monitoring', 'System Monitoring', Monitoring], ['incidents', 'Incidents', Incidents],
  ['remediation', 'Remediation Center', Remediation], ['logs', 'Activity Logs', Logs], ['demo', 'Demo Center', Demo],
]
const readHash = () => { const h = window.location.hash.replace('#/', ''); return PAGES.some((p) => p[0] === h) ? h : 'dashboard' }

function Shell() {
  const [page, setPage] = useState(readHash())
  useEffect(() => { const f = () => setPage(readHash()); window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f) }, [])
  const go = (p) => { window.location.hash = `#/${p}` }
  const health = usePoll(() => api.health(), [], 4000)
  const { run, busy } = useAction()
  const Page = PAGES.find((p) => p[0] === page)[2]
  const mode = health.data?.mode
  return (
    <div className="shell">
      <nav className="side">
        <div className="brand">Auto<span>Remed</span></div>
        {PAGES.map(([id, label]) => <a key={id} href={`#/${id}`} className={page === id ? 'on' : ''}>{label}</a>)}
        <div className="side-foot muted small">Read-only real host · remediation only in simulation</div>
      </nav>
      <div className="main">
        <header className="top">
          <div className="top-l">
            {health.error ? <Badge value="critical">BACKEND UNREACHABLE</Badge> : health.data ? (<>
              <Badge value={mode === 'approval' ? 'warning' : 'ok'}>MODE: {mode?.toUpperCase()}</Badge>
              <Badge value={health.data.monitoring_running ? 'ok' : 'critical'}>MONITORING {health.data.monitoring_running ? 'ON' : 'OFF'}</Badge>
              <span className="muted small">DB {health.data.database} · v{health.data.version}</span></>) : <span className="muted small">Connecting…</span>}
          </div>
          {mode && <button className="btn sm" disabled={busy} onClick={async () => { await run(() => api.setMode(mode === 'approval' ? 'autonomous' : 'approval'), 'Mode changed'); health.reload() }}>
            Switch to {mode === 'approval' ? 'Autonomous' : 'Approval'} mode</button>}
        </header>
        <main><Page go={go} /></main>
      </div>
    </div>
  )
}

export default function App() { return <ToastProvider><Shell /></ToastProvider> }
