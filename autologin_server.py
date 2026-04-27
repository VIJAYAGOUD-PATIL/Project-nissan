"""
autologin_server.py — LG Defect Tracker Auto-Login Server
==========================================================
Run this ONCE before using the dashboard:
    python autologin_server.py

Requires:
    pip install playwright flask flask-cors
    python -m playwright install chromium

This server uses Playwright (real browser automation / webscraping)
to open your login page, type the username & password, click login,
and stream live status updates back to the dashboard popup via
Server-Sent Events (SSE).
"""

from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import threading, time, json, queue

# ══════════════════════════════════════════════════════
#  CONFIG — edit these values to match your tool
# ══════════════════════════════════════════════════════
LOGIN_URL       = "https://your-tool-url.com/login"   # ← YOUR LOGIN PAGE URL
USERNAME        = "your_username"                      # ← YOUR USERNAME
PASSWORD        = "your_password"                      # ← YOUR PASSWORD
USERNAME_SEL    = "#username"    # CSS selector for the username input
PASSWORD_SEL    = "#password"    # CSS selector for the password input
LOGIN_BTN_SEL   = "#login-btn"   # CSS selector for the login/submit button
SUCCESS_URL_PART = ""            # optional: part of URL after successful login (e.g. "/dashboard")
HEADLESS        = False          # False = you can see the browser window opening
PORT            = 5055
# ══════════════════════════════════════════════════════

app = Flask(__name__)
CORS(app)   # allow the dashboard HTML (file://) to call this server

# Global status queue used for SSE streaming
_status_queues = {}

def log(q, step, status, message, percent=None):
    """Push a status update into the queue (streamed to browser)."""
    data = {"step": step, "status": status, "message": message}
    if percent is not None:
        data["percent"] = percent
    q.put(data)

def run_autologin(job_id, url, username, password, user_sel, pass_sel, btn_sel):
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    q = _status_queues[job_id]

    try:
        log(q, 1, "running", "🚀 Launching browser…", 5)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=HEADLESS)
            context = browser.new_context()
            page    = context.new_page()

            # ── STEP 1: Navigate ──────────────────────────
            log(q, 1, "running", f"🌐 Opening login page: {url}", 15)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)
            log(q, 1, "done", "✅ Login page loaded successfully", 30)

            time.sleep(0.5)

            # ── STEP 2: Fill username ─────────────────────
            log(q, 2, "running", f"✏️  Locating username field ({user_sel})…", 40)
            try:
                page.wait_for_selector(user_sel, timeout=8000)
                page.fill(user_sel, "")          # clear first
                page.click(user_sel)
                page.type(user_sel, username, delay=80)   # human-like typing
                log(q, 2, "running", f"✏️  Username entered: {username}", 50)
            except PWTimeout:
                log(q, 2, "error", f"❌ Username field '{user_sel}' not found. Check the selector.", 50)
                q.put({"done": True, "success": False})
                browser.close()
                return

            time.sleep(0.3)

            # ── STEP 3: Fill password ─────────────────────
            log(q, 3, "running", f"🔒 Locating password field ({pass_sel})…", 60)
            try:
                page.wait_for_selector(pass_sel, timeout=8000)
                page.fill(pass_sel, "")
                page.click(pass_sel)
                page.type(pass_sel, password, delay=80)
                log(q, 3, "running", "🔒 Password entered", 70)
            except PWTimeout:
                log(q, 3, "error", f"❌ Password field '{pass_sel}' not found. Check the selector.", 70)
                q.put({"done": True, "success": False})
                browser.close()
                return

            time.sleep(0.3)

            # ── STEP 4: Click login button ────────────────
            log(q, 4, "running", f"🖱️  Clicking login button ({btn_sel})…", 80)
            clicked = False
            fallbacks = [btn_sel, 'button[type="submit"]', 'input[type="submit"]',
                         '.login-btn', '#loginButton', '.btn-login', 'button:has-text("Login")',
                         'button:has-text("Sign in")', 'button:has-text("Log in")']
            for sel in fallbacks:
                if not sel:
                    continue
                try:
                    page.wait_for_selector(sel, timeout=3000)
                    page.click(sel)
                    clicked = True
                    log(q, 4, "running", f"🖱️  Clicked: {sel}", 85)
                    break
                except Exception:
                    continue

            if not clicked:
                # Last resort: submit the form
                try:
                    page.evaluate("document.querySelector('form').submit()")
                    clicked = True
                    log(q, 4, "running", "🖱️  Submitted form directly", 85)
                except Exception:
                    log(q, 4, "error", "❌ Could not find login button. Try updating LOGIN_BTN_SEL.", 85)
                    q.put({"done": True, "success": False})
                    browser.close()
                    return

            # ── STEP 5: Wait for navigation / success ─────
            log(q, 5, "running", "⏳ Waiting for login response…", 90)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
                current_url = page.url
                # Check if still on login page (means login failed)
                if "login" in current_url.lower() or "signin" in current_url.lower():
                    # Check for error message on page
                    err_text = page.locator(".error, .alert, .message, [class*='error'], [class*='alert']").first
                    err_msg  = ""
                    try:
                        err_msg = err_text.inner_text(timeout=2000)
                    except Exception:
                        pass
                    if err_msg:
                        log(q, 5, "error", f"❌ Login failed: {err_msg}", 95)
                    else:
                        log(q, 5, "error", "❌ Still on login page — check username/password.", 95)
                    q.put({"done": True, "success": False})
                else:
                    log(q, 5, "done", f"✅ Login successful! Now at: {current_url}", 100)
                    q.put({"done": True, "success": True, "redirect": current_url})
            except PWTimeout:
                log(q, 5, "error", "⚠️ Timeout waiting for redirect — login may have failed.", 95)
                q.put({"done": True, "success": False})

            # Keep browser open so user can see the result
            time.sleep(5)
            browser.close()

    except Exception as ex:
        q.put({"step": 0, "status": "error", "message": f"❌ Unexpected error: {str(ex)}"})
        q.put({"done": True, "success": False})


@app.route("/autologin", methods=["POST"])
def autologin():
    """
    Start a new auto-login job.
    Body (JSON, all optional — falls back to server config):
        { url, username, password, username_sel, password_sel, btn_sel }
    Returns: { job_id }
    """
    data     = request.get_json(silent=True) or {}
    job_id   = str(int(time.time() * 1000))
    _status_queues[job_id] = queue.Queue()

    url      = data.get("url",          LOGIN_URL)
    user     = data.get("username",     USERNAME)
    pwd      = data.get("password",     PASSWORD)
    user_sel = data.get("username_sel", USERNAME_SEL)
    pass_sel = data.get("password_sel", PASSWORD_SEL)
    btn_sel  = data.get("btn_sel",      LOGIN_BTN_SEL)

    t = threading.Thread(target=run_autologin,
                         args=(job_id, url, user, pwd, user_sel, pass_sel, btn_sel),
                         daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/autologin/status/<job_id>")
def autologin_status(job_id):
    """
    Server-Sent Events stream for live status of a job.
    The dashboard popup subscribes to this to show real-time step updates.
    """
    def generate():
        q = _status_queues.get(job_id)
        if not q:
            yield f"data: {json.dumps({'error': 'Unknown job'})}\n\n"
            return
        while True:
            try:
                item = q.get(timeout=30)
                yield f"data: {json.dumps(item)}\n\n"
                if item.get("done"):
                    break
            except queue.Empty:
                yield "data: {\"heartbeat\": true}\n\n"  # keep-alive

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "message": "Auto-login server is running"})


if __name__ == "__main__":
    print("=" * 55)
    print("  LG Auto-Login Server")
    print(f"  Listening on http://localhost:{PORT}")
    print(f"  Login URL : {LOGIN_URL}")
    print(f"  Username  : {USERNAME}")
    print(f"  Headless  : {HEADLESS}")
    print("=" * 55)
    app.run(port=PORT, threaded=True, debug=False)
