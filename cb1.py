"""
Defect Tracker — Python tkinter
Login → Project Selection → Defect Dashboard
Run: python defect_tracker.py
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json, os, datetime, threading, webbrowser

# ── Load .env for CB credentials ──────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass  # python-dotenv not installed; rely on OS env vars

CB_URL      = os.environ.get("CB_URL", "")
CB_USERNAME = os.environ.get("CB_USERNAME", "")
CB_PASSWORD = os.environ.get("CB_PASSWORD", "")

# ── Credentials ───────────────────────────────────────────────────────────────
USERNAME = "admin"
PASSWORD = "admin123"

# ── Palette ───────────────────────────────────────────────────────────────────
BRAND      = "#a50034"
BRAND_DARK = "#6b0022"
SIDEBAR_BG = "#0f1623"
SIDEBAR2   = "#1a2537"
BG         = "#f0f2f5"
SURFACE    = "#ffffff"
BORDER     = "#e2e6ea"
TEXT_PRI   = "#111827"
TEXT_SEC   = "#6b7280"
TEXT_MUT   = "#9ca3af"
GREEN      = "#16a34a"
ORANGE     = "#d97706"
RED_C      = "#dc2626"
BLUE       = "#2563eb"
PURPLE     = "#7c3aed"

DATA_FILE = "defects.json"

ICON_BG = {
    BRAND:     "#f5e6ea",
    BLUE:      "#e8effe",
    PURPLE:    "#ede8fd",
    GREEN:     "#e6f4ec",
    ORANGE:    "#fdf3e3",
    "#0891b2": "#e0f4f8",
}

DEFAULT_PROJECTS = [
    {"name": "Nissan CDC", "color": BRAND,  "icon": "◈", "desc": "Creating & Modify Bug"},
    {"name": "Nissan EU", "color": BLUE,   "icon": "◉", "desc": "Creating & Modify Bug"},
    {"name": "Nissan DA2", "color": PURPLE, "icon": "◆", "desc": "Creating & Modify Bug"},
]

# ── Persistence ───────────────────────────────────────────────────────────────
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"defects": [], "projects": DEFAULT_PROJECTS}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

APP_DATA = load_data()
if "projects" not in APP_DATA:
    APP_DATA["projects"] = DEFAULT_PROJECTS
if "defects" not in APP_DATA:
    APP_DATA["defects"] = []

# ── Playwright: Create defect in CodeBeamer ───────────────────────────────────
def _run_playwright_create(cb_url, cb_user, cb_pass, callback):
    """
    Opens CodeBeamer in a headed browser, logs in, clicks '+' to create a
    defect, waits for the user to fill in fields and click Save, then
    scrapes Issue ID, Description and Issue Link and calls callback(result).
    result is a dict with keys: id, description, link, error (or None on success).
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        callback({"error": "playwright not installed.\nRun: pip install playwright && playwright install chromium"})
        return

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=False,
                slow_mo=200,
                args=["--start-maximized"],
            )
            ctx  = browser.new_context(no_viewport=True)
            page = ctx.new_page()

            # ── 1. Open CB login page ─────────────────────────────────
            page.goto(cb_url, wait_until="domcontentloaded", timeout=30_000)

            # ── 2. Fill login form ────────────────────────────────────
            for sel in ['input[name="user"]', 'input[name="username"]',
                        'input[id="username"]', '#user']:
                if page.locator(sel).count():
                    page.fill(sel, cb_user)
                    break

            for sel in ['input[name="password"]', 'input[type="password"]']:
                if page.locator(sel).count():
                    page.fill(sel, cb_pass)
                    break

            # Submit
            for sel in ['button[type="submit"]', 'input[type="submit"]',
                        'button:has-text("Login")', 'button:has-text("Sign in")']:
                if page.locator(sel).count():
                    page.click(sel)
                    break

            page.wait_for_load_state("networkidle", timeout=20_000)

            # ── 3. Click + / New Issue button ─────────────────────────
            # Try tooltip/title attributes first (most reliable in CB)
            plus_selectors = [
                '[data-original-title="New Issue"]',
                '[title="New Issue"]',
                'a[title="New Issue"]',
                'button[title="New Issue"]',
                'a:has-text("New Issue")',
                'button:has-text("New Issue")',
                '.new-issue-btn',
                '#new-issue',
                'a.btn:has-text("+")',
                'button:has-text("+")',
            ]
            clicked = False
            for sel in plus_selectors:
                loc = page.locator(sel)
                if loc.count() > 0:
                    loc.first.scroll_into_view_if_needed()
                    loc.first.click()
                    clicked = True
                    break

            if not clicked:
                # JS fallback: click the first element whose text is exactly "+"
                page.evaluate("""
                    () => {
                        const all = Array.from(document.querySelectorAll('a, button'));
                        const btn = all.find(el =>
                            el.textContent.trim() === '+' ||
                            (el.getAttribute('title') || '').toLowerCase().includes('new issue') ||
                            (el.getAttribute('data-original-title') || '').toLowerCase().includes('new issue')
                        );
                        if (btn) btn.click();
                    }
                """)

            page.wait_for_load_state("networkidle", timeout=20_000)

            # ── 4. Wait for user to fill form and click Save ──────────
            # We wait up to 5 minutes for the URL to change after Save
            saved_url = page.url
            for _ in range(300):           # 300 × 1 s = 5 min
                page.wait_for_timeout(1000)
                current = page.url
                if current != saved_url and "issue" in current.lower():
                    saved_url = current
                    break

            page.wait_for_load_state("networkidle", timeout=15_000)

            # ── 5. Scrape issue details ───────────────────────────────
            issue_id    = ""
            description = ""
            issue_link  = page.url

            # Try common CB detail-page selectors
            for sel in ['[data-testid="issue-id"]', '.issue-id',
                        '.tracker-item-id', 'h1.issueId',
                        '.issueTitle span.id', '.summary-id']:
                if page.locator(sel).count():
                    issue_id = page.locator(sel).first.inner_text().strip()
                    break

            # Fallback: extract ID from URL  e.g. /issue/12345
            if not issue_id:
                import re
                m = re.search(r'/(?:issue|item)/(\d+)', page.url)
                if m:
                    issue_id = m.group(1)

            for sel in ['[data-testid="issue-description"]',
                        '.issue-description', '.description-content',
                        '.summary', 'textarea[name="description"]',
                        '#description']:
                if page.locator(sel).count():
                    description = page.locator(sel).first.inner_text().strip()
                    break

            browser.close()

            callback({
                "id":          issue_id or "N/A",
                "description": description or "(no description captured)",
                "link":        issue_link,
                "error":       None,
            })

    except Exception as exc:
        callback({"error": str(exc)})


def launch_cb_create(cb_url, cb_user, cb_pass, callback):
    """Runs Playwright in a background thread so the tkinter UI stays responsive."""
    if not cb_url:
        callback({"error": "CB_URL is not set in .env"})
        return
    t = threading.Thread(
        target=_run_playwright_create,
        args=(cb_url, cb_user, cb_pass, callback),
        daemon=True,
    )
    t.start()


# ── Playwright: Modify (edit) an existing defect in CodeBeamer ────────────────
def _run_playwright_modify(ticket_url, cb_user, cb_pass, callback):
    """
    Opens the given ticket URL in a headed browser.
    - If not logged in, logs in with cb_user/cb_pass first.
    - Clicks the Edit button.
    - Waits for the user to make changes and click Save.
    - Calls callback({"error": None}) on success or callback({"error": "..."}) on failure.
    The browser stays open until Save is detected (URL change or edit form disappears).
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        callback({"error": "playwright not installed.\nRun: pip install playwright && playwright install chromium"})
        return

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=False,
                slow_mo=200,
                args=["--start-maximized"],
            )
            ctx  = browser.new_context(no_viewport=True)
            page = ctx.new_page()

            # 1. Navigate to ticket URL
            page.goto(ticket_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_load_state("networkidle", timeout=20_000)

            # 2. Check if login is required
            if page.locator('input[type="password"]').count() > 0:
                for sel in ['input[name="user"]', 'input[name="username"]',
                            'input[id="username"]', '#user']:
                    if page.locator(sel).count():
                        page.fill(sel, cb_user)
                        break

                for sel in ['input[name="password"]', 'input[type="password"]']:
                    if page.locator(sel).count():
                        page.fill(sel, cb_pass)
                        break

                for sel in ['button[type="submit"]', 'input[type="submit"]',
                            'button:has-text("Login")', 'button:has-text("Sign in")']:
                    if page.locator(sel).count():
                        page.click(sel)
                        break

                page.wait_for_load_state("networkidle", timeout=20_000)
                # After login, go back to ticket
                page.goto(ticket_url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_load_state("networkidle", timeout=20_000)

            # 3. Click Edit button
            # CB uses title="Edit (Alt + e)" or data-original-title="Edit (Alt + e)"
            # so we match any element whose title/text STARTS WITH "Edit"
            clicked = page.evaluate("""
                () => {
                    const candidates = Array.from(
                        document.querySelectorAll('a, button, input[type="button"], [role="button"]')
                    );
                    const btn = candidates.find(el => {
                        const title  = (el.getAttribute('title') || '').trim();
                        const dtitle = (el.getAttribute('data-original-title') || '').trim();
                        const text   = (el.textContent || '').trim();
                        return title.startsWith('Edit') ||
                               dtitle.startsWith('Edit') ||
                               text === 'Edit';
                    });
                    if (btn) { btn.click(); return true; }
                    return false;
                }
            """)

            if not clicked:
                # Final fallback: use the keyboard shortcut Alt+E that CB advertises
                page.keyboard.press("Alt+e")

            page.wait_for_load_state("networkidle", timeout=15_000)

            # 4. Wait for Save — detect Save button disappearing (user clicked Save)
            pre_save_url = page.url
            for tick in range(600):           # up to 10 minutes
                page.wait_for_timeout(1000)
                save_gone = page.locator(
                    'input[type="submit"][value*="Save"], button:has-text("Save")'
                ).count() == 0

                if save_gone and tick > 3:
                    break

            final_url = page.url
            browser.close()
            callback({"error": None, "link": final_url})

    except Exception as exc:
        callback({"error": str(exc)})


def launch_cb_modify(ticket_url, cb_user, cb_pass, callback):
    """Runs Playwright modify in a background thread."""
    if not ticket_url:
        callback({"error": "Please enter a ticket URL."})
        return
    t = threading.Thread(
        target=_run_playwright_modify,
        args=(ticket_url, cb_user, cb_pass, callback),
        daemon=True,
    )
    t.start()


# ── Helpers ───────────────────────────────────────────────────────────────────
def zoomed(root):
    try:
        root.state("zoomed")
    except Exception:
        try:
            root.attributes("-zoomed", True)
        except Exception:
            root.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")

def styled_entry(parent, textvariable=None, show="", width=30):
    e = tk.Entry(parent, textvariable=textvariable, show=show, width=width,
                 bg="#f9fafb", fg=TEXT_PRI, font=("Segoe UI", 11),
                 relief="flat", highlightbackground=BORDER, highlightthickness=1,
                 insertbackground=TEXT_PRI)
    return e

def nav_button(parent, text, command, active=False):
    bg = BRAND if active else SIDEBAR_BG
    btn = tk.Button(parent, text=text, bg=bg, fg="#ffffff",
                    font=("Segoe UI", 11), relief="flat",
                    anchor="w", padx=20, pady=12, cursor="hand2",
                    activebackground=SIDEBAR2, activeforeground="#fff",
                    command=command)
    btn.pack(fill="x", padx=8, pady=2)
    def enter(e):
        if btn.cget("bg") != BRAND:
            btn.config(bg=SIDEBAR2)
    def leave(e):
        if btn.cget("bg") != BRAND:
            btn.config(bg=SIDEBAR_BG)
    btn.bind("<Enter>", enter)
    btn.bind("<Leave>", leave)
    return btn

def scrollable_frame(parent):
    """Returns (outer_frame, inner_frame). outer_frame fills parent; inner_frame is scrollable content."""
    outer = tk.Frame(parent, bg=BG)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(0, weight=1)

    canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
    vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")

    inner = tk.Frame(canvas, bg=BG)
    wid = canvas.create_window((0, 0), window=inner, anchor="nw")

    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
    canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))
    canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
    canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))
    return inner

def icon_bg(color):
    return ICON_BG.get(color, "#f0f2f5")

# ── Single persistent root window ─────────────────────────────────────────────
_ROOT = None

def get_root():
    global _ROOT
    if _ROOT is None:
        _ROOT = tk.Tk()
    return _ROOT

def switch_to(page_class, *args):
    root = get_root()
    for w in root.winfo_children():
        w.destroy()
    root.configure(bg=BG)
    page_class(root, *args)

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 1 — LOGIN  (full screen, two-column)
# ══════════════════════════════════════════════════════════════════════════════
class LoginWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Defect Tracker — Login")
        root.configure(bg=SIDEBAR_BG)
        root.resizable(True, True)
        zoomed(root)
        self._build()

    def _build(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        # ── Left branding panel (fills full height) ────────────────────
        left = tk.Frame(root, bg=SIDEBAR_BG)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        center = tk.Frame(left, bg=SIDEBAR_BG)
        center.grid(row=0, column=0)  # stays centred via grid weight

        logo_c = tk.Canvas(center, width=100, height=100,
                            bg=SIDEBAR_BG, highlightthickness=0)
        logo_c.pack(pady=(0, 24))
        logo_c.create_oval(4, 4, 96, 96, fill=BRAND, outline="")
        logo_c.create_text(50, 50, text="DT", fill="white",
                            font=("Segoe UI", 30, "bold"))

        tk.Label(center, text="Defect Tracker",
                 bg=SIDEBAR_BG, fg="#ffffff",
                 font=("Segoe UI", 30, "bold")).pack()
        tk.Label(center, text="Track. Fix. Ship.",
                 bg=SIDEBAR_BG, fg=TEXT_SEC,
                 font=("Segoe UI", 14)).pack(pady=(8, 48))

        for txt in ["Multi-project support",
                    "Real-time defect tracking",
                    "Priority management",
                    "Analytics & reporting"]:
            pill = tk.Frame(center, bg=SIDEBAR2,
                            highlightbackground="#2d3f5a", highlightthickness=1)
            pill.pack(fill="x", pady=6, ipady=10, ipadx=20)
            tk.Label(pill, text="✓", bg=SIDEBAR2,
                     fg=BRAND, font=("Segoe UI", 13, "bold")).pack(side="left", padx=(14, 10))
            tk.Label(pill, text=txt, bg=SIDEBAR2,
                     fg="#c9d3e0", font=("Segoe UI", 12)).pack(side="left")

        # vertical divider
        tk.Frame(root, bg="#2d3f5a", width=1).grid(row=0, column=0, sticky="nse")

        # ── Right login form (fills full height) ──────────────────────
        right = tk.Frame(root, bg="#131f30")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        form = tk.Frame(right, bg="#131f30")
        form.grid(row=0, column=0)   # centred by grid weight

        tk.Label(form, text="Welcome back",
                 bg="#131f30", fg="#ffffff",
                 font=("Segoe UI", 28, "bold")).pack(anchor="w")
        tk.Label(form, text="Sign in to your account",
                 bg="#131f30", fg=TEXT_SEC,
                 font=("Segoe UI", 13)).pack(anchor="w", pady=(6, 36))

        # Username
        tk.Label(form, text="Username",
                 bg="#131f30", fg="#c9d3e0",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 6))
        self._user_var = tk.StringVar()
        user_f = tk.Frame(form, bg="#1e2f47",
                          highlightbackground="#2d3f5a", highlightthickness=1)
        user_f.pack(fill="x", pady=(0, 22))
        user_e = tk.Entry(user_f, textvariable=self._user_var,
                          bg="#1e2f47", fg="#ffffff", insertbackground="#ffffff",
                          font=("Segoe UI", 13), relief="flat", bd=0, width=34)
        user_e.pack(fill="x", padx=16, pady=13)
        user_e.bind("<FocusIn>",  lambda e: user_f.config(highlightbackground=BRAND))
        user_e.bind("<FocusOut>", lambda e: user_f.config(highlightbackground="#2d3f5a"))

        # Password
        tk.Label(form, text="Password",
                 bg="#131f30", fg="#c9d3e0",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 6))
        self._pwd_var = tk.StringVar()
        pwd_f = tk.Frame(form, bg="#1e2f47",
                         highlightbackground="#2d3f5a", highlightthickness=1)
        pwd_f.pack(fill="x", pady=(0, 36))
        pwd_e = tk.Entry(pwd_f, textvariable=self._pwd_var, show="●",
                         bg="#1e2f47", fg="#ffffff", insertbackground="#ffffff",
                         font=("Segoe UI", 13), relief="flat", bd=0, width=34)
        pwd_e.pack(fill="x", padx=16, pady=13)
        pwd_e.bind("<FocusIn>",  lambda e: pwd_f.config(highlightbackground=BRAND))
        pwd_e.bind("<FocusOut>", lambda e: pwd_f.config(highlightbackground="#2d3f5a"))

        btn = tk.Button(form, text="Sign In  →",
                        bg=BRAND, fg="#ffffff",
                        font=("Segoe UI", 14, "bold"), relief="flat", cursor="hand2",
                        activebackground=BRAND_DARK, activeforeground="#fff",
                        padx=20, pady=15, command=self._login)
        btn.pack(fill="x")
        btn.bind("<Enter>", lambda e: btn.config(bg=BRAND_DARK))
        btn.bind("<Leave>", lambda e: btn.config(bg=BRAND))

        self._err_lbl = tk.Label(form, text="",
                                  bg="#131f30", fg="#f87171",
                                  font=("Segoe UI", 12))
        self._err_lbl.pack(pady=(18, 0))

        # hint
        tk.Label(form, text="Default: admin / admin123",
                 bg="#131f30", fg="#4a5e7a",
                 font=("Segoe UI", 10)).pack(pady=(12, 0))

        root.bind("<Return>", lambda e: self._login())

    def _login(self):
        u = self._user_var.get().strip()
        p = self._pwd_var.get().strip()
        if u == USERNAME and p == PASSWORD:
            self.root.after(0, lambda: switch_to(ProjectPage))
        else:
            self._err_lbl.config(text="✗  Invalid username or password")
            self._user_var.set("")
            self._pwd_var.set("")


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 2 — PROJECT SELECTION  (full screen)
# ══════════════════════════════════════════════════════════════════════════════
class ProjectPage:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Defect Tracker — Select Project")
        root.configure(bg=BG)
        root.resizable(True, True)
        zoomed(root)
        self._build()

    def _build(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=0)
        root.rowconfigure(1, weight=1)   # body row fills all remaining space

        # ── Navbar ─────────────────────────────────────────────────────
        nav = tk.Frame(root, bg=SIDEBAR_BG, height=64)
        nav.grid(row=0, column=0, sticky="ew")
        nav.pack_propagate(False)

        logo_f = tk.Frame(nav, bg=SIDEBAR_BG)
        logo_f.pack(side="left", padx=28, pady=16)
        lc = tk.Canvas(logo_f, width=34, height=34, bg=SIDEBAR_BG, highlightthickness=0)
        lc.pack(side="left")
        lc.create_oval(2, 2, 32, 32, fill=BRAND, outline="")
        lc.create_text(17, 17, text="DT", fill="white", font=("Segoe UI", 11, "bold"))
        tk.Label(logo_f, text="  Defect Tracker",
                 bg=SIDEBAR_BG, fg="#fff", font=("Segoe UI", 14, "bold")).pack(side="left")

        right_nav = tk.Frame(nav, bg=SIDEBAR_BG)
        right_nav.pack(side="right", padx=28, pady=16)
        tk.Button(right_nav, text="Logout",
                  bg=SIDEBAR2, fg=TEXT_SEC,
                  font=("Segoe UI", 10), relief="flat", cursor="hand2",
                  padx=14, pady=6,
                  command=self._logout).pack(side="right", padx=(10, 0))
        av = tk.Canvas(right_nav, width=34, height=34, bg=SIDEBAR_BG, highlightthickness=0)
        av.pack(side="right")
        av.create_oval(2, 2, 32, 32, fill=BRAND, outline="")
        av.create_text(17, 17, text="AD", fill="white", font=("Segoe UI", 10, "bold"))
        tk.Label(right_nav, text="admin",
                 bg=SIDEBAR_BG, fg="#c9d3e0", font=("Segoe UI", 12)).pack(side="right", padx=10)

        # ── Body fills ALL remaining height and width — no scrollbar ──
        self._body = tk.Frame(root, bg=BG)
        self._body.grid(row=1, column=0, sticky="nsew")
        self._body.columnconfigure(0, weight=1)
        self._body.rowconfigure(0, weight=0)   # header section fixed
        self._body.rowconfigure(1, weight=1)   # cards row expands

        self._render_cards()

    def _render_cards(self):
        for w in self._body.winfo_children():
            w.destroy()

        # ── Header section (fixed height, row 0) ──────────────────────
        hdr_section = tk.Frame(self._body, bg=BG)
        hdr_section.grid(row=0, column=0, sticky="ew", padx=40, pady=(30, 0))

        tk.Label(hdr_section, text="Select a Project",
                 bg=BG, fg=TEXT_PRI,
                 font=("Segoe UI", 32, "bold")).pack(anchor="w")
        tk.Label(hdr_section,
                 text="Choose a project below to manage its defects, or create a new one.",
                 bg=BG, fg=TEXT_SEC,
                 font=("Segoe UI", 13)).pack(anchor="w", pady=(6, 0))

        tk.Frame(hdr_section, bg=BORDER, height=1).pack(fill="x", pady=(22, 0))
        tk.Label(hdr_section, text="Available Projects",
                 bg=BG, fg=TEXT_MUT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 0))

        # ── Cards grid (expands, row 1) ────────────────────────────────
        cards_frame = tk.Frame(self._body, bg=BG)
        cards_frame.grid(row=1, column=0, sticky="nsew", padx=24, pady=(12, 24))

        all_projects = list(APP_DATA["projects"])
        total = len(all_projects)
        cols = total + 1          # one column per project + add-new card
        for c in range(cols):
            cards_frame.columnconfigure(c, weight=1, uniform="col", minsize=180)
        cards_frame.rowconfigure(0, weight=1)

        for i, proj in enumerate(all_projects):
            self._project_card(cards_frame, proj, 0, i)

        self._add_card(cards_frame, 0, total)

    def _project_card(self, parent, proj, row_i, col_i):
        name  = proj["name"]
        color = proj["color"]
        icon  = proj["icon"]
        desc  = proj["desc"]

        proj_defects = [d for d in APP_DATA["defects"] if d.get("project") == name]
        open_c = sum(1 for d in proj_defects if d.get("status") == "Open")

        card = tk.Frame(parent, bg=SURFACE,
                        highlightbackground=BORDER, highlightthickness=1,
                        cursor="hand2")
        card.grid(row=row_i, column=col_i, padx=12, pady=12, sticky="nsew")

        # Accent top bar
        tk.Frame(card, bg=color, height=5).pack(fill="x")

        body = tk.Frame(card, bg=SURFACE)
        body.pack(padx=24, pady=24, fill="both", expand=True)

        # Icon
        ic_bg_c = icon_bg(color)
        ic = tk.Canvas(body, width=54, height=54, bg=SURFACE, highlightthickness=0)
        ic.pack(anchor="w", pady=(0, 14))
        ic.create_oval(2, 2, 52, 52, fill=ic_bg_c, outline=color, width=1)
        ic.create_text(27, 27, text=icon, fill=color, font=("Segoe UI", 20))

        tk.Label(body, text=f"Project  {name.upper()}",
                 bg=SURFACE, fg=TEXT_PRI,
                 font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(body, text=desc,
                 bg=SURFACE, fg=TEXT_SEC,
                 font=("Segoe UI", 10), justify="left",
                 wraplength=190).pack(anchor="w", pady=(4, 16))

        stats = tk.Frame(body, bg="#f4f5f7",
                         highlightbackground=BORDER, highlightthickness=1)
        stats.pack(fill="x", pady=(0, 16), ipadx=10, ipady=8)
        tk.Label(stats,
                 text=f"{len(proj_defects)} defects  •  {open_c} open",
                 bg="#f4f5f7", fg=TEXT_SEC,
                 font=("Segoe UI", 10)).pack()

        open_btn = tk.Button(body, text="Open Project  →",
                             bg=color, fg="#ffffff",
                             font=("Segoe UI", 10, "bold"),
                             relief="flat", cursor="hand2",
                             activebackground=BRAND_DARK,
                             pady=10,
                             command=lambda n=name: self._open_project(n))
        open_btn.pack(fill="x")

        def enter(e, b=open_btn): b.config(bg=BRAND_DARK)
        def leave(e, b=open_btn, c=color): b.config(bg=c)
        open_btn.bind("<Enter>", enter)
        open_btn.bind("<Leave>", leave)

        for w in [card, body, stats]:
            w.bind("<Button-1>", lambda e, n=name: self._open_project(n))

    def _add_card(self, parent, row_i, col_i):
        DASH = "#c8cdd4"
        card = tk.Frame(parent, bg=SURFACE,
                        highlightbackground=DASH, highlightthickness=1,
                        cursor="hand2")
        card.grid(row=row_i, column=col_i, padx=12, pady=12, sticky="nsew")

        tk.Frame(card, bg=DASH, height=5).pack(fill="x")
        body = tk.Frame(card, bg=SURFACE)
        body.pack(padx=24, pady=24, fill="both", expand=True)

        ic = tk.Canvas(body, width=54, height=54, bg=SURFACE, highlightthickness=0)
        ic.pack(anchor="w", pady=(0, 14))
        ic.create_oval(2, 2, 52, 52, fill="#f0f2f5", outline=DASH, width=1)
        ic.create_text(27, 27, text="+", fill=TEXT_MUT, font=("Segoe UI", 24))

        tk.Label(body, text="Add New Project",
                 bg=SURFACE, fg=TEXT_SEC,
                 font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(body, text="Creating & Modify Bug",
                 bg=SURFACE, fg=TEXT_MUT,
                 font=("Segoe UI", 10), justify="left").pack(anchor="w", pady=(4, 16))

        spacer = tk.Frame(body, bg="#f4f5f7",
                          highlightbackground=DASH, highlightthickness=1)
        spacer.pack(fill="x", pady=(0, 16), ipadx=10, ipady=8)
        tk.Label(spacer, text="New workspace",
                 bg="#f4f5f7", fg=TEXT_MUT, font=("Segoe UI", 10)).pack()

        add_btn = tk.Button(body, text="+ Create Project",
                            bg=SIDEBAR2, fg="#c9d3e0",
                            font=("Segoe UI", 10, "bold"),
                            relief="flat", cursor="hand2",
                            pady=10, command=self._show_add_dialog)
        add_btn.pack(fill="x")
        add_btn.bind("<Enter>", lambda e: add_btn.config(bg=SIDEBAR_BG))
        add_btn.bind("<Leave>", lambda e: add_btn.config(bg=SIDEBAR2))

        for w in [card, body]:
            w.bind("<Button-1>", lambda e: self._show_add_dialog())

    def _show_add_dialog(self):
        DLG_W, DLG_H = 520, 480
        dlg = tk.Toplevel(self.root)
        dlg.title("Add New Project")
        dlg.configure(bg=SURFACE)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width()  - DLG_W) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - DLG_H) // 2
        dlg.geometry(f"{DLG_W}x{DLG_H}+{x}+{y}")

        # ── Layout: accent bar → header → divider → scrollable body → fixed footer ──
        # This ensures the footer/buttons are ALWAYS visible regardless of content height.

        # Accent top bar
        tk.Frame(dlg, bg=BRAND, height=5).pack(fill="x", side="top")

        # Fixed footer (packed from bottom BEFORE the scrollable body so it's always visible)
        footer = tk.Frame(dlg, bg="#f8f9fa",
                          highlightbackground=BORDER, highlightthickness=1)
        footer.pack(fill="x", side="bottom")

        btn_row = tk.Frame(footer, bg="#f8f9fa")
        btn_row.pack(padx=28, pady=14, anchor="e")

        # Dialog header (fixed, below accent bar)
        hdr = tk.Frame(dlg, bg=SURFACE)
        hdr.pack(fill="x", padx=28, pady=(18, 0), side="top")
        ic = tk.Canvas(hdr, width=40, height=40, bg=SURFACE, highlightthickness=0)
        ic.pack(side="left", padx=(0, 14))
        ic.create_oval(2, 2, 38, 38, fill="#f5e6ea", outline=BRAND, width=1)
        ic.create_text(20, 20, text="+", fill=BRAND, font=("Segoe UI", 18, "bold"))
        title_grp = tk.Frame(hdr, bg=SURFACE)
        title_grp.pack(side="left")
        tk.Label(title_grp, text="Create New Project",
                 bg=SURFACE, fg=TEXT_PRI,
                 font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(title_grp, text="Add a new project to your workspace",
                 bg=SURFACE, fg=TEXT_SEC,
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))

        tk.Frame(dlg, bg=BORDER, height=1).pack(fill="x", padx=28, pady=(14, 0), side="top")

        # Scrollable form body (fills remaining space between header and footer)
        scroll_wrap = tk.Frame(dlg, bg=SURFACE)
        scroll_wrap.pack(fill="both", expand=True, side="top")
        scroll_wrap.columnconfigure(0, weight=1)
        scroll_wrap.rowconfigure(0, weight=1)

        body_canvas = tk.Canvas(scroll_wrap, bg=SURFACE, highlightthickness=0)
        body_vsb = ttk.Scrollbar(scroll_wrap, orient="vertical", command=body_canvas.yview)
        body_canvas.configure(yscrollcommand=body_vsb.set)
        body_canvas.grid(row=0, column=0, sticky="nsew")
        body_vsb.grid(row=0, column=1, sticky="ns")

        body = tk.Frame(body_canvas, bg=SURFACE)
        body_wid = body_canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: body_canvas.configure(scrollregion=body_canvas.bbox("all")))
        body_canvas.bind("<Configure>", lambda e: body_canvas.itemconfig(body_wid, width=e.width))
        body_canvas.bind("<MouseWheel>", lambda e: body_canvas.yview_scroll(-1*(e.delta//120), "units"))
        body_canvas.bind("<Button-4>", lambda e: body_canvas.yview_scroll(-1, "units"))
        body_canvas.bind("<Button-5>", lambda e: body_canvas.yview_scroll(1, "units"))

        # ── Form fields inside scrollable body ──────────────────────────
        form = tk.Frame(body, bg=SURFACE)
        form.pack(padx=28, pady=16, fill="x")

        # Project Name
        tk.Label(form, text="Project Name *",
                 bg=SURFACE, fg=TEXT_PRI,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 5))
        name_var = tk.StringVar()
        name_f = tk.Frame(form, bg="#f9fafb",
                          highlightbackground=BORDER, highlightthickness=1)
        name_f.pack(fill="x", pady=(0, 16))
        name_e = tk.Entry(name_f, textvariable=name_var,
                          bg="#f9fafb", fg=TEXT_PRI, insertbackground=TEXT_PRI,
                          font=("Segoe UI", 12), relief="flat", bd=0)
        name_e.pack(fill="x", padx=12, pady=10)
        name_e.bind("<FocusIn>",  lambda e: name_f.config(highlightbackground=BRAND))
        name_e.bind("<FocusOut>", lambda e: name_f.config(highlightbackground=BORDER))
        name_e.focus_set()

        # Description
        tk.Label(form, text="Description",
                 bg=SURFACE, fg=TEXT_PRI,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 5))
        desc_wrap = tk.Frame(form, bg="#f9fafb",
                             highlightbackground=BORDER, highlightthickness=1)
        desc_wrap.pack(fill="x", pady=(0, 16))
        desc_box = tk.Text(desc_wrap, height=3, bg="#f9fafb", fg=TEXT_PRI,
                           font=("Segoe UI", 11), relief="flat", bd=0,
                           insertbackground=TEXT_PRI)
        desc_box.pack(fill="x", padx=10, pady=8)
        desc_box.bind("<FocusIn>",  lambda e: desc_wrap.config(highlightbackground=BRAND))
        desc_box.bind("<FocusOut>", lambda e: desc_wrap.config(highlightbackground=BORDER))

        # Accent Color
        tk.Label(form, text="Accent Color",
                 bg=SURFACE, fg=TEXT_PRI,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 8))

        color_var = tk.StringVar(value=BRAND)
        color_row = tk.Frame(form, bg=SURFACE)
        color_row.pack(anchor="w", pady=(0, 4))

        COLOR_NAMES = {BRAND: "Red", BLUE: "Blue", PURPLE: "Purple",
                       GREEN: "Green", ORANGE: "Orange", "#0891b2": "Teal"}
        palette = [BRAND, BLUE, PURPLE, GREEN, ORANGE, "#0891b2"]
        btn_refs = []
        color_lbl = tk.Label(form, text=f"Selected: {COLOR_NAMES[BRAND]}",
                             bg=SURFACE, fg=TEXT_MUT,
                             font=("Segoe UI", 9))
        color_lbl.pack(anchor="w", pady=(0, 4))

        def pick(c):
            color_var.set(c)
            color_lbl.config(text=f"Selected: {COLOR_NAMES.get(c, c)}")
            for b in btn_refs:
                chosen = b.cget("bg") == c
                b.config(relief="sunken" if chosen else "flat",
                         bd=3 if chosen else 1,
                         highlightbackground="#333" if chosen else b.cget("bg"),
                         highlightthickness=2 if chosen else 0)

        for col in palette:
            cb = tk.Button(color_row, bg=col, width=4, height=2,
                           relief="flat", bd=1, cursor="hand2",
                           highlightthickness=0,
                           command=lambda c=col: pick(c))
            cb.pack(side="left", padx=(0, 8))
            btn_refs.append(cb)
        # Mark first as selected
        btn_refs[0].config(relief="sunken", bd=3, highlightbackground="#333", highlightthickness=2)

        def do_create():
            n = name_var.get().strip()
            if not n:
                messagebox.showerror("Validation", "Project name is required.", parent=dlg)
                name_f.config(highlightbackground=RED_C)
                return
            if n.lower() in [p["name"].lower() for p in APP_DATA["projects"]]:
                messagebox.showerror("Duplicate", f'Project "{n}" already exists.', parent=dlg)
                name_f.config(highlightbackground=RED_C)
                return
            raw_desc = desc_box.get("1.0", "end").strip()
            APP_DATA["projects"].append({
                "name":  n,
                "color": color_var.get(),
                "icon":  "◇",
                "desc":  raw_desc or "Custom project",
            })
            save_data(APP_DATA)
            dlg.destroy()
            self._render_cards()

        # ── Footer buttons (always visible, rendered earlier via side="bottom") ──
        tk.Button(btn_row, text="Cancel",
                  bg=SURFACE, fg=TEXT_SEC,
                  font=("Segoe UI", 10), relief="flat",
                  cursor="hand2", padx=18, pady=8,
                  highlightbackground=BORDER, highlightthickness=1,
                  command=dlg.destroy).pack(side="left", padx=(0, 10))

        create_btn = tk.Button(btn_row, text="  ✚  Create Project  ",
                               bg=BRAND, fg="#fff",
                               font=("Segoe UI", 11, "bold"),
                               relief="flat", cursor="hand2",
                               padx=18, pady=8, command=do_create)
        create_btn.pack(side="left")
        create_btn.bind("<Enter>", lambda e: create_btn.config(bg=BRAND_DARK))
        create_btn.bind("<Leave>", lambda e: create_btn.config(bg=BRAND))

        dlg.bind("<Return>", lambda e: do_create())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    def _open_project(self, project_name):
        self.root.after(0, lambda: switch_to(DashboardWindow, project_name))

    def _logout(self):
        if messagebox.askyesno("Logout", "Are you sure you want to logout?"):
            self.root.after(0, lambda: switch_to(LoginWindow))


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 3 — DEFECT DASHBOARD  (full screen, sidebar + content)
# ══════════════════════════════════════════════════════════════════════════════

class DashboardWindow:

    def __init__(self, root: tk.Tk, project: str):

        self.root = root
        self.project = project

        root.title(f"Defect Tracker — Project {project.upper()}")
        root.configure(bg=BG)
        root.resizable(True, True)

        zoomed(root)

        proj_meta = next(
            (p for p in APP_DATA["projects"] if p["name"] == project),
            {}
        )

        self._color = proj_meta.get("color", BRAND)

        self._build()

        self._page_create()

    # ════════════════════════════════════════════════════════════
    # BUILD UI
    # ════════════════════════════════════════════════════════════
    def _build(self):

        root = self.root

        root.columnconfigure(0, weight=1)

        root.rowconfigure(0, weight=0)
        root.rowconfigure(1, weight=1)

        # ───────────────────────────────────────────────────────
        # NAVBAR
        # ───────────────────────────────────────────────────────
        nav = tk.Frame(
            root,
            bg=SIDEBAR_BG,
            height=64
        )

        nav.grid(
            row=0,
            column=0,
            sticky="ew"
        )

        nav.pack_propagate(False)

        # LEFT LOGO SECTION
        logo_f = tk.Frame(nav, bg=SIDEBAR_BG)
        logo_f.pack(side="left", padx=28, pady=16)

        lc = tk.Canvas(
            logo_f,
            width=34,
            height=34,
            bg=SIDEBAR_BG,
            highlightthickness=0
        )

        lc.pack(side="left")

        lc.create_oval(
            2, 2, 32, 32,
            fill=self._color,
            outline=""
        )

        lc.create_text(
            17,
            17,
            text="DT",
            fill="white",
            font=("Segoe UI", 11, "bold")
        )

        tk.Label(
            logo_f,
            text=f"  Project {self.project.upper()}",
            bg=SIDEBAR_BG,
            fg="#ffffff",
            font=("Segoe UI", 14, "bold")
        ).pack(side="left")

        # ───────────────────────────────────────────────────────
        # RIGHT NAV BUTTONS
        # ───────────────────────────────────────────────────────
        right_nav = tk.Frame(
            nav,
            bg=SIDEBAR_BG
        )

        # TOUCH RIGHT END
        right_nav.pack(
            side="right",
            padx=0,
            pady=12
        )

        # LOGOUT BUTTON
        tk.Button(
            right_nav,
            text="Logout",
            bg=SIDEBAR2,
            fg=TEXT_SEC,
            font=("Segoe UI", 10),
            relief="flat",
            cursor="hand2",
            padx=14,
            pady=6,
            command=self._logout
        ).pack(
            side="right",
            padx=(12, 20)
        )

        # ALL PROJECTS BUTTON
        tk.Button(
            right_nav,
            text="← All Projects",
            bg=SIDEBAR2,
            fg="#c9d3e0",
            font=("Segoe UI", 10),
            relief="flat",
            cursor="hand2",
            padx=14,
            pady=6,
            command=self._go_back
        ).pack(
            side="right",
            padx=(0, 10)
        )

        # ───────────────────────────────────────────────────────
        # MAIN LAYOUT
        # ───────────────────────────────────────────────────────
        main_frame = tk.Frame(
            root,
            bg=BG
        )

        main_frame.grid(
            row=1,
            column=0,
            sticky="nsew"
        )

        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        # ───────────────────────────────────────────────────────
        # SIDEBAR
        # ───────────────────────────────────────────────────────
        sidebar = tk.Frame(
            main_frame,
            bg=SIDEBAR_BG,
            width=220
        )

        sidebar.grid(
            row=0,
            column=0,
            sticky="nsew"
        )

        sidebar.pack_propagate(False)

        tk.Label(
            sidebar,
            text="NAVIGATION",
            bg=SIDEBAR_BG,
            fg=TEXT_MUT,
            font=("Segoe UI", 9, "bold")
        ).pack(
            anchor="w",
            padx=22,
            pady=(28, 12)
        )

        # ───────────────────────────────────────────────────────
        # NAV BUTTONS
        # ───────────────────────────────────────────────────────
        self._nav_btns = {}

        pages = [
            ("create",  "✚  Create Defect"),
            ("modify",  "✎  Modify Defect"),
            ("view",    "☰  View Defects"),
            ("results", "▦  Results"),
        ]

        for key, label in pages:

            btn = nav_button(
                sidebar,
                label,
                command=lambda k=key: self._switch_page(k),
                active=(key == "create")
            )

            self._nav_btns[key] = btn

        tk.Frame(
            sidebar,
            bg=SIDEBAR2,
            height=1
        ).pack(
            fill="x",
            padx=18,
            pady=24
        )

        # ───────────────────────────────────────────────────────
        # PROJECT INFO
        # ───────────────────────────────────────────────────────
        proj_meta = next(
            (p for p in APP_DATA["projects"]
             if p["name"] == self.project),
            {}
        )

        ic_bg_c = icon_bg(self._color)

        ic2 = tk.Canvas(
            sidebar,
            width=44,
            height=44,
            bg=SIDEBAR_BG,
            highlightthickness=0
        )

        ic2.pack(
            padx=22,
            anchor="w"
        )

        ic2.create_oval(
            2, 2, 42, 42,
            fill=ic_bg_c,
            outline=self._color,
            width=1
        )

        ic2.create_text(
            22,
            22,
            text=proj_meta.get("icon", "◈"),
            fill=self._color,
            font=("Segoe UI", 16)
        )

        tk.Label(
            sidebar,
            text=f"Project {self.project.upper()}",
            bg=SIDEBAR_BG,
            fg="#c9d3e0",
            font=("Segoe UI", 11, "bold")
        ).pack(
            anchor="w",
            padx=22,
            pady=(8, 2)
        )

        self._count_lbl = tk.Label(
            sidebar,
            text=f"{len(self._proj_defects())} defect(s)",
            bg=SIDEBAR_BG,
            fg=TEXT_MUT,
            font=("Segoe UI", 10)
        )

        self._count_lbl.pack(
            anchor="w",
            padx=22
        )

        # ───────────────────────────────────────────────────────
        # MAIN CONTENT AREA
        # ───────────────────────────────────────────────────────
        self._main = tk.Frame(
            main_frame,
            bg=BG
        )

        self._main.grid(
            row=0,
            column=1,
            sticky="nsew"
        )

        self._main.columnconfigure(0, weight=1)

        self._main.rowconfigure(0, weight=0)
        self._main.rowconfigure(1, weight=1)

    # ════════════════════════════════════════════════════════════
    # SWITCH PAGE
    # ════════════════════════════════════════════════════════════
    def _switch_page(self, key):

        for w in self._main.winfo_children():
            w.destroy()

        for k, btn in self._nav_btns.items():

            btn.config(
                bg=BRAND if k == key else SIDEBAR_BG
            )

        dispatch = {
            "create":  self._page_create,
            "modify":  self._page_modify,
            "view":    self._page_view,
            "results": self._page_results,
        }

        dispatch[key]()

    # ════════════════════════════════════════════════════════════
    # PROJECT DEFECTS
    # ════════════════════════════════════════════════════════════
    def _proj_defects(self):

        return [
            d for d in APP_DATA["defects"]
            if d.get("project") == self.project
        ]

    # ════════════════════════════════════════════════════════════
    # TOPBAR
    # ════════════════════════════════════════════════════════════
    def _topbar(self, title, subtitle=""):

    # MAIN TOPBAR
        bar = tk.Frame(
        self._main,
        bg=SURFACE,
        highlightbackground=BORDER,
        highlightthickness=0
        )

    # FULL WIDTH
        bar.grid(
        row=0,
        column=0,
        sticky="nsew"
        )

    # IMPORTANT
        self._main.grid_columnconfigure(0, weight=1)

    # LEFT COLOR STRIPE
        stripe = tk.Frame(
        bar,
        bg=self._color,
        width=4
        )

        stripe.pack(
        side="left",
        fill="y"
        )

    # CONTENT AREA
        inner = tk.Frame(
        bar,
        bg=SURFACE
        )

        inner.pack(
        side="left",
        padx=(28, 0),
        pady=20,
        fill="both",
        expand=True
        )

    # TITLE
        tk.Label(
        inner,
        text=title,
        bg=SURFACE,
        fg=TEXT_PRI,
        font=("Segoe UI", 20, "bold")
        ).pack(
        anchor="w"
        )

    # SUBTITLE
        if subtitle:

            tk.Label(
            inner,
            text=subtitle,
            bg=SURFACE,
            fg=TEXT_SEC,
            font=("Segoe UI", 11)
            ).pack(
            anchor="w",
            pady=(4, 0)
            )
    # ════════════════════════════════════════════════════════════════════
    #  CREATE DEFECT  — launches CB via Playwright, shows result card
    # ════════════════════════════════════════════════════════════════════
    def _page_create(self):

        self._topbar(
            "Create Defect",
            f"Log a new defect in Project {self.project.upper()}"
        )

        # ── Scrollable area using grid (matches all other pages) ──────────
        scroll_outer = tk.Frame(self._main, bg=BG)
        scroll_outer.grid(row=1, column=0, sticky="nsew")
        scroll_outer.columnconfigure(0, weight=1)
        scroll_outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(scroll_outer, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(scroll_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        scroll_inner = tk.Frame(canvas, bg=BG)
        wid = canvas.create_window((0, 0), window=scroll_inner, anchor="nw")
        scroll_inner.bind("<Configure>",
                          lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(wid, width=e.width))
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        container = tk.Frame(scroll_inner, bg=BG)
        container.pack(fill="x", padx=35, pady=35)

        # ─────────────────────────────────────────────
        # PROJECT LAUNCH CARD
        # ─────────────────────────────────────────────
        card = tk.Frame(
            container,
            bg="#ffffff",
            width=400,
            highlightbackground="#d9dde3",
            highlightthickness=1
        )
        card.pack(anchor="nw")

        # TOP COLOR LINE
        tk.Frame(card, bg=self._color, height=6).pack(fill="x")

        # ICON
        icon_canvas = tk.Canvas(card, width=70, height=70,
                                bg="#ffffff", highlightthickness=0)
        icon_canvas.pack(anchor="w", padx=30, pady=(28, 10))
        icon_canvas.create_oval(5, 5, 65, 65, outline=self._color,
                                width=2, fill="#fff5f8")
        icon_canvas.create_text(35, 35, text="◈", fill=self._color,
                                font=("Segoe UI", 18, "bold"))

        tk.Label(card, text=f" {self.project.upper()}", bg="#ffffff",
                 fg=TEXT_PRI, font=("Segoe UI", 24, "bold")
                 ).pack(anchor="w", padx=35, pady=(10, 6))

        tk.Label(card, text="CodeBeamer · Playwright Automation",
                 bg="#ffffff", fg=TEXT_SEC, font=("Segoe UI", 12)
                 ).pack(anchor="w", padx=35, pady=(0, 10))

        # CB URL preview (from .env)
        url_display = CB_URL if CB_URL else "⚠  CB_URL not set in .env"
        tk.Label(card, text=url_display, bg="#f0f2f5", fg=BLUE,
                 font=("Segoe UI", 10), cursor="hand2",
                 wraplength=340, justify="left"
                 ).pack(anchor="w", padx=35, pady=(0, 18),
                        ipadx=8, ipady=4, fill="x")

        # ── Result area (rendered after Playwright returns) ────────────
        result_frame = tk.Frame(container, bg=BG)
        result_frame.pack(fill="x", pady=(24, 0))

        status_lbl = tk.Label(card, text="", bg="#ffffff", fg=TEXT_SEC,
                              font=("Segoe UI", 11), wraplength=340)
        status_lbl.pack(padx=35, pady=(0, 10))

        def _on_result(res):
            """Called from the background thread; must schedule UI updates on main thread."""
            def _update():
                open_btn.config(state="normal", text="Create Defect   →")
                status_lbl.config(text="")

                if res.get("error"):
                    status_lbl.config(
                        text=f"✗ Error:\n{res['error']}", fg=RED_C)
                    return

                issue_id    = res["id"]
                description = res["description"]
                link        = res["link"]

                # ── Save to APP_DATA so View Defects & Results reflect it ──
                existing_ids = {d.get("cb_id") for d in APP_DATA["defects"]}
                if issue_id not in existing_ids:
                    new_def = {
                        "id":          len(APP_DATA["defects"]) + 1,
                        "cb_id":       issue_id,
                        "title":       f"CB-{issue_id}",
                        "description": description,
                        "link":        link,
                        "project":     self.project,
                        "priority":    "Major",
                        "status":      "Open",
                        "assignee":    CB_USERNAME or "—",
                        "created":     datetime.date.today().isoformat(),
                    }
                    APP_DATA["defects"].append(new_def)
                    save_data(APP_DATA)
                    # refresh sidebar count
                    self._count_lbl.config(
                        text=f"{len(self._proj_defects())} defect(s)")

                # ── Show result card ───────────────────────────────────────
                for w in result_frame.winfo_children():
                    w.destroy()

                rc = tk.Frame(result_frame, bg=SURFACE,
                              highlightbackground=GREEN, highlightthickness=2)
                rc.pack(fill="x")
                tk.Frame(rc, bg=GREEN, height=5).pack(fill="x")

                tk.Label(rc, text="✔  Defect Created in CodeBeamer",
                         bg=SURFACE, fg=GREEN,
                         font=("Segoe UI", 14, "bold")
                         ).pack(anchor="w", padx=24, pady=(18, 6))

                def _row(label, value, clickable=False):
                    r = tk.Frame(rc, bg=SURFACE)
                    r.pack(fill="x", padx=24, pady=5)
                    tk.Label(r, text=label, bg=SURFACE, fg=TEXT_SEC,
                             font=("Segoe UI", 10, "bold"), width=16,
                             anchor="w").pack(side="left")
                    if clickable:
                        lnk = tk.Label(r, text=value, bg=SURFACE, fg=BLUE,
                                       font=("Segoe UI", 10, "underline"),
                                       cursor="hand2", wraplength=460,
                                       justify="left", anchor="w")
                        lnk.pack(side="left", fill="x", expand=True)
                        lnk.bind("<Button-1>", lambda e: webbrowser.open(value))
                    else:
                        tk.Label(r, text=value, bg=SURFACE, fg=TEXT_PRI,
                                 font=("Segoe UI", 10), wraplength=460,
                                 justify="left", anchor="w"
                                 ).pack(side="left", fill="x", expand=True)

                _row("Issue ID",      issue_id)
                _row("Issue Link",    link, clickable=True)

                # separator
                tk.Frame(rc, bg=BORDER, height=1).pack(fill="x",
                                                        padx=24, pady=10)
                tk.Label(rc,
                         text="✔  View Defects & Results pages are updated.",
                         bg=SURFACE, fg=GREEN,
                         font=("Segoe UI", 10)).pack(anchor="w",
                                                      padx=24, pady=(0, 18))

            self.root.after(0, _update)

        def _start_playwright():
            open_btn.config(state="disabled",
                            text="⏳  Launching CodeBeamer…")
            status_lbl.config(
                text="Browser is opening. Fill the defect form in\nCodeBeamer and click Save when done.",
                fg=TEXT_SEC)
            launch_cb_create(CB_URL, CB_USERNAME, CB_PASSWORD, _on_result)

        # BUTTON
        open_btn = tk.Button(
            card,
            text="Create Defect   →",
            bg=self._color,
            fg="#ffffff",
            activebackground=self._color,
            activeforeground="#ffffff",
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=("Segoe UI", 14, "bold"),
            pady=14,
            command=_start_playwright,
        )
        open_btn.pack(fill="x", padx=35, pady=(0, 30))

    # ════════════════════════════════════════════════════════════════════
    #  MODIFY DEFECT
    # ════════════════════════════════════════════════════════════════════
   

    def _page_modify(self):

        self._topbar(
            "Modify Defect",
            f"Edit an existing defect in Project {self.project.upper()}"
        )

        # SCROLLABLE OUTER
        scroll_outer = tk.Frame(self._main, bg=BG)
        scroll_outer.grid(row=1, column=0, sticky="nsew")
        scroll_outer.columnconfigure(0, weight=1)
        scroll_outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(scroll_outer, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(scroll_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        scroll_inner = tk.Frame(canvas, bg=BG)
        wid = canvas.create_window((0, 0), window=scroll_inner, anchor="nw")
        scroll_inner.bind("<Configure>",
                          lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(wid, width=e.width))
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        container = tk.Frame(scroll_inner, bg=BG)
        container.pack(fill="x", padx=35, pady=35)

        # ─────────────────────────────────────────────
        # MODIFY CARD
        # ─────────────────────────────────────────────
        card = tk.Frame(
            container,
            bg="#ffffff",
            highlightbackground="#d9dde3",
            highlightthickness=1
        )
        card.pack(anchor="nw", fill="x")

        # TOP COLOR LINE
        tk.Frame(card, bg=self._color, height=6).pack(fill="x")

        # TITLE
        tk.Label(card, text="Modify Defect", bg="#ffffff", fg=TEXT_PRI,
                 font=("Segoe UI", 22, "bold")).pack(anchor="w", padx=35, pady=(30, 8))

        # SUBTITLE
        tk.Label(card, text=f"Project {self.project.upper()}", bg="#ffffff", fg=TEXT_SEC,
                 font=("Segoe UI", 12)).pack(anchor="w", padx=35, pady=(0, 25))

        # URL LABEL
        tk.Label(card, text="Ticket URL",
                 bg="#ffffff", fg=TEXT_PRI,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=35, pady=(0, 6))

        # URL ENTRY
        url_box = tk.Frame(card, bg="#f8fafc",
                           highlightbackground="#d9dde3", highlightthickness=1)
        url_box.pack(fill="x", padx=35, pady=(0, 25), ipady=8)

        url_var = tk.StringVar()
        url_entry = tk.Entry(url_box, textvariable=url_var, bg="#f8fafc",
                             fg=TEXT_PRI, relief="flat", font=("Segoe UI", 11),
                             insertbackground=TEXT_PRI)
        url_entry.pack(fill="x", padx=14, pady=6)
        url_entry.bind("<FocusIn>",  lambda e: url_box.config(highlightbackground=self._color))
        url_entry.bind("<FocusOut>", lambda e: url_box.config(highlightbackground="#d9dde3"))

        # STATUS LABEL
        status_lbl = tk.Label(card, text="", bg="#ffffff", fg=TEXT_SEC,
                              font=("Segoe UI", 11), wraplength=420)
        status_lbl.pack(padx=35, pady=(0, 8))

        # RESULT AREA (shown after browser closes)
        result_frame = tk.Frame(container, bg=BG)
        result_frame.pack(fill="x", pady=(16, 0))

        def _on_modify_result(res):
            """Called from background thread; schedule UI update on main thread."""
            def _update():
                edit_btn.config(state="normal", text="✎ Edit Defect")
                status_lbl.config(text="")

                if res.get("error"):
                    status_lbl.config(text=f"✗ Error:\n{res['error']}", fg=RED_C)
                    return

                # Show success card
                for w in result_frame.winfo_children():
                    w.destroy()

                rc = tk.Frame(result_frame, bg=SURFACE,
                              highlightbackground=GREEN, highlightthickness=2)
                rc.pack(fill="x")
                tk.Frame(rc, bg=GREEN, height=5).pack(fill="x")
                tk.Label(rc, text="✔  Defect Edited Successfully",
                         bg=SURFACE, fg=GREEN,
                         font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=24, pady=(18, 6))

                final_link = res.get("link", "")
                if final_link:
                    r = tk.Frame(rc, bg=SURFACE)
                    r.pack(fill="x", padx=24, pady=5)
                    tk.Label(r, text="Issue Link:", bg=SURFACE, fg=TEXT_SEC,
                             font=("Segoe UI", 10, "bold"), width=14,
                             anchor="w").pack(side="left")
                    lnk = tk.Label(r, text=final_link, bg=SURFACE, fg=BLUE,
                                   font=("Segoe UI", 10, "underline"),
                                   cursor="hand2", wraplength=400, justify="left", anchor="w")
                    lnk.pack(side="left", fill="x", expand=True)
                    lnk.bind("<Button-1>", lambda e: webbrowser.open(final_link))

                tk.Frame(rc, bg=BORDER, height=1).pack(fill="x", padx=24, pady=10)
                tk.Label(rc, text="✔  Browser closed after Save was detected.",
                         bg=SURFACE, fg=GREEN,
                         font=("Segoe UI", 10)).pack(anchor="w", padx=24, pady=(0, 18))

            self.root.after(0, _update)

        def _start_modify():
            raw_url = url_var.get().strip()
            if not raw_url:
                messagebox.showerror("Validation", "Please enter a Ticket URL.")
                url_box.config(highlightbackground=RED_C)
                return
            url_box.config(highlightbackground="#d9dde3")
            edit_btn.config(state="disabled", text="⏳  Opening Browser…")
            status_lbl.config(
                text="Browser is opening. The Edit button will be clicked automatically.\n"
                     "Make your changes and click Save — the browser will close.",
                fg=TEXT_SEC)
            launch_cb_modify(raw_url, CB_USERNAME, CB_PASSWORD, _on_modify_result)

        # EDIT BUTTON
        edit_btn = tk.Button(
            card,
            text="✎ Edit Defect",
            bg=self._color,
            fg="#ffffff",
            activebackground=self._color,
            activeforeground="#ffffff",
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=("Segoe UI", 13, "bold"),
            padx=20,
            pady=14,
            command=_start_modify,
        )
        edit_btn.pack(fill="x", padx=35, pady=(10, 30))
        edit_btn.bind("<Enter>", lambda e: edit_btn.config(bg=BRAND_DARK))
        edit_btn.bind("<Leave>", lambda e: edit_btn.config(bg=self._color))
    # ════════════════════════════════════════════════════════════════════
    #  VIEW DEFECTS
    # ════════════════════════════════════════════════════════════════════
    def _page_view(self):
        defects = self._proj_defects()
        self._topbar("View Defects",
                     f"{len(defects)} defect(s) logged in Project {self.project.upper()}")
        scroll_outer = tk.Frame(self._main, bg=BG)
        scroll_outer.grid(row=1, column=0, sticky="nsew")
        scroll_outer.columnconfigure(0, weight=1)
        scroll_outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(scroll_outer, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(scroll_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        inner = tk.Frame(canvas, bg=BG)
        wid = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))
        canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

        if not defects:
            empty = tk.Frame(inner, bg=SURFACE,
                             highlightbackground=BORDER, highlightthickness=1)
            empty.pack(padx=36, pady=40, fill="both", expand=True)
            tk.Label(empty, text="📭  No Defects Yet",
                     bg=SURFACE, fg=TEXT_PRI,
                     font=("Segoe UI", 18, "bold")).pack(pady=(60, 8))
            tk.Label(empty, text="No defects have been logged for this project yet.",
                     bg=SURFACE, fg=TEXT_SEC,
                     font=("Segoe UI", 12)).pack(pady=(0, 60))
            return

        # Table card
        tcard = tk.Frame(inner, bg=SURFACE,
                         highlightbackground=BORDER, highlightthickness=1)
        tcard.pack(padx=36, pady=30, fill="x")

        thdr_bar = tk.Frame(tcard, bg=self._color)
        thdr_bar.pack(fill="x")
        tk.Label(thdr_bar, text="  ☰  Defect List",
                 bg=self._color, fg="#fff",
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=16, pady=10)

        # Column headers
        PRI_COLOR = {"Critical": RED_C, "Major": ORANGE, "Minor": BLUE, "Low": GREEN}
        STA_COLOR = {"Open": RED_C, "In Progress": ORANGE, "Closed": GREEN, "Resolved": BLUE}

        hdr = tk.Frame(tcard, bg="#e8eaed")
        hdr.pack(fill="x", padx=0)
        for txt, w in [("Issue ID", 10), ("Issue Link", 50), ("Created", 12)]:
            tk.Label(hdr, text=txt, bg="#e8eaed", fg=TEXT_SEC,
                     font=("Segoe UI", 10, "bold"),
                     width=w, anchor="w"
                     ).pack(side="left", padx=4, pady=10)

        for i, d in enumerate(reversed(defects)):
            row_bg = SURFACE if i % 2 == 0 else "#fafbfc"
            row = tk.Frame(tcard, bg=row_bg,
                           highlightbackground=BORDER, highlightthickness=1)
            row.pack(fill="x", padx=0, pady=1)
            inner2 = tk.Frame(row, bg=row_bg)
            inner2.pack(fill="x", padx=4, pady=8)

            pri = d.get("priority", "Minor")
            sta = d.get("status",   "Open")
            pc  = PRI_COLOR.get(pri, TEXT_SEC)
            sc  = STA_COLOR.get(sta, TEXT_SEC)

            # Issue ID (cb_id preferred, fallback to #id)
            issue_id_text = d.get("cb_id") or f"#{d.get('id','?')}"
            tk.Label(inner2, text=issue_id_text,
                     bg=row_bg, fg=TEXT_PRI,
                     font=("Segoe UI", 10, "bold"), width=10, anchor="w"
                     ).pack(side="left", padx=4)

            # Issue Link (clickable)
            link = d.get("link", "")
            link_short = link[:65] + "…" if len(link) > 65 else link
            lnk_lbl = tk.Label(inner2, text=link_short or "—",
                                bg=row_bg, fg=BLUE if link else TEXT_MUT,
                                font=("Segoe UI", 10,
                                      "underline" if link else "normal"),
                                width=50, anchor="w",
                                cursor="hand2" if link else "arrow")
            lnk_lbl.pack(side="left", padx=4)
            if link:
                lnk_lbl.bind("<Button-1>", lambda e, u=link: webbrowser.open(u))

            tk.Label(inner2, text=d.get("created", ""),
                     bg=row_bg, fg=TEXT_MUT,
                     font=("Segoe UI", 10), width=12, anchor="center"
                     ).pack(side="left", padx=4)

    # ════════════════════════════════════════════════════════════════════
    #  RESULTS
    # ════════════════════════════════════════════════════════════════════
    def _page_results(self):
        defects = self._proj_defects()
        self._topbar("Results",
                     f"Analytics & breakdown for Project {self.project.upper()}")
        scroll_outer = tk.Frame(self._main, bg=BG)
        scroll_outer.grid(row=1, column=0, sticky="nsew")
        scroll_outer.columnconfigure(0, weight=1)
        scroll_outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(scroll_outer, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(scroll_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        inner = tk.Frame(canvas, bg=BG)
        wid = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))
        canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

        total    = len(defects)
        open_c   = sum(1 for d in defects if d.get("status") == "Open")
        prog_c   = sum(1 for d in defects if d.get("status") == "In Progress")
        closed_c = sum(1 for d in defects if d.get("status") in ("Closed", "Resolved"))

        # ── Summary stat cards ────────────────────────────────────────
        stats_wrap = tk.Frame(inner, bg=BG)
        stats_wrap.pack(fill="x", padx=36, pady=(30, 0))
        stats_wrap.columnconfigure(0, weight=1)
        stats_wrap.columnconfigure(1, weight=1)
        stats_wrap.columnconfigure(2, weight=1)
        stats_wrap.columnconfigure(3, weight=1)

        for col_i, (lbl, val, color, icon) in enumerate([
            ("Total Defects", total,    TEXT_PRI, "📋"),
            ("Open",          open_c,   RED_C,    "🔴"),
            ("In Progress",   prog_c,   ORANGE,   "🟡"),
            ("Closed",        closed_c, GREEN,    "🟢"),
        ]):
            sc = tk.Frame(stats_wrap, bg=SURFACE,
                          highlightbackground=BORDER, highlightthickness=1)
            sc.grid(row=0, column=col_i, padx=8, sticky="nsew")
            tk.Frame(sc, bg=color, height=4).pack(fill="x")
            tk.Label(sc, text=icon, bg=SURFACE,
                     font=("Segoe UI", 22)).pack(pady=(18, 4))
            tk.Label(sc, text=str(val), bg=SURFACE, fg=color,
                     font=("Segoe UI", 32, "bold")).pack()
            tk.Label(sc, text=lbl, bg=SURFACE, fg=TEXT_SEC,
                     font=("Segoe UI", 10)).pack(pady=(4, 18))

        # ── Bar charts ────────────────────────────────────────────────
        charts_row = tk.Frame(inner, bg=BG)
        charts_row.pack(fill="x", padx=36, pady=24)
        charts_row.columnconfigure(0, weight=1)
        charts_row.columnconfigure(1, weight=1)

        self._bar_card(charts_row, 0, "Priority Breakdown", [
            ("Critical", sum(1 for d in defects if d.get("priority") == "Critical"), RED_C),
            ("Major",    sum(1 for d in defects if d.get("priority") == "Major"),    ORANGE),
            ("Minor",    sum(1 for d in defects if d.get("priority") == "Minor"),    BLUE),
            ("Low",      sum(1 for d in defects if d.get("priority") == "Low"),      GREEN),
        ], total or 1)

        self._bar_card(charts_row, 1, "Status Breakdown", [
            ("Open",        open_c,   RED_C),
            ("In Progress", prog_c,   ORANGE),
            ("Closed",      sum(1 for d in defects if d.get("status") == "Closed"),   GREEN),
            ("Resolved",    sum(1 for d in defects if d.get("status") == "Resolved"), BLUE),
        ], total or 1)

        # ── Full defect table ─────────────────────────────────────────
        tbl_card = tk.Frame(inner, bg=SURFACE,
                            highlightbackground=BORDER, highlightthickness=1)
        tbl_card.pack(fill="x", padx=36, pady=(0, 36))
        tk.Frame(tbl_card, bg=self._color, height=4).pack(fill="x")
        tk.Label(tbl_card, text="All Defects",
                 bg=SURFACE, fg=TEXT_PRI,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=22, pady=(16, 8))

        cols = ("Issue ID", "Description", "Issue Link", "Priority", "Status", "Created")
        style = ttk.Style()
        style.configure("Treeview",         font=("Segoe UI", 10), rowheight=34)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.map("Treeview", background=[("selected", self._color)])

        tree = ttk.Treeview(tbl_card, columns=cols,
                             show="headings", height=min(max(len(defects), 1), 14))
        for col, w in zip(cols, [90, 240, 260, 85, 105, 105]):
            tree.heading(col, text=col)
            tree.column(col, width=w, anchor="w")
        tree.pack(fill="x", padx=20, pady=(0, 20))

        for d in reversed(defects):
            issue_id_text = d.get("cb_id") or f"#{d.get('id','?')}"
            desc = d.get("description", d.get("title", "—"))
            tree.insert("", "end", values=(
                issue_id_text,
                desc[:50] + ("…" if len(desc) > 50 else ""),
                d.get("link", "—"),
                d.get("priority", ""),
                d.get("status", ""),
                d.get("created", ""),
            ))

    def _bar_card(self, parent, col, title, items, total):
        card = tk.Frame(parent, bg=SURFACE,
                        highlightbackground=BORDER, highlightthickness=1)
        card.grid(row=0, column=col,
                  padx=(0, 12) if col == 0 else (12, 0), sticky="nsew")
        tk.Frame(card, bg=self._color, height=4).pack(fill="x")
        body = tk.Frame(card, bg=SURFACE)
        body.pack(padx=24, pady=22, fill="x")
        tk.Label(body, text=title, bg=SURFACE, fg=TEXT_PRI,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 16))
        for lbl, count, color in items:
            row = tk.Frame(body, bg=SURFACE)
            row.pack(fill="x", pady=6)
            tk.Label(row, text=lbl, bg=SURFACE, fg=TEXT_SEC,
                     font=("Segoe UI", 10), width=13, anchor="w").pack(side="left")
            track = tk.Frame(row, bg="#f0f2f5", height=14)
            track.pack(side="left", fill="x", expand=True, padx=(8, 8))
            track.pack_propagate(False)
            ratio = count / total
            if ratio > 0:
                fill_f = tk.Frame(track, bg=color, height=14)
                fill_f.place(relx=0, rely=0, relwidth=ratio, relheight=1)
            tk.Label(row, text=str(count), bg=SURFACE, fg=color,
                     font=("Segoe UI", 10, "bold"),
                     width=4, anchor="e").pack(side="right")

    def _go_back(self):
        self.root.after(0, lambda: switch_to(ProjectPage))

    def _logout(self):
        if messagebox.askyesno("Logout", "Are you sure you want to logout?"):
            self.root.after(0, lambda: switch_to(LoginWindow))


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        root = get_root()
        LoginWindow(root)
        root.mainloop()
    except KeyboardInterrupt:
        pass
