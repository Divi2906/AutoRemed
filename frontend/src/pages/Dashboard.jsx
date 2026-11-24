import React from 'react'
import { api } from '../api.js'
import { usePoll } from '../hooks.js'
import { fmtTime, human } from '../format.js'
import { Async, Badge, Card, EnvTag, LineChart, MetricTile, Empty } from '../components/ui.jsx'

function EnvPanel({ m, th, title }) {
  return (
    <Card title={<>{title} <EnvTag env={m.environment} /></>} right={<Badge value={m.health}>health: {m.health}</Badge>}>
      <div className="tiles">
        <MetricTile label="CPU" value={m.cpu} status={m.statuses.cpu} threshold={th.cpu} />
        <MetricTile label="Memory" value={m.memory} status={m.statuses.memory} threshold={th.memory} />
        <MetricTile label="Disk" value={m.disk} status={m.statuses.disk} threshold={th.disk} />
        {m.service_state && <div className={`tile ${m.statuses.service}`}><div className="tile-top"><span>Service</span><Badge value={m.statuses.service} /></div><div className="tile-val sm">{m.service_state}</div></div>}
      </div>
      {m.errors?.length > 0 && <div className="small bad-t">Unavailable metrics: {m.errors.join('; ')}</div>}
    </Card>
  )
}

export default function Dashboard({ go }) {
  const cur = usePoll(() => api.metricsCurrent(), [], 3000)
  const sum = usePoll(() => api.summary(), [], 3000)
  const hr = usePoll(() => api.metricsHistory('real_host', 80), [], 5000)
  const hs = usePoll(() => api.metricsHistory('simulation', 80), [], 3000)
  const inc = usePoll(() => api.incidents({ limit: 8 }), [], 3000)
  const logs = usePoll(() => api.logs({ limit: 10 }), [], 3000)

  return (
    <div className="page">
      <h2>Dashboard</h2>
      <Async res={sum} what="summary">{(s) => (
        <div className="kpis">
          <Kpi label="Active incidents" v={s.active} t={s.active ? 'warn' : 'ok'} onClick={() => go('incidents')} />
          <Kpi label="Critical (active)" v={s.active_critical} t={s.active_critical ? 'bad' : 'ok'} />
          <Kpi label="Resolved" v={s.resolved} t="ok" />
          <Kpi label="Escalated" v={s.escalated} t={s.escalated ? 'bad' : 'muted'} />
          <Kpi label="Pending approvals" v={s.pending_approvals} t={s.pending_approvals ? 'warn' : 'muted'} onClick={() => go('remediation')} />
          <Kpi label="Manual intervention" v={s.manual_intervention} t={s.manual_intervention ? 'bad' : 'muted'} />
          <Kpi label="Remediation success" v={s.remediation_success_rate == null ? 'n/a' : `${s.remediation_success_rate}%`} t="info" />
          <Kpi label="Mode" v={s.mode} t="muted" onClick={() => go('demo')} />
        </div>)}
      </Async>
      <Async res={cur} what="metrics">{(c) => (
        <div className="grid2">
          <EnvPanel m={c.real_host} th={c.thresholds} title="Host metrics" />
          <EnvPanel m={c.simulation} th={c.thresholds} title="Simulated metrics" />
        </div>)}
      </Async>
      <div className="grid2">
        <Card title="Real host history" right={<EnvTag env="real_host" />}>
          <Async res={hr} what="history">{(rows) => <LineChart rows={rows} />}</Async>
        </Card>
        <Card title="Simulation history" right={<EnvTag env="simulation" />}>
          <Async res={hs} what="history">{(rows) => <LineChart rows={rows} />}</Async>
        </Card>
      </div>
      <div className="grid2">
        <Card title="Incident timeline" right={<button className="btn sm" onClick={() => go('incidents')}>All incidents</button>}>
          <Async res={inc} what="incidents" isEmpty={(d) => !d.items.length} empty="No incidents yet. Trigger one from the Demo Center.">{(d) => (
            <ul className="tl">{d.items.map((i) => (
              <li key={i.id}><span className="muted mono">{fmtTime(i.created_at)}</span> <EnvTag env={i.environment} /> <Badge value={i.severity} /> <span>{human(i.type)}</span> → <Badge value={i.status} /> <span className="muted">{i.attempts_made}/{i.max_attempts}</span></li>))}</ul>)}
          </Async>
        </Card>
        <Card title="Recent activity" right={<button className="btn sm" onClick={() => go('logs')}>All logs</button>}>
          <Async res={logs} what="activity" isEmpty={(d) => !d.items.length} empty="No activity yet.">{(d) => (
            <ul className="tl">{d.items.map((e) => (
              <li key={e.id}><span className="muted mono">{fmtTime(e.ts)}</span> <span>{e.message}</span></li>))}</ul>)}
          </Async>
        </Card>
      </div>
    </div>
  )
}

function Kpi({ label, v, t, onClick }) {
  return (
    <div className={`kpi ${t}`} onClick={onClick} role={onClick ? 'button' : undefined} tabIndex={onClick ? 0 : undefined}>
      <div className={`kpi-v ${typeof v === "string" && v.length > 6 ? "txt" : ""}`}>{v}</div><div className="kpi-l">{label}</div>
    </div>
  )
}
