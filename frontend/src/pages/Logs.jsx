import React, { useState } from 'react'
import { api } from '../api.js'
import { usePoll } from '../hooks.js'
import { fmtDateTime, human } from '../format.js'
import { Async, Badge, Card, EnvTag } from '../components/ui.jsx'

const EVENTS = ['monitoring_started', 'monitoring_stopped', 'incident_detected', 'diagnosis', 'strategy_selected', 'approval_requested', 'approval_granted', 'approval_rejected',
  'execution', 'retry', 'verification', 'incident_resolved', 'incident_escalated', 'config_changed', 'demo_trigger', 'demo_reset', 'health_changed']

export default function Logs() {
  const [f, setF] = useState({ q: '', event_type: '', status: '', incident_id: '', environment: '' })
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const res = usePoll(() => api.logs({ ...f, limit: 300 }), [JSON.stringify(f)], 3000)
  return (
    <div className="page">
      <h2>Activity Logs</h2>
      <Card>
        <div className="filters">
          <input placeholder="Search message…" value={f.q} onChange={set('q')} aria-label="search logs" />
          <input placeholder="Incident ID" value={f.incident_id} onChange={set('incident_id')} aria-label="incident id" />
          <input placeholder="Event type" list="events" value={f.event_type} onChange={set('event_type')} aria-label="event type" />
          <datalist id="events">{EVENTS.map((e) => <option key={e} value={e} />)}</datalist>
          <input placeholder="Status" value={f.status} onChange={set('status')} aria-label="status" />
          <select value={f.environment} onChange={set('environment')} aria-label="environment"><option value="">All environments</option><option value="simulation">SIMULATION</option><option value="real_host">REAL HOST</option></select>
        </div>
        <Async res={res} what="logs" isEmpty={(d) => !d.items.length} empty="No log entries match.">{(d) => (
          <div className="table-wrap"><table className="tbl small-t">
            <thead><tr><th>Timestamp</th><th>Event</th><th>Incident</th><th>Action</th><th>Status</th><th>Att.</th><th>Env</th><th>Message</th></tr></thead>
            <tbody>{d.items.map((e) => (
              <tr key={e.id}><td className="nowrap mono">{fmtDateTime(e.ts)}</td><td>{human(e.event_type)}</td><td className="mono">{e.incident_id || '—'}</td><td>{e.action || '—'}</td>
                <td>{e.status ? <Badge value={e.status} /> : '—'}</td><td>{e.attempt ?? '—'}</td><td>{e.environment ? <EnvTag env={e.environment} /> : '—'}</td><td>{e.message}</td></tr>))}</tbody></table>
            <div className="muted small">Showing {d.items.length} of {d.total}, newest first</div></div>)}
        </Async>
      </Card>
    </div>
  )
}
