# AutoRemed — Safe, Self-Healing DevOps Prototype

AutoRemed monitors a system, detects abnormal conditions, diagnoses them, picks a remediation strategy (with an
explanation), executes it, **independently verifies** the result, retries intelligently (max **3 total attempts**) and
either resolves the incident or **escalates it for manual intervention**.

> **Safety model.** The *REAL HOST* is monitored read-only via `psutil`. Fault injection and every remediation act
> exclusively on an isolated *SIMULATION* inside the app. No shell commands, no process kills, no file deletion, no
> service restarts. The real executor exists only as a permanently-disabled stub. A simulated repair never claims to fix your machine.

## Problem & objectives
Operators lose time on repetitive incident response, and naive auto-remediation is unsafe: it trusts "success" return
codes, retries blindly and never stops. Objectives: close the loop (monitor → detect → diagnose → select → execute →
verify → retry → resolve/escalate), keep it explainable and deterministic, hard-cap retries, and never touch the real host.

## Features
- Real-host (psutil) and simulated monitoring, strictly separated and labelled `REAL HOST` / `SIMULATION` everywhere
- Configurable thresholds (CPU 75/90, Memory 80/90, Disk 85/95), collection interval, and consecutive-violation rule (transient-spike filtering)
- Incident engine: fingerprints, duplicate prevention, severity classification, validated lifecycle, recovery detection
- Rule-based diagnosis + strategy selection with reasons, previous-outcome analysis and no blind repetition
- Pluggable executors (simulation = default, test, real = disabled); separate verifier that re-reads the actual simulated state
- Retry orchestration with a backend-enforced 3-attempt cap (DB-persisted, survives restarts, race-safe)
- Autonomous and Approval modes (rejected actions never execute)
- Demo Center with 8 deterministic scenarios x 4 faults, reset that keeps history
- Dashboard with 6 pages; SQLite persistence; full activity log

## Architecture (modular monolith)
```
backend/app
  core/         db (SQLite WAL, BEGIN IMMEDIATE), activity log, config service, errors, util
  monitoring/   sources (RealHostSource | SimulatedSource), monitor (singleton loop), health
  simulation/   SimulationState (the only thing remediation may change)
  incidents/    engine (detect/dedupe/lifecycle), diagnosis, repository
  remediation/  strategies (+ranker interface), executors, verifier, orchestrator (retry/escalation/approval)
  demo/         scenarios + fault injection (feeds the real pipeline)
  api/          FastAPI routes, typed schemas, error handlers
frontend/       React 18 + Vite; hand-rolled SVG charts; polls the REST API
e2e/            Playwright browser tests
```
Workflow: `Monitor -> Detect -> Diagnose -> Select strategy -> Execute (simulation) -> Verify (independent) -> Retry (<=3) -> Resolved | Escalated`.

## Setup (Windows PowerShell)
Prereqs: Python 3.11+, Node 20+.
```powershell
# Backend
cd autoremed\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000        # API + docs at http://127.0.0.1:8000/docs

# Frontend (second terminal)
cd autoremed\frontend
npm install
npm run dev                                        # http://localhost:5173 (proxies /api to :8000)
# or: npm run build  -> backend then serves the dashboard itself at http://127.0.0.1:8000
```
The SQLite DB (`backend/data/autoremed.db`) and schema are created automatically on first start. Environment variables: see `.env.example`.

## Tests
```powershell
cd backend;  python -m pytest                      # 117 backend tests (82 functions, parametrized): unit, workflow, API, concurrency, persistence
cd frontend; npm test                              # 8 frontend tests
# Browser E2E (backend must be running; pip install playwright; playwright install chromium)
python e2e\test_e2e.py                             # 19 end-to-end checks through the real UI
```

## Demo (Demo Center page)
1. **Success:** pick *High CPU* -> *First attempt succeeds*. Incident resolves after exactly 1 attempt; verification record shows `recovered`.
2. **Retry:** pick *High memory* -> *Attempts 1 & 2 fail, attempt 3 succeeds*. Watch three different strategies; resolves on attempt 3/3.
3. **Escalation:** pick *Critical disk* -> *All 3 attempts fail*. After exactly 3 attempts the incident is `escalated`, **MANUAL INTERVENTION REQUIRED** appears with the recommended manual step, and nothing further runs.
4. **Approval:** *Service failure* -> *Approval required*. Open **Remediation Center**, read the proposal, Approve (workflow runs) or Reject (zero executions).
5. **Reset demo state** clears the simulation but keeps every incident, log and execution.

## API
Interactive docs at `/docs`; schema in `backend/openapi.json` (30 paths, generated from the code). Everything is under `/api`:
`/health /summary /metrics/{current,history} /monitoring/{status,start,stop} /incidents[/active|/{id}|/simulate|/{id}/resolve]
/remediation[/{id}|/{id}/approve|/{id}/reject] /executions /verification /activity-logs /config[/thresholds|/mode|/monitoring]
/demo/{scenarios,scenario,recover,reset,history}`. Errors: `{"error":{"code","message","details"}}`.

## AI/ML
Strategy ranking is **deterministic and rule-based** (clearly labelled `rule_based`). No model is trained, there are no
training metrics or accuracy claims, and no API keys or network are needed. A ranker interface exists so a trained model
could be plugged in later once meaningful incident data exists.

## Real vs simulated
| Real | Simulated |
|---|---|
| Host CPU/memory/disk via psutil (read-only); real-host incidents are detected and flagged observe-only | Fault injection, simulated CPU/memory/disk/service state, all remediation effects |

## Limitations / future work
Real-host incidents are never remediated (by design). Single-process, single-node. Polling (no websockets). Future: trained
ranker from accumulated history, opt-in sandboxed real executor with allow-listed actions, auth/RBAC, alert integrations.
