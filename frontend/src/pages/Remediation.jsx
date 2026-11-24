import React, { useState } from 'react'
import { api } from '../api.js'
import { usePoll } from '../hooks.js'
import { fmtDateTime, human } from '../format.js'
import { Async, Badge, Card, EnvTag, useAction } from '../components/ui.jsx'
import { IncidentDetailLoader } from './Incidents.jsx'

function Approvals({ items, onDone, onSelect }) {
  const { run, busy } = useAction()
  const [notes, setNotes] = useState({})
  return (
    <Card title={`Pending approvals (${items.length})`}>
      {items.map((r) => (
        <div key={r.id} className="approval">
          <div className="d-head"><strong>{r.id}</strong><span className="mono">{r.incident_id}</span><EnvTag env={r.environment} /><Badge value={r.severity} /></div>
          <p><strong>Proposed strategy:</strong> <code>{r.proposal?.strategy || r.proposed_strategy}</code></p>
          <p className="reason">{r.proposal?.reason}</p>
          {r.proposal?.expected_outcome && <p className="small muted">Expected outcome: {r.proposal.expected_outcome}</p>}
          <p className="small muted">Approval does not bypass the 3-attempt limit or safety checks. Rejected actions never execute.</p>
          <div className="actions">
            <input placeholder="Optional note" value={notes[r.id] || ''} onChange={(e) => setNotes({ ...notes, [r.id]: e.target.value })} />
            <button className="btn" disabled={busy} onClick={async () => { if (await run(() => api.approve(r.id, notes[r.id]), 'Approved — remediation workflow started')) onDone() }}>Approve</button>
            <button className="btn danger" disabled={busy} onClick={async () => { if (await run(() => api.reject(r.id, notes[r.id]), 'Rejected — nothing was executed')) onDone() }}>Reject</button>
            <button className="btn sm" onClick={() => onSelect(r.incident_id)}>View incident</button>
          </div>
        </div>))}
    </Card>
  )
}

export default function Remediation() {
  const [sel, setSel] = useState(null)
  const [status, setStatus] = useState('')
  const pending = usePoll(() => api.remediations({ approval_state: 'pending', limit: 50 }), [], 2500)
  const all = usePoll(() => api.remediations({ status, limit: 100 }), [status], 3000)
  const execs = usePoll(() => api.executions({ limit: 15 }), [], 3000)
  const vers = usePoll(() => api.verifications({ limit: 15 }), [], 3000)
  const reload = () => { pending.reload(); all.reload(); execs.reload(); vers.reload() }
  return (
    <div className="page">
      <h2>Remediation Center</h2>
      <Async res={pending} what="approvals">{(d) => d.items.length > 0 && <Approvals items={d.items} onDone={reload} onSelect={setSel} />}</Async>
      <Card title="Remediation workflows" right={
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="remediation status">
          <option value="">All</option>{['pending_approval', 'running', 'resolved', 'escalated', 'rejected'].map((s) => <option key={s} value={s}>{human(s)}</option>)}
        </select>}>
        <Async res={all} what="remediations" isEmpty={(d) => !d.items.length} empty="No remediation workflows yet. Trigger a fault from the Demo Center.">{(d) => (
          <div className="table-wrap"><table className="tbl">
            <thead><tr><th>Remediation</th><th>Incident</th><th>Type</th><th>Env</th><th>Mode</th><th>Approval</th><th>Status</th><th>Attempt</th><th>Manual?</th></tr></thead>
            <tbody>{d.items.map((r) => (
              <tr key={r.id} className={sel === r.incident_id ? 'sel' : ''} onClick={() => setSel(r.incident_id)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && setSel(r.incident_id)}>
                <td className="mono">{r.id}</td><td className="mono">{r.incident_id}</td><td>{human(r.incident_type)}</td><td><EnvTag env={r.environment} /></td>
                <td>{r.mode}</td><td><Badge value={r.approval_state} /></td><td><Badge value={r.status} /></td>
                <td>{r.attempts_made}/{r.max_attempts}</td><td>{r.manual_intervention_required ? <Badge value="critical">YES</Badge> : 'no'}</td></tr>))}</tbody></table></div>)}
        </Async>
      </Card>
      {sel && <Card title="Diagnosis, strategy reasoning & attempt timeline" right={<button className="btn sm" onClick={() => setSel(null)}>Close</button>}><IncidentDetailLoader id={sel} /></Card>}
      <div className="grid2">
        <Card title="Recent executions">
          <Async res={execs} what="executions" isEmpty={(d) => !d.items.length} empty="No executions yet.">{(d) => (
            <table className="tbl small-t"><thead><tr><th>ID</th><th>Incident</th><th>#</th><th>Strategy</th><th>Status</th><th>ms</th><th>Message</th></tr></thead>
              <tbody>{d.items.map((e) => <tr key={e.id}><td className="mono">{e.id}</td><td className="mono">{e.incident_id}</td><td>{e.attempt}</td><td>{e.strategy}</td><td><Badge value={e.status} /></td><td>{e.duration_ms}</td><td className="clip">{e.error || e.message}</td></tr>)}</tbody></table>)}
          </Async>
        </Card>
        <Card title="Independent verifications">
          <Async res={vers} what="verifications" isEmpty={(d) => !d.items.length} empty="No verifications yet.">{(d) => (
            <table className="tbl small-t"><thead><tr><th>ID</th><th>Incident</th><th>#</th><th>Result</th><th>Criteria / failure</th></tr></thead>
              <tbody>{d.items.map((v) => <tr key={v.id}><td className="mono">{v.id}</td><td className="mono">{v.incident_id}</td><td>{v.attempt}</td><td><Badge value={v.result} /></td><td className="clip">{v.failure_reason || v.criteria?.rule}</td></tr>)}</tbody></table>)}
          </Async>
        </Card>
      </div>
    </div>
  )
}
