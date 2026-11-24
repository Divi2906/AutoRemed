import React, { useState } from 'react'
import { api } from '../api.js'
import { usePoll } from '../hooks.js'
import { fmtDateTime } from '../format.js'
import { Async, Badge, Card, EnvTag, LineChart, MetricTile, useAction } from '../components/ui.jsx'

function Thresholds({ cfg, reload }) {
  const { run, busy } = useAction()
  const [vals, setVals] = useState(null)
  const cur = vals || Object.fromEntries(['cpu', 'memory', 'disk'].map((k) => [k, { ...cfg.thresholds[k] }]))
  const set = (k, f, v) => setVals({ ...cur, [k]: { ...cur[k], [f]: v } })
  return (
    <Card title="Thresholds (applies to both environments)">
      <form className="form" onSubmit={async (e) => {
        e.preventDefault()
        const body = Object.fromEntries(Object.entries(cur).map(([k, v]) => [k, { warning: Number(v.warning), critical: Number(v.critical) }]))
        const r = await run(() => api.setThresholds(body), 'Thresholds saved')
        if (r) { setVals(null); reload() }
      }}>
        <table className="tbl small-t"><thead><tr><th>Metric</th><th>Warning %</th><th>Critical %</th></tr></thead>
          <tbody>{Object.keys(cur).map((k) => (
            <tr key={k}><td>{k}</td>
              <td><input type="number" min="1" max="100" value={cur[k].warning} onChange={(e) => set(k, 'warning', e.target.value)} /></td>
              <td><input type="number" min="1" max="100" value={cur[k].critical} onChange={(e) => set(k, 'critical', e.target.value)} /></td></tr>))}</tbody></table>
        <button className="btn" disabled={busy}>Save thresholds</button>
      </form>
    </Card>
  )
}

function Interval({ cfg, reload }) {
  const { run, busy } = useAction()
  const [v, setV] = useState(cfg.monitoring.interval_seconds)
  const [cs, setCs] = useState(cfg.consecutive_violations.simulation)
  const [cr, setCr] = useState(cfg.consecutive_violations.real_host)
  return (
    <Card title="Collection interval & evaluation rules">
      <form className="form" onSubmit={async (e) => {
        e.preventDefault()
        const r = await run(() => api.setMonitoring({ interval_seconds: Number(v), consecutive_violations_simulation: Number(cs), consecutive_violations_real_host: Number(cr) }), 'Monitoring configuration saved')
        if (r) reload()
      }}>
        <label>Interval (seconds)<input type="number" min="1" max="3600" step="0.5" value={v} onChange={(e) => setV(e.target.value)} /></label>
        <label>Consecutive violations — simulation<input type="number" min="1" max="20" value={cs} onChange={(e) => setCs(e.target.value)} /></label>
        <label>Consecutive violations — real host<input type="number" min="1" max="20" value={cr} onChange={(e) => setCr(e.target.value)} /></label>
        <button className="btn" disabled={busy}>Save</button>
        <p className="muted small">Requiring several consecutive violations stops transient spikes from creating incidents.</p>
      </form>
    </Card>
  )
}

export default function Monitoring() {
  const cur = usePoll(() => api.metricsCurrent(), [], 2000)
  const cfg = usePoll(() => api.config(), [], 0)
  const hr = usePoll(() => api.metricsHistory('real_host', 200), [], 4000)
  const hs = usePoll(() => api.metricsHistory('simulation', 200), [], 3000)
  const { run, busy } = useAction()
  const st = cur.data?.monitoring
  return (
    <div className="page">
      <h2>System Monitoring</h2>
      <Card title="Monitoring loop" right={st && <Badge value={st.running ? 'ok' : 'critical'}>{st.running ? 'RUNNING' : 'STOPPED'}</Badge>}>
        <Async res={cur} what="monitoring">{(c) => (
          <div className="row">
            <dl className="kv inline">
              <dt>Interval</dt><dd>{c.monitoring.interval_seconds}s</dd>
              <dt>Started</dt><dd>{fmtDateTime(c.monitoring.started_at)}</dd>
              <dt>Ticks</dt><dd>{c.monitoring.tick_count}</dd>
              <dt>Errors</dt><dd>{c.monitoring.error_count}</dd>
              <dt>Loop threads</dt><dd>{c.monitoring.thread_count}</dd>
              <dt>Last error</dt><dd>{c.monitoring.last_error || 'none'}</dd>
            </dl>
            <div className="actions">
              <button className="btn" disabled={busy || c.monitoring.running}
                onClick={async () => { await run(() => api.monitoringStart(), (r) => r.changed ? 'Monitoring started' : 'Already running'); cur.reload() }}>Start</button>
              <button className="btn danger" disabled={busy || !c.monitoring.running}
                onClick={async () => { await run(() => api.monitoringStop(), 'Monitoring stopped'); cur.reload() }}>Stop</button>
            </div>
          </div>)}
        </Async>
      </Card>
      <Async res={cur} what="metrics">{(c) => (
        <div className="grid2">
          {[c.real_host, c.simulation].map((m) => (
            <Card key={m.environment} title={<>Current <EnvTag env={m.environment} /></>} right={<Badge value={m.health}>{m.health}</Badge>}>
              <div className="tiles">
                <MetricTile label="CPU" value={m.cpu} status={m.statuses.cpu} threshold={c.thresholds.cpu} />
                <MetricTile label="Memory" value={m.memory} status={m.statuses.memory} threshold={c.thresholds.memory} />
                <MetricTile label="Disk" value={m.disk} status={m.statuses.disk} threshold={c.thresholds.disk} />
              </div>
              <div className="small muted">Sampled {fmtDateTime(m.ts)}{m.environment === 'real_host' ? ' · read-only, never remediated' : ' · service: ' + m.service_state}</div>
            </Card>))}
        </div>)}
      </Async>
      <div className="grid2">
        <Card title="Real host history" right={<EnvTag env="real_host" />}><Async res={hr} what="history">{(r) => <LineChart rows={r} thresholds={cur.data?.thresholds} height={190} />}</Async></Card>
        <Card title="Simulation history" right={<EnvTag env="simulation" />}><Async res={hs} what="history">{(r) => <LineChart rows={r} thresholds={cur.data?.thresholds} height={190} />}</Async></Card>
      </div>
      <Async res={cfg} what="configuration">{(c) => (
        <div className="grid2"><Thresholds cfg={c} reload={() => { cfg.reload(); cur.reload() }} /><Interval cfg={c} reload={() => { cfg.reload(); cur.reload() }} /></div>)}
      </Async>
    </div>
  )
}
