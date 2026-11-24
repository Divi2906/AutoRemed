"""Browser end-to-end tests. Drives the real UI (Playwright/Chromium) against a running AutoRemed server.

Usage:  python e2e/test_e2e.py [base_url]     (default http://127.0.0.1:8000)
Requires: the backend running (serving frontend/dist), `pip install playwright`.
"""
import json, sys, time, urllib.request
from playwright.sync_api import sync_playwright, expect

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SHOTS = "e2e/screenshots"
results, console_errors, failed_requests = [], [], []


def api(method, path, body=None):
    req = urllib.request.Request(BASE + "/api" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"__status": e.code, **json.load(e)}


def wait_status(inc_id, want, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        d = api("GET", f"/incidents/{inc_id}")
        if d["incident"]["status"] in want:
            return d
        time.sleep(0.3)
    raise AssertionError(f"{inc_id} never reached {want}; last={d['incident']['status']}")


def check(name):
    def deco(fn):
        try:
            fn()
            results.append((name, "PASS", ""))
            print(f"PASS  {name}")
        except Exception as e:  # noqa
            results.append((name, "FAIL", str(e)[:300]))
            print(f"FAIL  {name}: {str(e)[:300]}")
        return fn
    return deco


def reset(page):
    page.goto(BASE + "/#/demo")
    page.get_by_role("button", name="Reset demo state").click()
    expect(page.get_by_text("Simulation reset").last).to_be_visible()
    time.sleep(0.5)


def run_scenario(page, fault_label, title):
    page.goto(BASE + "/#/demo")
    page.get_by_text(fault_label, exact=True).first.click()
    card = page.locator(".scenario", has=page.get_by_text(title, exact=True))
    card.get_by_role("button").click()
    expect(page.get_by_text("Scenario started").last).to_be_visible()
    time.sleep(0.3)
    return api("GET", "/demo/history")[0]["incident_id"]


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page = ctx.new_page()
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("response", lambda r: failed_requests.append(f"{r.status} {r.url}") if r.status >= 500 else None)
    page.on("pageerror", lambda e: console_errors.append(str(e)))

    @check("all six pages render with data and navigation works")
    def _():
        page.goto(BASE + "/")
        for label, heading in [("Dashboard", "Dashboard"), ("System Monitoring", "System Monitoring"), ("Incidents", "Incidents"),
                               ("Remediation Center", "Remediation Center"), ("Activity Logs", "Activity Logs"), ("Demo Center", "Demo Center")]:
            page.get_by_role("link", name=label).click()
            expect(page.get_by_role("heading", name=heading, level=2)).to_be_visible()
            expect(page.get_by_text("Loading", exact=False)).to_have_count(0, timeout=8000)
        page.goto(BASE + "/#/incidents"); page.reload()        # refresh must not break the app
        expect(page.get_by_role("heading", name="Incidents", level=2)).to_be_visible()

    @check("dashboard separates REAL HOST and SIMULATION and shows healthy start")
    def _():
        reset(page)
        page.goto(BASE + "/#/dashboard")
        expect(page.get_by_text("REAL HOST").first).to_be_visible()
        expect(page.get_by_text("SIMULATION").first).to_be_visible()
        expect(page.get_by_text("Simulated metrics")).to_be_visible()
        assert api("GET", "/metrics/current")["simulation"]["health"] == "ok"
        page.screenshot(path=f"{SHOTS}/dashboard.png")

    @check("healthy metrics create no simulation incident")
    def _():
        reset(page); time.sleep(6)
        assert api("GET", "/incidents/active?environment=simulation") == []

    @check("first attempt succeeds -> resolved after exactly 1 attempt")
    def _():
        reset(page)
        inc = run_scenario(page, "High CPU", "First attempt succeeds")
        d = wait_status(inc, {"resolved", "escalated"})
        assert d["incident"]["status"] == "resolved" and d["incident"]["attempts_made"] == 1
        assert len(d["attempts"]) == 1 and d["attempts"][0]["verification"]["result"] == "recovered"
        expect(page.get_by_text("Attempt 1/3", exact=True)).to_be_visible()
        page.screenshot(path=f"{SHOTS}/demo_success.png")

    @check("attempt 3 succeeds -> resolved after 3 attempts, strategies not blindly repeated")
    def _():
        reset(page)
        inc = run_scenario(page, "High memory", "Attempts 1 & 2 fail, attempt 3 succeeds")
        d = wait_status(inc, {"resolved", "escalated"}, 30)
        assert d["incident"]["status"] == "resolved" and d["incident"]["attempts_made"] == 3
        strategies = [a["strategy"] for a in d["attempts"]]
        assert len(set(strategies)) == 3, strategies
        expect(page.get_by_text("Attempt 3/3", exact=True)).to_be_visible()
        page.screenshot(path=f"{SHOTS}/demo_retry.png")

    @check("all 3 attempts fail -> escalated, exactly 3 executions, manual intervention, automation stops")
    def _():
        reset(page)
        inc = run_scenario(page, "Critical disk usage", "All 3 attempts fail -> escalation")
        d = wait_status(inc, {"escalated", "resolved"}, 30)
        assert d["incident"]["status"] == "escalated" and d["incident"]["manual_intervention_required"] is True
        expect(page.get_by_text("MANUAL INTERVENTION REQUIRED").first).to_be_visible()
        expect(page.locator("strong", has_text="Automation stopped")).to_be_visible()
        time.sleep(8)                                           # monitoring keeps ticking; nothing may re-run
        assert api("GET", f"/executions?incident_id={inc}")["total"] == 3
        msgs = [e["event_type"] for e in api("GET", f"/activity-logs?incident_id={inc}&limit=300")["items"]]
        assert "incident_escalated" in msgs or "escalat" in " ".join(msgs), msgs
        page.screenshot(path=f"{SHOTS}/demo_escalation.png")

    @check("execution succeeds but verification fails -> retry initiated")
    def _():
        reset(page)
        inc = run_scenario(page, "High CPU", "Execution succeeds but verification fails")
        d = wait_status(inc, {"resolved", "escalated"})
        a1 = d["attempts"][0]
        assert a1["execution"]["status"] == "success" and a1["verification"]["result"] == "not_recovered", a1["outcome"]
        assert d["incident"]["attempts_made"] == 2 and d["incident"]["status"] == "resolved"

    @check("incident recovering before remediation -> zero executions")
    def _():
        reset(page)
        inc = run_scenario(page, "High CPU", "Incident recovers before remediation")
        d = wait_status(inc, {"resolved", "escalated"})
        assert d["incident"]["status"] == "resolved" and api("GET", f"/executions?incident_id={inc}")["total"] == 0

    @check("approval required: nothing executes until Approve is clicked in the UI")
    def _():
        reset(page)
        inc = run_scenario(page, "Service failure", "Approval required")
        wait_status(inc, {"pending_approval"})
        assert api("GET", f"/executions?incident_id={inc}")["total"] == 0
        page.goto(BASE + "/#/remediation")
        expect(page.get_by_text("Pending approvals (1)")).to_be_visible()
        page.screenshot(path=f"{SHOTS}/approval.png")
        page.get_by_role("button", name="Approve", exact=True).click()
        d = wait_status(inc, {"resolved", "escalated"})
        assert d["incident"]["status"] == "resolved" and api("GET", f"/executions?incident_id={inc}")["total"] >= 1
        assert [a["action"] for a in d["approvals"]][:2] == ["requested", "approved"]

    @check("approval required: Reject in the UI -> zero executions, logged")
    def _():
        reset(page)
        inc = run_scenario(page, "High memory", "Approval required")
        wait_status(inc, {"pending_approval"})
        page.goto(BASE + "/#/remediation")
        page.get_by_role("button", name="Reject", exact=True).click()
        d = wait_status(inc, {"rejected"})
        time.sleep(4)
        assert api("GET", f"/executions?incident_id={inc}")["total"] == 0
        assert "rejected" in [a["action"] for a in d["approvals"]]

    @check("action rejected scenario -> zero executions")
    def _():
        reset(page)
        inc = run_scenario(page, "High CPU", "Action rejected")
        d = wait_status(inc, {"rejected"})
        assert api("GET", f"/executions?incident_id={inc}")["total"] == 0

    @check("repeated detection + concurrent faults: one incident per fault, no duplicate workflows")
    def _():
        reset(page)
        a = api("POST", "/incidents/simulate", {"fault": "cpu", "plan": ["recover"]})
        b = api("POST", "/incidents/simulate", {"fault": "memory", "plan": ["recover"]})
        dup = api("POST", "/incidents/simulate", {"fault": "cpu"})
        assert dup["__status"] == 409
        for i in (a["incident_id"], b["incident_id"]):
            d = wait_status(i, {"resolved", "escalated"})
            assert d["incident"]["attempts_made"] == 1 and api("GET", f"/executions?incident_id={i}")["total"] == 1

    @check("filters, search and incident details work in the UI")
    def _():
        page.goto(BASE + "/#/incidents")
        page.get_by_label("status").select_option("escalated")
        expect(page.locator("tbody tr").first).to_be_visible()
        n = page.locator("tbody tr").count()
        assert n >= 1 and all("escalated" in t.lower() for t in page.locator("tbody tr td:nth-child(8)").all_inner_texts())
        page.locator("tbody tr").first.click()
        expect(page.get_by_text("Attempt timeline")).to_be_visible()
        page.get_by_label("status").select_option("")
        page.get_by_label("search").fill("zzz-no-such-incident")
        expect(page.get_by_text("No incidents match")).to_be_visible()
        page.get_by_label("search").fill("")

    @check("activity log filters work")
    def _():
        page.goto(BASE + "/#/logs")
        page.get_by_label("search logs").fill("escalat")
        time.sleep(1)
        rows = page.locator("tbody tr")
        expect(rows.first).to_be_visible()
        assert all("escalat" in t.lower() for t in page.locator("tbody tr td:nth-child(8)").all_inner_texts())
        page.screenshot(path=f"{SHOTS}/logs.png")

    @check("monitoring: stop/start controls and threshold update hit the backend")
    def _():
        page.goto(BASE + "/#/monitoring")
        page.get_by_role("button", name="Stop", exact=True).click()
        expect(page.get_by_text("STOPPED").first).to_be_visible()
        assert api("GET", "/monitoring/status")["running"] is False
        page.get_by_role("button", name="Start", exact=True).click()
        expect(page.get_by_text("RUNNING").first).to_be_visible()
        assert api("GET", "/monitoring/status")["thread_count"] == 1
        page.get_by_role("button", name="Save thresholds").click()
        expect(page.get_by_text("Thresholds saved")).to_be_visible()
        page.screenshot(path=f"{SHOTS}/monitoring.png")

    @check("invalid threshold shows a clear API error (no fake success)")
    def _():
        page.goto(BASE + "/#/monitoring")
        page.locator("tbody tr").nth(0).locator("input").nth(0)  # ensure present
        page.locator("form input[type=number]").nth(0).fill("95")   # cpu warning 95 > critical 90
        page.get_by_role("button", name="Save thresholds").click()
        expect(page.locator(".toast.bad")).to_be_visible()

    @check("demo reset keeps history")
    def _():
        before = api("GET", "/incidents?limit=500")["total"]
        reset(page)
        assert api("GET", "/incidents?limit=500")["total"] == before > 0
        assert len(api("GET", "/demo/history")) > 0

    @check("mobile viewport has no horizontal page scroll")
    def _():
        m = browser.new_context(viewport={"width": 390, "height": 800}).new_page()
        m.goto(BASE + "/#/dashboard"); time.sleep(1.5)
        assert m.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal overflow"
        m.screenshot(path=f"{SHOTS}/mobile.png")

    @check("no console errors or 5xx responses during the whole run")
    def _():
        noisy = [e for e in console_errors if "409" not in e and "422" not in e and "Failed to load resource" not in e]
        assert not noisy and not failed_requests, (noisy, failed_requests)

    browser.close()

passed = sum(1 for r in results if r[1] == "PASS")
print(f"\n{passed}/{len(results)} E2E checks passed")
sys.exit(0 if passed == len(results) else 1)
