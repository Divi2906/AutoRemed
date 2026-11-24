export const fmtTime = (ts) => (ts ? new Date(ts).toLocaleTimeString([], { hour12: false }) : '—')
export const fmtDateTime = (ts) => (ts ? new Date(ts).toLocaleString([], { hour12: false }) : '—')
export const pct = (v) => (v === null || v === undefined ? 'n/a' : `${Number(v).toFixed(1)}%`)
export const human = (s) => (s ? String(s).replace(/_/g, ' ') : '—')
export const STATUS_TONE = {
  ok: 'ok', resolved: 'ok', recovered: 'ok', approved: 'ok', success: 'ok', succeeded: 'ok',
  warning: 'warn', detected: 'warn', investigating: 'warn', pending: 'warn', pending_approval: 'warn',
  remediating: 'info', retry_in_progress: 'info', running: 'info',
  critical: 'bad', escalated: 'bad', failed: 'bad', rejected: 'bad', not_recovered: 'bad', execution_failed: 'bad',
}
export const tone = (s) => STATUS_TONE[s] || 'muted'
