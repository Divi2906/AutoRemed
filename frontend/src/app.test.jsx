import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { request, ApiError } from './api.js'
import { Async, AttemptTimeline, EnvTag } from './components/ui.jsx'
import Incidents from './pages/Incidents.jsx'

const json = (status, body) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) })
beforeEach(() => { vi.restoreAllMocks() })

describe('api client', () => {
  it('builds query strings, skipping empty values', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockImplementation(() => json(200, {}))
    await request('GET', '/incidents', { params: { q: 'cpu', status: '', limit: 5 } })
    expect(f.mock.calls[0][0]).toBe('/api/incidents?q=cpu&limit=5')
  })
  it('maps the backend error envelope to ApiError', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => json(409, { error: { code: 'conflict', message: 'already active' } }))
    await expect(request('POST', '/incidents/simulate', { body: {} })).rejects.toMatchObject({ status: 409, code: 'conflict', message: 'already active' })
  })
  it('reports an unreachable backend clearly', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('failed'))
    await expect(request('GET', '/health')).rejects.toBeInstanceOf(ApiError)
    await expect(request('GET', '/health')).rejects.toThrow(/Cannot reach/)
  })
})

describe('shared components', () => {
  it('Async shows loading, error (with retry), empty and content states', () => {
    const retry = vi.fn()
    const { rerender } = render(<Async res={{ loading: true, data: null }} what="things">{() => 'x'}</Async>)
    expect(screen.getByText(/Loading things/)).toBeInTheDocument()
    rerender(<Async res={{ loading: false, data: null, error: new Error('boom'), reload: retry }}>{() => 'x'}</Async>)
    expect(screen.getByRole('alert')).toHaveTextContent('boom')
    fireEvent.click(screen.getByText('Retry')); expect(retry).toHaveBeenCalled()
    rerender(<Async res={{ loading: false, data: [] }} isEmpty={(d) => !d.length} empty="Nothing here">{() => 'x'}</Async>)
    expect(screen.getByText('Nothing here')).toBeInTheDocument()
    rerender(<Async res={{ loading: false, data: [1] }}>{(d) => `n=${d.length}`}</Async>)
    expect(screen.getByText('n=1')).toBeInTheDocument()
  })
  it('EnvTag labels the environment', () => {
    render(<><EnvTag env="real_host" /><EnvTag env="simulation" /></>)
    expect(screen.getByText('REAL HOST')).toBeInTheDocument(); expect(screen.getByText('SIMULATION')).toBeInTheDocument()
  })
  it('AttemptTimeline shows each attempt, failure reasons and the escalation banner', () => {
    const attempts = [
      { attempt: 1, strategy: 'workload_reduction', outcome: 'execution_failed', decision: { reason: 'because A' },
        execution: { status: 'failed', action: 'throttle', duration_ms: 3, executor: 'simulation', message: 'm', error: 'exec blew up' }, verification: null },
      { attempt: 2, strategy: 'cpu_optimization_simulation', outcome: 'execution_succeeded_issue_remains', decision: { reason: 'because B' },
        execution: { status: 'success', action: 'opt', duration_ms: 4, executor: 'simulation', message: 'ok' },
        verification: { result: 'not_recovered', criteria: { rule: 'cpu < 75%' }, failure_reason: 'cpu still 90%' } },
    ]
    render(<AttemptTimeline attempts={attempts} max={3} escalated />)
    expect(screen.getByText('Attempt 1/3')).toBeInTheDocument(); expect(screen.getByText('Attempt 2/3')).toBeInTheDocument()
    expect(screen.getByText('exec blew up')).toBeInTheDocument(); expect(screen.getByText('cpu still 90%')).toBeInTheDocument()
    expect(screen.getByText(/Manual intervention required/)).toBeInTheDocument()
  })
})

describe('Incidents page', () => {
  it('shows the empty state, then sends the selected filter to the backend', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockImplementation(() => json(200, { items: [], total: 0, limit: 200, offset: 0 }))
    render(<Incidents />)
    await waitFor(() => expect(screen.getByText(/No incidents match/)).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('severity'), { target: { value: 'critical' } })
    await waitFor(() => expect(f.mock.calls.some((c) => String(c[0]).includes('severity=critical'))).toBe(true))
  })
  it('shows an error state when the API fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => json(500, { error: { code: 'internal_error', message: 'db down' } }))
    render(<Incidents />)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('db down'))
  })
})
