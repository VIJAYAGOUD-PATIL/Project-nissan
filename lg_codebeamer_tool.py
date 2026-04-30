"""
LG Codebeamer Automation Tool
Whatever you type in the form is exactly what gets filled in Codebeamer.

Install:
    pip install playwright
    playwright install chromium

Run:
    python lg_codebeamer_tool.py
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading

# ── Colors ────────────────────────────────────────────────────────────────────
BRAND      = "#a50034"
BRAND_DARK = "#6b0022"
SURFACE    = "#ffffff"
BG         = "#f0f2f5"
BORDER     = "#e2e5ea"
TEXT       = "#111827"
MUTED      = "#6b7280"
GREEN      = "#22c55e"
RED        = "#ef4444"
ORANGE     = "#f59e0b"

# ── Demo login credentials ────────────────────────────────────────────────────
VALID_USERS = {
    "admin":      "admin123",
    "vijaykumar": "lg@2024",
}


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def centre(win, w, h):
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")


def make_entry(parent, var, secret=False):
    """Bordered entry that highlights red brand on focus."""
    wrap = tk.Frame(parent, bg=SURFACE,
                    highlightbackground=BORDER, highlightthickness=1)
    e = tk.Entry(wrap, textvariable=var,
                 show="•" if secret else "",
                 font=("Segoe UI", 11),
                 bg="#fafafa", fg=TEXT,
                 relief="flat", insertbackground=BRAND)
    e.pack(fill="x", ipady=8, padx=10)
    e.bind("<FocusIn>",  lambda _: wrap.config(highlightbackground=BRAND))
    e.bind("<FocusOut>", lambda _: wrap.config(highlightbackground=BORDER))
    return wrap, e


# ══════════════════════════════════════════════════════════════════════════════
#  LOGIN WINDOW
# ══════════════════════════════════════════════════════════════════════════════
class LoginWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("LG — Sign In")
        root.resizable(False, False)
        centre(root, 420, 500)
        root.configure(bg=BG)
        self._build()

    def _build(self):
        # Header
        hdr = tk.Frame(self.root, bg=BRAND, height=155)
        hdr.pack(fill="x"); hdr.pack_propagate(False)

        brand = tk.Frame(hdr, bg=BRAND)
        brand.pack(anchor="w", padx=36, pady=(28, 0))
        tk.Label(brand, text=" LG ", bg=SURFACE, fg=BRAND,
                 font=("Segoe UI", 12, "bold"), padx=6, pady=3).pack(side="left")
        tk.Label(brand, text="  Defect Tracker", bg=BRAND, fg="white",
                 font=("Segoe UI", 12)).pack(side="left")

        tk.Label(hdr, text="Welcome back", bg=BRAND, fg="white",
                 font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=36, pady=(10, 2))
        tk.Label(hdr, text="Sign in to continue",
                 bg=BRAND, fg="#f9c9d4", font=("Segoe UI", 10)).pack(anchor="w", padx=36)

        # White card
        card = tk.Frame(self.root, bg=SURFACE,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=32, pady=24)
        inner = tk.Frame(card, bg=SURFACE)
        inner.pack(fill="both", expand=True, padx=28, pady=24)

        # Error bar (hidden until needed)
        self._err_var = tk.StringVar()
        self._err_bar = tk.Label(inner, textvariable=self._err_var,
                                 bg="#fef2f2", fg=RED,
                                 font=("Segoe UI", 10), anchor="w",
                                 padx=10, pady=8,
                                 highlightbackground="#fecaca",
                                 highlightthickness=1)

        # Username
        tk.Label(inner, text="Username", bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
        self._user = tk.StringVar()
        uw, ue = make_entry(inner, self._user)
        uw.pack(fill="x"); ue.focus_set()

        # Password
        tk.Label(inner, text="Password", bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(14, 4))
        self._pwd = tk.StringVar()
        pw, _ = make_entry(inner, self._pwd, secret=True)
        pw.pack(fill="x")

        # Sign in button
        tk.Button(inner, text="Sign In",
                  bg=BRAND, fg="white",
                  font=("Segoe UI", 12, "bold"),
                  relief="flat", cursor="hand2",
                  activebackground=BRAND_DARK, activeforeground="white",
                  pady=10, command=self._login
                  ).pack(fill="x", pady=(18, 0))

        # Hint
        tk.Label(inner, text="admin / admin123   ·   vijaykumar / lg@2024",
                 bg=SURFACE, fg=MUTED,
                 font=("Courier New", 9)).pack(pady=(12, 0))

        self.root.bind("<Return>", lambda _: self._login())

    def _login(self):
        user = self._user.get().strip().lower()
        pwd  = self._pwd.get().strip()
        if user in VALID_USERS and VALID_USERS[user] == pwd:
            self.root.destroy()
            launch_main(user)
        else:
            self._err_var.set("⚠  Invalid username or password.")
            self._err_bar.pack(fill="x", pady=(0, 10))
            self._pwd.set("")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW  —  form data → Playwright → Codebeamer
# ══════════════════════════════════════════════════════════════════════════════
class MainWindow:
    def __init__(self, root: tk.Tk, username: str):
        self.root     = root
        self.username = username
        root.title("LG Codebeamer Automation Tool")
        root.resizable(False, False)
        centre(root, 640, 840)
        root.configure(bg=BG)

        # ── All form StringVars (what YOU type goes into Codebeamer) ──────────
        self.v_cb_url      = tk.StringVar()   # Codebeamer page URL
        self.v_cb_user     = tk.StringVar()   # Codebeamer username
        self.v_cb_pass     = tk.StringVar()   # Codebeamer password
        self.v_function    = tk.StringVar()   # → Choose Function field
        self.v_affects_ver = tk.StringVar()   # → Choose Affects version field
        self.v_tc_id       = tk.StringVar()   # → Choose Test Case ID field
        self.v_headless    = tk.BooleanVar(value=True)

        self._build()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build(self):
        self._navbar()
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")
        self._scrollable_body()

    def _navbar(self):
        nav = tk.Frame(self.root, bg=SURFACE, height=56)
        nav.pack(fill="x"); nav.pack_propagate(False)

        tk.Label(nav, text=" LG ", bg=BRAND, fg="white",
                 font=("Segoe UI", 12, "bold"), padx=6, pady=3
                 ).pack(side="left", padx=(16, 8), pady=13)
        tk.Label(nav, text="Codebeamer Automation Tool",
                 bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 12, "bold")).pack(side="left")

        tk.Button(nav, text="Logout", bg=SURFACE, fg=BRAND,
                  font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                  padx=8, highlightbackground=BRAND, highlightthickness=1,
                  command=self._logout
                  ).pack(side="right", pady=15, padx=16)

        initials = "".join(w[0].upper() for w in self.username.split()[:2]) or "U"
        tk.Label(nav, text=self.username.title(), bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 10)).pack(side="right", padx=(0, 4), pady=13)
        tk.Label(nav, text=initials, bg=BRAND, fg="white",
                 font=("Segoe UI", 10, "bold"), padx=7, pady=4
                 ).pack(side="right", padx=(0, 4), pady=13)

    def _scrollable_body(self):
        body   = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)
        canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        vsb    = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        inner  = tk.Frame(canvas, bg=BG)
        wid    = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(wid, width=e.width))
        for w in (canvas, inner):
            w.bind("<MouseWheel>",
                   lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))

        # ── Cards ──
        self._card_login(inner)
        self._card_tracker(inner)
        self._card_options(inner)
        self._card_log(inner)
        tk.Frame(inner, bg=BG, height=16).pack()   # bottom padding

    # ── Card: Codebeamer Login ────────────────────────────────────────────────
    def _card_login(self, parent):
        body = self._card(parent, "🔐  Codebeamer Login")
        self._row(body, "Codebeamer URL",  self.v_cb_url)
        self._row(body, "CB Username",     self.v_cb_user)
        self._row(body, "CB Password",     self.v_cb_pass, secret=True)

    # ── Card: Tracker Fields ──────────────────────────────────────────────────
    def _card_tracker(self, parent):
        body = self._card(parent, "📋  Tracker Fields")
        self._row(body, "Function",        self.v_function)
        self._row(body, "Affects Version", self.v_affects_ver)
        self._row(body, "Test Case ID",    self.v_tc_id)

    # ── Card: Options + Run ───────────────────────────────────────────────────
    def _card_options(self, parent):
        body = self._card(parent, "⚙  Options & Run")

        # Headless toggle
        row = tk.Frame(body, bg=SURFACE)
        row.pack(fill="x", pady=(0, 10))
        tk.Label(row, text="Headless Mode", bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 10, "bold"), width=18, anchor="w").pack(side="left")
        tk.Label(row, text="Hide browser window while running",
                 bg=SURFACE, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=6)
        self._tgl = tk.Label(row, cursor="hand2", font=("Segoe UI", 10, "bold"))
        self._tgl.pack(side="right")
        self._tgl.bind("<Button-1>", lambda _: self._toggle())
        self._redraw_toggle()

        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(4, 12))

        tk.Button(body, text="▶   Run Automation",
                  bg=BRAND, fg="white",
                  font=("Segoe UI", 12, "bold"),
                  relief="flat", cursor="hand2",
                  activebackground=BRAND_DARK, activeforeground="white",
                  pady=11, command=self._run
                  ).pack(fill="x")

    # ── Card: Log ─────────────────────────────────────────────────────────────
    def _card_log(self, parent):
        body = self._card(parent, "📄  Automation Log")
        self._log_box = tk.Text(body, height=11,
                                bg="#0f1623", fg="#a8d8a0",
                                font=("Courier New", 10),
                                relief="flat", wrap="word",
                                state="disabled")
        self._log_box.pack(fill="x")
        self._status_var = tk.StringVar(value="Ready")
        self._status_lbl = tk.Label(body, textvariable=self._status_var,
                                    bg=SURFACE, fg=MUTED,
                                    font=("Segoe UI", 9), anchor="w")
        self._status_lbl.pack(fill="x", pady=(6, 0))

    # ── Reusable card shell ───────────────────────────────────────────────────
    def _card(self, parent, title) -> tk.Frame:
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="x", padx=28, pady=(12, 0))
        card = tk.Frame(outer, bg=SURFACE,
                        highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x")
        hdr = tk.Frame(card, bg=SURFACE)
        hdr.pack(fill="x", padx=20, pady=(14, 8))
        tk.Label(hdr, text=title, bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Frame(card, bg=BORDER, height=1).pack(fill="x")
        body = tk.Frame(card, bg=SURFACE)
        body.pack(fill="x", padx=20, pady=(10, 16))
        return body

    # ── Reusable aligned row ──────────────────────────────────────────────────
    def _row(self, parent, label: str, var: tk.StringVar, secret=False):
        """
        Fixed 160-px label column so all entry boxes align perfectly.
        var is the StringVar — whatever the user types is stored directly.
        """
        row = tk.Frame(parent, bg=SURFACE)
        row.pack(fill="x", pady=5)

        # Label column (fixed width)
        lbl_col = tk.Frame(row, bg=SURFACE, width=160)
        lbl_col.pack(side="left"); lbl_col.pack_propagate(False)
        tk.Label(lbl_col, text=label + "  *",
                 bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 10, "bold"), anchor="w"
                 ).pack(anchor="w", pady=7)

        # Entry (fills remaining width)
        wrap, _ = make_entry(row, var, secret=secret)
        wrap.pack(side="left", fill="x", expand=True)

    # ── Toggle ────────────────────────────────────────────────────────────────
    def _toggle(self):
        self.v_headless.set(not self.v_headless.get())
        self._redraw_toggle()

    def _redraw_toggle(self):
        if self.v_headless.get():
            self._tgl.config(text=" ON ", bg=BRAND, fg="white", padx=4, pady=3)
        else:
            self._tgl.config(text="OFF",  bg="#e5e7eb", fg=MUTED, padx=4, pady=3)

    # ── Log helpers (thread-safe) ─────────────────────────────────────────────
    def _log(self, msg: str, colour: str = None):
        def _go():
            self._log_box.config(state="normal")
            if colour:
                tag = f"t{colour[1:]}"
                self._log_box.tag_configure(tag, foreground=colour)
                self._log_box.insert("end", msg + "\n", tag)
            else:
                self._log_box.insert("end", msg + "\n")
            self._log_box.see("end")
            self._log_box.config(state="disabled")
        self.root.after(0, _go)

    def _status(self, text: str, colour=MUTED):
        self.root.after(0, lambda: (
            self._status_var.set(text),
            self._status_lbl.config(fg=colour)
        ))

    # ── Validation ────────────────────────────────────────────────────────────
    def _validate(self):
        """Reads form values. Returns dict or None if any field is empty."""
        checks = [
            (self.v_cb_url,      "Codebeamer URL"),
            (self.v_cb_user,     "CB Username"),
            (self.v_cb_pass,     "CB Password"),
            (self.v_function,    "Function"),
            (self.v_affects_ver, "Affects Version"),
            (self.v_tc_id,       "Test Case ID"),
        ]
        missing = [label for var, label in checks if not var.get().strip()]
        if missing:
            messagebox.showerror("Missing Fields",
                                 "Please fill in:\n\n• " + "\n• ".join(missing))
            return None

        return {
            "cb_url":      self.v_cb_url.get().strip(),
            "cb_user":     self.v_cb_user.get().strip(),
            "cb_pass":     self.v_cb_pass.get().strip(),
            "function":    self.v_function.get().strip(),
            "affects_ver": self.v_affects_ver.get().strip(),
            "tc_id":       self.v_tc_id.get().strip(),
            "headless":    self.v_headless.get(),
        }

    # ── Run ───────────────────────────────────────────────────────────────────
    def _run(self):
        data = self._validate()
        if not data:
            return

        # Clear log
        self._log_box.config(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.config(state="disabled")

        self._status("⏳  Running …", ORANGE)
        self._log("═" * 52)
        self._log("  LG Codebeamer Automation — Started")
        self._log("═" * 52)
        self._log(f"  URL            : {data['cb_url']}")
        self._log(f"  CB Username    : {data['cb_user']}")
        self._log(f"  Function       : {data['function']}")
        self._log(f"  Affects Ver.   : {data['affects_ver']}")
        self._log(f"  Test Case ID   : {data['tc_id']}")
        self._log(f"  Headless       : {data['headless']}")
        self._log("")

        threading.Thread(target=self._automate, args=(data,), daemon=True).start()

    # ── Playwright automation (background thread) ─────────────────────────────
    def _automate(self, d: dict):
        """
        d["function"], d["affects_ver"], d["tc_id"] are EXACTLY what the user
        typed — no defaults, no hardcoding. They go straight into Codebeamer.
        """
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                # 1 ─ Launch browser
                self._log("[1/6] Launching Chromium browser …")
                browser = p.chromium.launch(headless=d["headless"])
                page    = browser.new_page()

                # 2 ─ Open Codebeamer
                self._log(f"[2/6] Opening  →  {d['cb_url']}")
                page.goto(d["cb_url"], timeout=30_000)

                # 3 ─ Login
                self._log("[3/6] Filling login credentials …")
                page.fill('input[name="user"]',     d["cb_user"])
                page.fill('input[name="password"]', d["cb_pass"])
                page.click('input[type="submit"]')
                page.wait_for_load_state("networkidle", timeout=20_000)
                self._log("      ✅ Logged in.", GREEN)

                page.goto(d["cb_url"], timeout=30_000)
                page.wait_for_load_state("networkidle", timeout=20_000)

                # 4 ─ Function field  ← user's value from form
                self._log(f"[4/6] Typing Function  →  \"{d['function']}\"")
                vc = page.locator('table[title*="Choose Function"]')
                vi = vc.get_by_role("textbox")
                vi.click()
                vi.press_sequentially(d["function"], delay=300)   # ← form value
                page.wait_for_timeout(500)
                page.keyboard.press("Enter")
                self._log("      ✅ Function filled.", GREEN)

                # 5 ─ Affects Version  ← user's value from form
                self._log(f"[5/6] Typing Affects Version  →  \"{d['affects_ver']}\"")
                ac = page.locator('table[title*="Choose Affects version"]')
                ai = ac.get_by_role("textbox")
                ai.click()
                ai.press_sequentially(d["affects_ver"], delay=300)   # ← form value
                page.wait_for_timeout(500)
                page.keyboard.press("Enter")
                self._log("      ✅ Affects Version filled.", GREEN)

                # 6 ─ Test Case ID  ← user's value from form
                self._log(f"[6/6] Typing Test Case ID  →  \"{d['tc_id']}\"")
                tc = page.locator('table[title*="Choose Test Case ID"]')
                ti = tc.get_by_role("textbox")
                ti.click()
                ti.press_sequentially(d["tc_id"], delay=400)   # ← form value
                page.wait_for_timeout(500)
                page.keyboard.press("Enter")
                self._log("      ✅ Test Case ID filled.", GREEN)

                browser.close()

            self._log("")
            self._log("═" * 52)
            self._log("  🎉  All fields filled successfully!")
            self._log("═" * 52)
            self._status("✅  Done — all fields filled", GREEN)

        except ImportError:
            msg = ("Playwright is not installed.\n\n"
                   "Run in terminal:\n"
                   "  pip install playwright\n"
                   "  playwright install chromium")
            self._log(f"[ERROR] {msg}", RED)
            self._status("❌  Playwright not installed", RED)
            self.root.after(0, lambda: messagebox.showerror("Missing Package", msg))

        except Exception as ex:
            self._log(f"[ERROR] {ex}", RED)
            self._status(f"❌  {ex}", RED)

    # ── Logout ────────────────────────────────────────────────────────────────
    def _logout(self):
        if messagebox.askyesno("Logout", "Are you sure you want to logout?"):
            self.root.destroy()
            launch_login()


# ══════════════════════════════════════════════════════════════════════════════
#  LAUNCHERS
# ══════════════════════════════════════════════════════════════════════════════
def launch_login():
    root = tk.Tk()
    LoginWindow(root)
    root.mainloop()


def launch_main(username: str):
    root = tk.Tk()
    MainWindow(root, username)
    root.mainloop()


if __name__ == "__main__":
    launch_login()
