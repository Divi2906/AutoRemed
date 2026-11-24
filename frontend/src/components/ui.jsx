import React, { createContext, useCallback, useContext, useState } from 'react'
import { api } from '../api.js'
import { fmtTime, human, pct, tone } from '../format.js'

export const Badge = ({ value, children }) => (
  <span className={`badge ${tone(value)}`}>{children ?? human(value)}</span>
)

export const EnvTag = ({ env }) => (
  <span className={`env ${env === 'real_host' ? 'real' : 'sim'}`}>{env === 'real_host' ? 'REAL HOST' : 'SIMULATION'}</span>
)

export const Card = ({ title, right, children, className = '' }) => (
  <section className={`card ${className}`}>
    {(title || right) && (
      <header className="card-h">
        <h3>{title}</h3>
        <div>{right}</div>
      </header>
    )}
    {children}
  </section>
)

export const Loading = ({ what = 'data' }) => <div className="state" role="status">Loading {what}…</div>
export const Empty = ({ children }) => <div className="state empty">{children}</div>
export const ErrorBox = ({ error, onRetry }) => (
  <div className="state error" role="alert">
    <strong>Request failed:</strong> {error?.message || String(error)}
    {onRetry && <button className="btn sm" onClick={onRetry}>Retry</button>}
  </div>
)

// Renders loading / error / empty / content for a usePoll result.
export function Async({ res, what, isEmpty, empty, children }) {
  if (res.loading && !res.data) return <Loading what={what} />
  if (res.error && !res.data) return <ErrorBox error={res.error} onRetry={res.reload} />
  if (res.data && isEmpty && isEmpty(res.data)) return <Empty>{empty}</Empty>
  return (
    <>
      {res.error && <ErrorBox error={res.error} onRetry={res.reload} />}
      {res.data && children(res.data)}
    </>
  )
}

// ---- toasts (only shown for real API outcomes)
const ToastCtx = createContext(() => {})
export const useToast = () => useContext(ToastCtx)
export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const push = useCallback((kind, text) => {
    const id = Math.random().toString(36).slice(2)
    setItems((s) => [...s, { id, kind, text }])
    setTimeout(() => setItems((s) => s.filter((t) => t.id !== id)), 5000)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  )
}

// Run an API action, toast the real outcome.
export function useAction() {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const run = useCallback(async (fn, okMsg) => {
    setBusy(true)
    try {
      const r = await fn()
      if (okMsg) toast('ok', typeof okMsg === 'function' ? okMsg(r) : okMsg)
      return r
    } catch (e) {
      toast('bad', e.message)
      return null
    } finally {
      setBusy(false)
    }
  }, [toast])
  return { run, busy }
}

// ---- gauge / metric tile
export function MetricTile({ label, value, status, threshold }) {
  const v = value ?? 0
  return (
    <div className={`tile ${status || 'muted'}`}>
      <div className="tile-top"><span>{label}</span><Badge value={status} /></div>
      <div className="tile-val">{value === null || value === undefined ? 'n/a' : pct(value)}</div>
      <div className="bar"><div style={{ width: `${Math.min(100, v)}%` }} /></div>
      {threshold && <div className="tile-th">warn {threshold.warning}% · crit {threshold.critical}%</div>}
    </div>
  )
}

// ---- SVG line chart over real backend history rows
const COLORS = { cpu: '#5aa9ff', memory: '#b48cff', disk: '#4cd7a5' }
export function LineChart({ rows, thresholds, height = 150 }) {
  if (!rows || rows.length < 2) return <Empty>Collecting history… (needs at least 2 samples)</Empty>
  const W = 600, H = height, P = 24
  const x = (i) => P + (i * (W - P - 6)) / (rows.length - 1)
  const y = (v) => H - 14 - (Math.max(0, Math.min(100, v)) / 100) * (H - 22)
  const line = (k) => rows.map((r, i) => (r[k] == null ? null : `${x(i).toFixed(1)},${y(r[k]).toFixed(1)}`)).filter(Boolean).join(' ')
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="metric history">
        {[0, 25, 50, 75, 100].map((g) => (
          <g key={g}>
            <line x1={P} x2={W - 6} y1={y(g)} y2={y(g)} className="grid" />
            <text x={2} y={y(g) + 3} className="axis">{g}</text>
          </g>
        ))}
        {thresholds && <line x1={P} x2={W - 6} y1={y(thresholds.cpu.critical)} y2={y(thresholds.cpu.critical)} className="crit-line" />}
        {['cpu', 'memory', 'disk'].map((k) => <polyline key={k} points={line(k)} fill="none" stroke={COLORS[k]} strokeWidth="1.8" />)}
      </svg>
      <div className="legend">
        {['cpu', 'memory', 'disk'].map((k) => <span key={k}><i style={{ background: COLORS[k] }} />{k}</span>)}
        {thresholds && <span><i className="dash" />cpu critical ({thresholds.cpu.critical}%)</span>}
        <span className="muted">{fmtTime(rows[0].ts)} – {fmtTime(rows[rows.length - 1].ts)}</span>
      </div>
    </div>
  )
}

// ---- attempt timeline (decision -> execution -> verification per attempt)
export function AttemptTimeline({ attempts, max = 3, escalated }) {
  if (!attempts?.length) return <Empty>No remediation attempts for this incident.</Empty>
  return (
    <ol className="attempts">
      {attempts.map((a) => (
        <li key={a.attempt} className={`attempt ${tone(a.outcome)}`}>
          <div className="a-head">
            <strong>Attempt {a.attempt}/{max}</strong>
            <code>{a.strategy}</code>
            <Badge value={a.outcome} />
          </div>
          {a.decision && <p className="reason">{a.decision.reason}</p>}
          <div className="a-grid">
            <div><label>Execution</label>
              {a.execution ? <><Badge value={a.execution.status} /> <span className="muted">{a.execution.action} · {a.execution.duration_ms}ms · {a.execution.executor}</span>
                <div className="small">{a.execution.message}</div>
                {a.execution.error && <div className="small bad-t">{a.execution.error}</div>}</> : <span className="muted">not executed</span>}
            </div>
            <div><label>Independent verification</label>
              {a.verification ? <><Badge value={a.verification.result} />
                <div className="small">{a.verification.criteria?.rule}</div>
                {a.verification.failure_reason && <div className="small bad-t">{a.verification.failure_reason}</div>}</> : <span className="muted">not verified</span>}
            </div>
            <div><label>State before → after</label>
              <StateDiff before={a.state_before || a.verification?.before} after={a.state_after || a.verification?.after} /></div>
          </div>
        </li>
      ))}
      {escalated && <li className="attempt bad"><strong>Automation stopped</strong> — all {max} attempts used. Manual intervention required.</li>}
    </ol>
  )
}

export function StateDiff({ before, after }) {
  if (!before && !after) return <span className="muted">—</span>
  const f = (s) => (s ? `cpu ${s.cpu}% · mem ${s.memory}% · disk ${s.disk}% · svc ${s.service_state}` : '—')
  return <div className="small mono"><div>{f(before)}</div><div>→ {f(after)}</div></div>
}

// ---- incident detail panel (used by Incidents and Remediation Center)
export function IncidentDetailView({ d, onChanged }) {
  const { run, busy } = useAction()
  const inc = d.incident
  const escalated = inc.status === 'escalated'
  return (
    <div className="detail">
      <div className="d-head">
        <h3>{inc.id}</h3><EnvTag env={inc.environment} /><Badge value={inc.severity} /><Badge value={inc.status} />
        {inc.manual_intervention_required && <span className="badge bad">MANUAL INTERVENTION REQUIRED</span>}
      </div>
      <p>{inc.description}</p>
      <dl className="kv">
        <dt>Type</dt><dd>{human(inc.type)}</dd>
        <dt>Metric</dt><dd>{inc.metric}: {inc.value_label} (threshold {inc.threshold_label})</dd>
        <dt>Fingerprint</dt><dd className="mono">{inc.fingerprint}</dd>
        <dt>Mode</dt><dd>{inc.mode}{inc.observe_only ? ' · observe-only (real host is never remediated)' : ''}</dd>
        <dt>Attempts</dt><dd>{inc.attempts_made}/{inc.max_attempts}</dd>
        <dt>Probable root cause</dt><dd>{inc.root_cause}</dd>
        <dt>Diagnosis</dt><dd>{inc.diagnosis?.summary} <span className="muted">({inc.diagnosis?.method}, rule {inc.diagnosis?.rule_id})</span>
          <ul>{inc.diagnosis?.evidence?.map((e, i) => <li key={i}>{e}</li>)}</ul></dd>
        {inc.resolution && (<><dt>Resolution</dt><dd>{inc.resolution}</dd></>)}
        {d.current_value && (<><dt>Current value</dt><dd>{d.current_value}</dd></>)}
        {escalated && inc.final_state && (<><dt>Final condition</dt><dd><StateDiff after={inc.final_state} /></dd></>)}
        {inc.recommended_action && (escalated || inc.manual_intervention_required) && (<><dt>Recommended manual step</dt><dd className="callout">{inc.recommended_action}</dd></>)}
      </dl>
      <h4>Attempt timeline</h4>
      <AttemptTimeline attempts={d.attempts} max={inc.max_attempts} escalated={escalated} />
      {d.approvals?.length > 0 && (<><h4>Approval history</h4>
        <ul className="plain">{d.approvals.map((a) => <li key={a.id}><Badge value={a.action} /> by {a.actor} <span className="muted">{fmtTime(a.created_at)} {a.note}</span></li>)}</ul></>)}
      <h4>Incident timeline</h4>
      <ul className="tl">{d.timeline.map((e) => (
        <li key={e.id}><span className="muted mono">{fmtTime(e.ts)}</span> <Badge value={e.status} /> <span>{e.message}</span></li>))}</ul>
      {inc.is_active && ['escalated', 'rejected'].includes(inc.status) && (
        <button className="btn" disabled={busy} onClick={async () => {
          const r = await run(() => api.closeIncident(inc.id, 'closed from dashboard'), 'Incident closed')
          if (r) onChanged?.()
        }}>Close incident (only allowed when the condition is healthy)</button>
      )}
    </div>
  )
}
