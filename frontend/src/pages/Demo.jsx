import React, { useState } from 'react'
import { api } from '../api.js'
import { usePoll } from '../hooks.js'
import { fmtTime, human } from '../format.js'
import { Async, Badge, Card, EnvTag, MetricTile, useAction } from '../components/ui.jsx'
import { IncidentDetailLoader } from './Incidents.jsx'

const GROUPS = [['remediation', 'Successful remediation'], ['retry', 'Retry demos'], ['escalation', 'Escalation demos'], ['approval', 'Approval demos'], ['recovery', 'Recovery demos']]

export default function Demo() {
  const [fault, setFault] = useState('cpu')
  const [sel, setSel] = useState(null)
  const { run, busy } = useAction()
  const sc = usePoll(() => api.scenarios(), [], 0)
  const hist = usePoll(() => api.demoHistory(), [], 3000)
  const cur = usePoll(() => api.metricsCurrent(), [], 1500)
  const cfg = usePoll(() => api.config(), [], 0)

  const trigger = async (id) => {
    const r = await run(() => api.runScenario(id, fault), (x) => `Scenario started: incident ${x.incident_id || '(none created)'} — expected: ${x.expected}`)
    if (r) { hist.reload(); if (r.incident_id) setSel(r.incident_id) }
  }
  return (
    <div className="page">
      <h2>Demo Center <EnvTag env="simulation" /></h2>
      <p className="muted">Everything here injects faults into the isolated simulation and flows through the real detection → diagnosis → remediation → verification → retry → escalation pipeline. Your actual machine is never touched.</p>
      <div className="grid2">
        <Card title="Operating mode">
          <Async res={cfg} what="config">{(c) => (
            <div className="row">
              <Badge value={c.mode === 'approval' ? 'warning' : 'ok'}>{c.mode.toUpperCase()} MODE</Badge>
              <button className="btn" disabled={busy} onClick={async () => { await run(() => api.setMode(c.mode === 'approval' ? 'autonomous' : 'approval'), 'Mode changed (applies to newly detected incidents)'); cfg.reload() }}>
                Switch to {c.mode === 'approval' ? 'Autonomous' : 'Approval'}</button>
            </div>)}
          </Async>
        </Card>
        <Card title="Simulated state (live)" right={<EnvTag env="simulation" />}>
          <Async res={cur} what="simulation">{(c) => (
            <div className="tiles">
              <MetricTile label="CPU" value={c.simulation.cpu} status={c.simulation.statuses.cpu} />
              <MetricTile label="Memory" value={c.simulation.memory} status={c.simulation.statuses.memory} />
              <MetricTile label="Disk" value={c.simulation.disk} status={c.simulation.statuses.disk} />
              <div className={`tile ${c.simulation.statuses.service}`}><div className="tile-top"><span>Service</span><Badge value={c.simulation.statuses.service} /></div><div className="tile-val sm">{c.simulation.service_state}</div></div>
            </div>)}
          </Async>
          <div className="actions">
            <button className="btn danger" disabled={busy} onClick={async () => { await run(() => api.resetDemo(), (r) => `Simulation reset; ${r.closed_incidents} active simulation incident(s) closed, history kept`); hist.reload(); setSel(null) }}>Reset demo state</button>
            <button className="btn" disabled={busy} onClick={async () => { await run(() => api.recover(fault), `Simulated ${fault} recovered`) }}>Recover {fault} (external recovery)</button>
          </div>
        </Card>
      </div>
      <Async res={sc} what="scenarios">{(d) => (
        <Card title="Fault & scenario selection">
          <div className="faults" role="radiogroup" aria-label="fault">
            {d.faults.map((f) => (
              <label key={f.id} className={`fault ${fault === f.id ? 'on' : ''}`}>
                <input type="radio" name="fault" checked={fault === f.id} onChange={() => setFault(f.id)} />
                <strong>{f.label}</strong><span className="muted small">starts at {f.initial}</span>
              </label>))}
          </div>
          {GROUPS.map(([g, title]) => (
            <div key={g}><h4>{title}</h4>
              <div className="scen">{d.scenarios.filter((s) => s.group === g).map((s) => (
                <div key={s.id} className="scenario">
                  <strong>{s.title}</strong><p className="small">{s.description}</p>
                  <p className="small muted">Plan: {s.plan.length ? s.plan.join(' → ') : 'none'}{s.mode ? ` · ${s.mode} mode` : ''}<br />Expected: {s.expected}</p>
                  <button className="btn" disabled={busy} onClick={() => trigger(s.id)}>Run on {fault}</button>
                </div>))}</div></div>))}
        </Card>)}
      </Async>
      <Card title="Demo history">
        <Async res={hist} what="demo history" isEmpty={(d) => !d.length} empty="No demo runs yet.">{(d) => (
          <table className="tbl small-t"><thead><tr><th>Time</th><th>Scenario</th><th>Fault</th><th>Incident</th><th>Result</th><th>Attempts</th></tr></thead>
            <tbody>{d.map((r) => (
              <tr key={r.id} onClick={() => r.incident_id && setSel(r.incident_id)} className={sel === r.incident_id ? 'sel' : ''}>
                <td className="mono">{fmtTime(r.ts)}</td><td>{human(r.scenario)}</td><td>{r.fault}</td><td className="mono">{r.incident_id || '—'}</td>
                <td>{r.incident_status ? <Badge value={r.incident_status} /> : human(r.status)}</td><td>{r.attempts_made ?? '—'}</td></tr>))}</tbody></table>)}
        </Async>
      </Card>
      {sel && <Card title="Live attempt timeline" right={<button className="btn sm" onClick={() => setSel(null)}>Hide</button>}><IncidentDetailLoader id={sel} /></Card>}
    </div>
  )
}
