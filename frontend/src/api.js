// Thin client over the AutoRemed REST API. All data shown in the UI comes from here.
export class ApiError extends Error {
  constructor(message, status, code, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

const BASE = '/api'

export async function request(method, path, { params, body } = {}) {
  let url = BASE + path
  if (params) {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const s = qs.toString()
    if (s) url += '?' + s
  }
  let res
  try {
    res = await fetch(url, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (e) {
    throw new ApiError('Cannot reach the AutoRemed backend. Is it running on port 8000?', 0, 'network_error')
  }
  let data = null
  try {
    data = await res.json()
  } catch (_) {
    /* non-JSON body */
  }
  if (!res.ok) {
    const err = data && data.error
    throw new ApiError(err?.message || `HTTP ${res.status}`, res.status, err?.code || 'http_error', err?.details)
  }
  return data
}

export const api = {
  health: () => request('GET', '/health'),
  summary: () => request('GET', '/summary'),
  metricsCurrent: () => request('GET', '/metrics/current'),
  metricsHistory: (environment, limit = 120) => request('GET', '/metrics/history', { params: { environment, limit } }),
  monitoringStatus: () => request('GET', '/monitoring/status'),
  monitoringStart: (interval_seconds) => request('POST', '/monitoring/start', { body: interval_seconds ? { interval_seconds } : {} }),
  monitoringStop: () => request('POST', '/monitoring/stop'),
  incidents: (params) => request('GET', '/incidents', { params }),
  incident: (id) => request('GET', `/incidents/${id}`),
  closeIncident: (id, note) => request('POST', `/incidents/${id}/resolve`, { body: { note } }),
  remediations: (params) => request('GET', '/remediation', { params }),
  remediation: (id) => request('GET', `/remediation/${id}`),
  approve: (id, note) => request('POST', `/remediation/${id}/approve`, { body: { actor: 'operator', note } }),
  reject: (id, note) => request('POST', `/remediation/${id}/reject`, { body: { actor: 'operator', note } }),
  executions: (params) => request('GET', '/executions', { params }),
  verifications: (params) => request('GET', '/verification', { params }),
  logs: (params) => request('GET', '/activity-logs', { params }),
  config: () => request('GET', '/config'),
  setThresholds: (t) => request('PUT', '/config/thresholds', { body: t }),
  setMode: (mode) => request('PUT', '/config/mode', { body: { mode } }),
  setMonitoring: (b) => request('PUT', '/config/monitoring', { body: b }),
  scenarios: () => request('GET', '/demo/scenarios'),
  runScenario: (scenario, fault) => request('POST', '/demo/scenario', { body: { scenario, fault } }),
  simulate: (body) => request('POST', '/incidents/simulate', { body }),
  recover: (fault) => request('POST', '/demo/recover', { body: { fault } }),
  resetDemo: () => request('POST', '/demo/reset'),
  demoHistory: () => request('GET', '/demo/history'),
}
