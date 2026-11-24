import React, { useState } from 'react'
import { api } from '../api.js'
import { usePoll } from '../hooks.js'
import { fmtDateTime, human } from '../format.js'
import { Async, Badge, Card, EnvTag, IncidentDetailView } from '../components/ui.jsx'

const STATUSES = ['detected', 'investigating', 'pending_approval', 'remediating', 'retry_in_progress', 'resolved', 'escalated', 'rejected']
const SORTS = [['created_at', 'Time'], ['severity', 'Severity'], ['status', 'Status'], ['type', 'Type'], ['attempts_made', 'Attempts']]

export function IncidentDetailLoader({ id }) {
  const d = usePoll(() => api.incident(id), [id], 2500)
  return <Async res={d} what="incident">{(x) => <IncidentDetailView d={x} onChanged={d.reload} />}</Async>
}

export default function Incidents({ initialId }) {
  const [f, setF] = useState({ q: '', status: '', severity: '', environment: '', sort: 'created_at', order: 'desc' })
  const [sel, setSel] = useState(initialId || null)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const res = usePoll(() => api.incidents({ ...f, limit: 200 }), [JSON.stringify(f)], 3000)
  return (
    <div className="page">
      <h2>Incidents</h2>
      <Card>
        <div className="filters">
          <input placeholder="Search id, type, description…" value={f.q} onChange={set('q')} aria-label="search" />
          <select value={f.status} onChange={set('status')} aria-label="status"><option value="">All statuses</option>{STATUSES.map((s) => <option key={s} value={s}>{human(s)}</option>)}</select>
          <select value={f.severity} onChange={set('severity')} aria-label="severity"><option value="">All severities</option><option>warning</option><option>critical</option></select>
          <select value={f.environment} onChange={set('environment')} aria-label="environment"><option value="">All environments</option><option value="simulation">SIMULATION</option><option value="real_host">REAL HOST</option></select>
          <select value={f.sort} onChange={set('sort')} aria-label="sort">{SORTS.map(([k, l]) => <option key={k} value={k}>Sort: {l}</option>)}</select>
          <select value={f.order} onChange={set('order')} aria-label="order"><option value="desc">Newest/highest first</option><option value="asc">Oldest/lowest first</option></select>
        </div>
        <Async res={res} what="incidents" isEmpty={(d) => !d.items.length} empty="No incidents match. Trigger a fault from the Demo Center or adjust the filters.">{(d) => (
          <div className="table-wrap"><table className="tbl">
            <thead><tr><th>ID</th><th>Type</th><th>Severity</th><th>Env</th><th>Metric</th><th>Value</th><th>Threshold</th><th>Status</th><th>Attempts</th><th>Time</th><th>Root cause / resolution</th></tr></thead>
            <tbody>{d.items.map((i) => (
              <tr key={i.id} className={sel === i.id ? 'sel' : ''} onClick={() => setSel(i.id)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && setSel(i.id)}>
                <td className="mono">{i.id}</td><td>{human(i.type)}</td><td><Badge value={i.severity} /></td><td><EnvTag env={i.environment} /></td>
                <td>{i.metric}</td><td>{i.value_label}</td><td>{i.threshold_label}</td><td><Badge value={i.status} /></td><td>{i.attempts_made}/{i.max_attempts}</td>
                <td className="nowrap">{fmtDateTime(i.created_at)}</td><td className="clip">{i.resolution || i.root_cause}</td></tr>))}</tbody>
          </table><div className="muted small">{d.total} incident(s)</div></div>)}
        </Async>
      </Card>
      {sel && <Card title="Incident details" right={<button className="btn sm" onClick={() => setSel(null)}>Close</button>}><IncidentDetailLoader id={sel} /></Card>}
    </div>
  )
}
