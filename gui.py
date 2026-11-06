"""Desktop client for the Pharma AI Agent (CustomTkinter).

A lightweight single-window chat client. For inventory tables, documents, stock movements
and the audit log use the web UI (web/app.py).

Environment: BACKEND_URL (default http://127.0.0.1:8000), PHARMA_USER, PHARMA_PASSWORD.
"""
import os
import re
import sys
import threading
import time
import tkinter as tk
import uuid

import customtkinter as ctk
import requests
from PIL import Image, ImageDraw

ctk.set_appearance_mode("System")  # follows the OS; the sidebar toggle overrides it

# ----------------------------------------------------------------------------- design tokens
# Colours are (light, dark) pairs, which CustomTkinter switches automatically.
BRAND = "#6E34D1"  # Doesy purple
BRAND_HOVER = "#5B28B5"
BRAND_TEXT = ("#6E34D1", "#C4B5FD")
BG = ("#F7F5FC", "#0B1220")
SIDEBAR = ("#FFFFFF", "#111827")
CARD = ("#FFFFFF", "#1E293B")
SOFT = ("#F1F5F9", "#0F172A")
BORDER = ("#E6E0F5", "#334155")
HOVER = ("#F1F5F9", "#273449")
TEXT = ("#0F172A", "#F1F5F9")
MUTED = ("#64748B", "#94A3B8")
OK_BG, OK_TX = ("#DCFCE7", "#14532D"), ("#166534", "#86EFAC")
BAD_BG, BAD_TX = ("#FEE2E2", "#7F1D1D"), ("#991B1B", "#FECACA")
MONO = {"win32": "Consolas", "darwin": "Menlo"}.get(sys.platform, "DejaVu Sans Mono")

# (button label, question) — shared by the sidebar and the welcome screen
PRESETS = [
    ("Check Amoxicillin stock", "What is the current stock level of Amoxicillin?"),
    ("Ibuprofen expiry & contraindications", "Check expiration and contraindications for Ibuprofen batch IBU-9942."),
    ("What needs attention?", "What is expired, expiring soon, or low on stock?"),
]


# ----------------------------------------------------------------------------- Doesy (mascot)
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "assets", "doesy")  # see docs/BRAND.md


def _asset(name: str):
    try:
        return Image.open(os.path.join(ASSET_DIR, name)).convert("RGBA")
    except OSError:  # missing assets must never stop the app from starting
        return None


def doesy_image(name: str, height: int):
    """A CTkImage of a Doesy asset at the given display height (same image for light and dark mode)."""
    img = _asset(name)
    if img is None:
        return None
    return ctk.CTkImage(light_image=img, dark_image=img, size=(round(img.width * height / img.height), height))


def _lerp(t: float, keys: list) -> float:
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * ((t - t0) / (t1 - t0) if t1 > t0 else 0)
    return keys[-1][1]


def push_frames(count: int = 32, width: int = 168, height: int = 58):
    """Pre-render the 'Doesy pushes a pill' loop (mirrors the web UI's CSS animation). Returns CTkImages or []."""
    bot = _asset("doesy-full-128.png")
    if bot is None:
        return []
    k = 2  # supersample, then let CTkImage scale for HiDPI
    bh = 54 * k
    bot = bot.resize((round(bot.width * bh / bot.height), bh), Image.LANCZOS)
    pw, ph = 26 * k, 12 * k
    pill = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    draw = ImageDraw.Draw(pill)
    draw.rectangle((0, 0, pw // 2, ph), fill=(110, 52, 209, 255))
    draw.rectangle((pw // 2, 0, pw, ph), fill=(255, 255, 255, 255))
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw - 1, ph - 1), radius=ph // 2, fill=255)
    pill.putalpha(mask)
    ImageDraw.Draw(pill).rounded_rectangle((0, 0, pw - 1, ph - 1), radius=ph // 2, outline=(110, 52, 209, 255), width=2 * k)
    frames = []
    for i in range(count):
        t = i / count
        canvas = Image.new("RGBA", (width * k, height * k), (0, 0, 0, 0))
        bx = _lerp(t, [(0, 0), (.14, -3), (.52, 52), (1, 0)])
        br = _lerp(t, [(0, 0), (.14, -5), (.52, 8), (1, 0)])
        body = bot.rotate(-br, resample=Image.BICUBIC, center=(bot.width / 2, bot.height))
        canvas.alpha_composite(body, (round((6 + bx) * k), canvas.height - bh))
        px = _lerp(t, [(0, 0), (.14, 0), (.52, 52), (.80, 88), (.92, 100), (1, 100)])
        opacity = _lerp(t, [(0, 0), (.14, 1), (.80, 1), (.92, 0), (1, 0)])
        spin = _lerp(t, [(0, 0), (.14, 0), (.52, 500), (.80, 700), (.92, 760), (1, 760)])
        if opacity > 0.02:
            rolled = pill.rotate(-spin, resample=Image.BICUBIC, expand=True)
            rolled.putalpha(rolled.getchannel("A").point(lambda a: int(a * opacity)))
            cx, cy = (58 + 13 + px) * k, canvas.height - 13 * k
            canvas.alpha_composite(rolled, (round(cx - rolled.width / 2), round(cy - rolled.height / 2)))
        frames.append(ctk.CTkImage(light_image=canvas, dark_image=canvas, size=(width, height)))
    return frames


def plain_text(markdown: str) -> str:
    """Tk labels can't render markdown, so strip the markers instead of showing stray asterisks."""
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), markdown, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    return re.sub(r"^(\s*)[-*]\s+", r"\1•  ", text, flags=re.M)


class PharmaDesktopApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Pharma AI Assistant")
        try:
            self._icon = tk.PhotoImage(file=os.path.join(ASSET_DIR, "favicon-64.png"))
            self.iconphoto(True, self._icon)
        except tk.TclError:
            pass
        self.geometry("1100x720")
        self.minsize(840, 560)
        self.configure(fg_color=BG)

        base_url = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
        self.backend_url = f"{base_url}/api/v1/chat"
        self.health_url = f"{base_url}/health"
        self.login_url = f"{base_url}/api/v1/auth/login"
        self.username = os.getenv("PHARMA_USER", "")
        self.password = os.getenv("PHARMA_PASSWORD", "")
        self.token = None
        self.session_id = uuid.uuid4().hex  # same id = the agent remembers the conversation

        self.busy = False
        self.wrap = 560
        self._wrap_labels: list[tuple[ctk.CTkLabel, int]] = []
        self._welcome = None
        self._thinking_row = None
        self._thinking_label = None
        self._thinking_job = None
        self._resize_job = None
        self._dots = 0
        self._frame = 0
        self._push = None  # lazily built animation frames
        self._logo = doesy_image("doesy-badge-128.png", 38)
        self._mini = doesy_image("doesy-badge-64.png", 22)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(2, weight=1)
        self._build_sidebar()
        ctk.CTkFrame(self, width=1, corner_radius=0, fg_color=BORDER).grid(row=0, column=1, sticky="ns")
        self._build_main()

        self.show_welcome()
        self.bind("<Control-n>", lambda _e: self.new_conversation())
        threading.Thread(target=self.health_loop, daemon=True).start()

    # ------------------------------------------------------------------------- layout
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=268, corner_radius=0, fg_color=SIDEBAR)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.pack_propagate(False)

        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(22, 0))
        ctk.CTkLabel(brand, text="", image=self._logo, width=38, height=38).pack(side="left")
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left", padx=10)
        ctk.CTkLabel(names, text="Pharma AI", text_color=TEXT, font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(names, text="Operations & Compliance", text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w")

        self.status_badge = ctk.CTkLabel(sb, text="●  Checking service…", height=28, corner_radius=14, fg_color=SOFT,
                                         text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold"))
        self.status_badge.pack(fill="x", padx=18, pady=(18, 22))

        ctk.CTkLabel(sb, text="QUICK AUDITS", text_color=MUTED,
                     font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=20, pady=(0, 6))
        self.preset_buttons = []
        for label, question in PRESETS:
            btn = ctk.CTkButton(sb, text=label, anchor="w", height=38, corner_radius=10, fg_color="transparent",
                                border_width=1, border_color=BORDER, text_color=TEXT, hover_color=HOVER,
                                font=ctk.CTkFont(size=13), command=lambda q=question: self.send_preset(q))
            btn.pack(fill="x", padx=18, pady=3)
            self.preset_buttons.append(btn)

        # bottom block (packed bottom-up)
        self.user_label = ctk.CTkLabel(
            sb, text=f"Signed in as {self.username}" if self.username else "Not signed in — set PHARMA_USER / PHARMA_PASSWORD",
            text_color=MUTED, font=ctk.CTkFont(size=11), wraplength=225, justify="left")
        self.user_label.pack(side="bottom", anchor="w", padx=20, pady=(6, 18))
        self.theme_switch = ctk.CTkSegmentedButton(
            sb, values=["Light", "Dark", "System"], command=lambda v: ctk.set_appearance_mode(v),
            selected_color=BRAND, selected_hover_color=BRAND_HOVER, font=ctk.CTkFont(size=12))
        self.theme_switch.set("System")
        self.theme_switch.pack(side="bottom", fill="x", padx=18, pady=(8, 0))
        ctk.CTkButton(sb, text="New conversation  (Ctrl+N)", height=38, corner_radius=10, fg_color=BRAND,
                      hover_color=BRAND_HOVER, font=ctk.CTkFont(size=13, weight="bold"),
                      command=self.new_conversation).pack(side="bottom", fill="x", padx=18, pady=(0, 6))

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=2, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 6))
        ctk.CTkLabel(header, text="Assistant", text_color=TEXT, font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(header, text="Ask Doesy about stock, expiry dates, storage rules and drug interactions.",
                     text_color=MUTED, font=ctk.CTkFont(size=13)).pack(anchor="w")

        self.chat = ctk.CTkScrollableFrame(main, fg_color="transparent")
        self.chat.grid(row=1, column=0, sticky="nsew", padx=(18, 10), pady=(4, 0))
        self.chat._parent_canvas.bind("<Configure>", self._on_chat_resize, add="+")

        composer = ctk.CTkFrame(main, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
        composer.grid(row=2, column=0, sticky="ew", padx=28, pady=(8, 4))
        composer.grid_columnconfigure(0, weight=1)
        self.input = ctk.CTkTextbox(composer, height=44, wrap="word", fg_color="transparent", border_width=0,
                                    text_color=TEXT, font=ctk.CTkFont(size=14))
        self.input.grid(row=0, column=0, sticky="ew", padx=(12, 6), pady=8)
        self.input.bind("<Return>", self._on_return)
        self.input.bind("<KeyRelease>", lambda _e: self._resize_input())
        self.send_button = ctk.CTkButton(composer, text="Send", width=92, height=38, corner_radius=10, fg_color=BRAND,
                                         hover_color=BRAND_HOVER, font=ctk.CTkFont(size=13, weight="bold"),
                                         command=self.send_message)
        self.send_button.grid(row=0, column=1, sticky="s", padx=(0, 10), pady=8)
        ctk.CTkLabel(main, text="Enter to send  ·  Shift+Enter for a new line", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).grid(row=3, column=0, pady=(0, 12))

    # ------------------------------------------------------------------------- input handling
    def _on_return(self, event):
        if event.state & 0x0001:  # Shift+Enter inserts a newline
            return None
        self.send_message()
        return "break"

    def _resize_input(self):
        try:
            counted = self.input._textbox.count("1.0", "end", "displaylines")
            lines = counted[0] if isinstance(counted, tuple) else (counted or 1)
        except Exception:
            lines = 1
        self.input.configure(height=min(130, max(44, 20 * lines + 14)))

    def send_message(self):
        query = self.input.get("1.0", "end").strip()
        if not query or self.busy:
            return
        self.input.delete("1.0", "end")
        self._resize_input()
        self.submit(query)

    def send_preset(self, query_text: str):
        self.submit(query_text)

    def submit(self, query: str):
        query = query.strip()
        if not query or self.busy:
            return
        self.clear_welcome()
        self.add_user_message(query)
        self.set_busy(True)
        self.show_thinking()
        self.scroll_to_bottom()
        # Run the backend request in a background thread so the window stays responsive
        threading.Thread(target=self.query_backend_thread, args=(query,), daemon=True).start()

    def set_busy(self, busy: bool):
        self.busy = busy
        self.send_button.configure(state="disabled" if busy else "normal", text="Thinking…" if busy else "Send")
        for btn in self.preset_buttons:
            btn.configure(state="disabled" if busy else "normal")

    # ------------------------------------------------------------------------- backend (unchanged behaviour)
    def health_loop(self):
        """Poll /health so the status badge reflects the real backend state."""
        while True:
            try:
                online = requests.get(self.health_url, timeout=3).status_code == 200
            except requests.RequestException:
                online = False
            try:
                self.after(0, self.set_status, online)
            except RuntimeError:  # window was closed
                return
            time.sleep(10)

    def set_status(self, online: bool):
        if online:
            self.status_badge.configure(text="●  Service online", fg_color=OK_BG, text_color=OK_TX)
        else:
            self.status_badge.configure(text="●  Service offline", fg_color=BAD_BG, text_color=BAD_TX)

    def login(self) -> bool:
        """Log in with PHARMA_USER / PHARMA_PASSWORD and keep the JWT."""
        response = requests.post(self.login_url, json={"username": self.username, "password": self.password}, timeout=15)
        if response.status_code != 200:
            return False
        self.token = response.json()["access_token"]
        return True

    def post_chat(self, query: str):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        return requests.post(self.backend_url, json={"query": query, "session_id": self.session_id},
                             headers=headers, timeout=90)

    @staticmethod
    def format_sources(citations: list) -> str:
        """Plain-text rendering of citations (kept for scripts/tests; the UI renders them as cards)."""
        lines = []
        for c in citations:
            if c.get("type") == "sql":
                lines.append(f"  - SQL: {c['query']}")
            elif c.get("type") == "document":
                page = f", p.{c['page']}" if c.get("page") else ""
                lines.append(f"  - Document: {c['source']}{page}")
            elif c.get("type") == "inventory_alerts":
                lines.append(f"  - Inventory alerts (next {c['days_ahead']} days)")
        return "\n\nSources:\n" + "\n".join(lines) if lines else ""

    def query_backend_thread(self, query: str):
        try:
            response = self.post_chat(query)
            if response.status_code == 401 and self.login():  # no/expired token: log in once and retry
                response = self.post_chat(query)
            if response.status_code == 200:
                data = response.json()
                self.session_id = data.get("session_id", self.session_id)
                self.after(0, self.deliver, "assistant", data.get("response", "No response content received."),
                           data.get("citations", []))
            elif response.status_code == 401:
                self.after(0, self.deliver, "error", "Login failed: set PHARMA_USER and PHARMA_PASSWORD.", [])
            elif response.status_code == 429:
                self.after(0, self.deliver, "error", "Too many requests: wait a moment and try again.", [])
            else:
                self.after(0, self.deliver, "error", f"Server responded with code {response.status_code}", [])
        except Exception as e:
            self.after(0, self.deliver, "error", f"Could not reach API service: {str(e)}", [])
        finally:
            self.after(0, self.finish_request)

    def deliver(self, kind: str, text: str, citations: list):
        self.hide_thinking()
        if kind == "assistant":
            self.add_assistant_message(text, citations)
        else:
            self.add_error_message(text)
        self.scroll_to_bottom()

    def finish_request(self):
        self.hide_thinking()
        self.set_busy(False)
        self.input.focus_set()

    def new_conversation(self):
        if self.busy:
            return
        self.session_id = uuid.uuid4().hex
        for widget in self.chat.winfo_children():
            widget.destroy()
        self._wrap_labels.clear()
        self._welcome = None
        self.add_system_notice("Started a new conversation — the agent forgot the previous one.")
        self.show_welcome()

    # ------------------------------------------------------------------------- chat rendering
    def _row(self) -> ctk.CTkFrame:
        row = ctk.CTkFrame(self.chat, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=5)
        return row

    def _label(self, parent, text, offset: int = 0, **kwargs) -> ctk.CTkLabel:
        label = ctk.CTkLabel(parent, text=text, justify="left", anchor="w", wraplength=self.wrap - offset, **kwargs)
        self._wrap_labels.append((label, offset))
        return label

    def _on_chat_resize(self, event):
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(80, self._apply_wrap, event.width)

    def _apply_wrap(self, width: int):
        self._resize_job = None
        new = max(300, int(width * 0.72))
        if abs(new - self.wrap) < 20:
            return
        self.wrap = new
        alive = []
        for label, offset in self._wrap_labels:
            if label.winfo_exists():
                label.configure(wraplength=new - offset)
                alive.append((label, offset))
        self._wrap_labels = alive

    def scroll_to_bottom(self):
        self.after(60, lambda: (self.update_idletasks(), self.chat._parent_canvas.yview_moveto(1.0)))

    def _bubble(self, row, fg, border=0):
        bubble = ctk.CTkFrame(row, fg_color=fg, corner_radius=16, border_width=border, border_color=BORDER)
        return bubble

    def add_user_message(self, text: str):
        row = self._row()
        bubble = self._bubble(row, BRAND)
        bubble.pack(side="right", padx=(60, 0))
        self._label(bubble, text, text_color="white", font=ctk.CTkFont(size=14)).pack(padx=16, pady=10)

    def add_assistant_message(self, text: str, citations: list):
        row = self._row()
        bubble = self._bubble(row, CARD, border=1)
        bubble.pack(side="left", padx=(0, 60))
        head = ctk.CTkFrame(bubble, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(10, 0))
        ctk.CTkLabel(head, text=" Doesy", image=self._mini, compound="left", text_color=BRAND_TEXT,
                     font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
        copy = ctk.CTkButton(head, text="Copy", width=48, height=22, fg_color="transparent", text_color=MUTED,
                             hover_color=HOVER, font=ctk.CTkFont(size=11))
        copy.configure(command=lambda: self.copy_text(text, copy))
        copy.pack(side="right")
        self._label(bubble, plain_text(text), text_color=TEXT, font=ctk.CTkFont(size=14)).pack(
            anchor="w", padx=16, pady=(4, 10 if not citations else 6))
        if citations:
            self._add_sources(bubble, citations)

    def _add_sources(self, bubble, citations: list):
        box = ctk.CTkFrame(bubble, fg_color="transparent")
        box.pack(fill="x", padx=10, pady=(0, 10))
        detail = ctk.CTkFrame(box, fg_color=SOFT, corner_radius=10)
        toggle = ctk.CTkButton(box, text=f"▸  Sources ({len(citations)})", anchor="w", width=10, height=26,
                               fg_color="transparent", text_color=MUTED, hover_color=HOVER,
                               font=ctk.CTkFont(size=12, weight="bold"))

        def flip():
            if detail.winfo_ismapped():
                detail.pack_forget()
                toggle.configure(text=f"▸  Sources ({len(citations)})")
            else:
                detail.pack(fill="x", pady=(4, 0))
                toggle.configure(text=f"▾  Sources ({len(citations)})")
                self.scroll_to_bottom()

        toggle.configure(command=flip)
        toggle.pack(anchor="w")
        for c in citations:
            item = ctk.CTkFrame(detail, fg_color="transparent")
            item.pack(fill="x", padx=12, pady=(8, 4))
            kind = c.get("type")
            if kind == "sql":
                rows = f" · {c['row_count']} row(s)" if "row_count" in c else ""
                self._label(item, f"Database query{rows}", 70, text_color=MUTED,
                            font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
                self._label(item, c.get("query", ""), 70, text_color=TEXT, font=ctk.CTkFont(family=MONO, size=12)).pack(anchor="w")
            elif kind == "document":
                page = f" · p.{c['page']}" if c.get("page") else ""
                self._label(item, f"{c.get('source', 'document')}{page}", 70, text_color=BRAND_TEXT,
                            font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
                snippet = (c.get("snippet") or "").strip()
                if snippet:
                    self._label(item, snippet[:280] + ("…" if len(snippet) > 280 else ""), 70, text_color=MUTED,
                                font=ctk.CTkFont(size=12)).pack(anchor="w")
            elif kind == "inventory_alerts":
                self._label(item, f"Inventory alerts · next {c.get('days_ahead', '?')} days", 70, text_color=MUTED,
                            font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")

    def add_error_message(self, text: str):
        row = self._row()
        bubble = self._bubble(row, BAD_BG)
        bubble.pack(side="left", padx=(0, 60))
        self._label(bubble, "System error", text_color=BAD_TX, font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w", padx=16, pady=(10, 0))
        self._label(bubble, text, text_color=BAD_TX, font=ctk.CTkFont(size=14)).pack(anchor="w", padx=16, pady=(2, 10))

    def add_system_notice(self, text: str):
        ctk.CTkLabel(self.chat, text=text, text_color=MUTED, font=ctk.CTkFont(size=12, slant="italic")).pack(pady=8)

    def copy_text(self, text: str, button: ctk.CTkButton):
        self.clipboard_clear()
        self.clipboard_append(text)
        button.configure(text="Copied")
        self.after(1500, lambda: button.winfo_exists() and button.configure(text="Copy"))

    # thinking indicator: Doesy pushes a pill along (frames are pre-rendered, see push_frames)
    def show_thinking(self):
        if self._push is None:
            self._push = push_frames()
        self._thinking_row = self._row()
        bubble = self._bubble(self._thinking_row, CARD, border=1)
        bubble.pack(side="left")
        inner = ctk.CTkFrame(bubble, fg_color="transparent")
        inner.pack(padx=(8, 16), pady=4)
        self._thinking_anim = ctk.CTkLabel(inner, text="", image=self._push[0] if self._push else None)
        self._thinking_anim.pack(side="left")
        self._thinking_label = ctk.CTkLabel(inner, text="Searching inventory and documents", text_color=MUTED,
                                            font=ctk.CTkFont(size=13))
        self._thinking_label.pack(side="left", padx=(6, 0))
        self._dots = 0
        self._frame = 0
        self._tick()

    def _tick(self):
        if self._thinking_row is None:
            return
        self._frame += 1
        if self._push:
            self._thinking_anim.configure(image=self._push[self._frame % len(self._push)])
        if self._frame % 7 == 0:
            self._dots = (self._dots + 1) % 4
            self._thinking_label.configure(text="Searching inventory and documents" + "." * self._dots)
        self._thinking_job = self.after(60, self._tick)

    def hide_thinking(self):
        if self._thinking_job:
            self.after_cancel(self._thinking_job)
            self._thinking_job = None
        if self._thinking_row is not None:
            self._thinking_row.destroy()
            self._thinking_row = None

    # welcome screen
    def show_welcome(self):
        frame = ctk.CTkFrame(self.chat, fg_color="transparent")
        frame.pack(pady=(40, 0))
        ctk.CTkLabel(frame, text="", image=doesy_image("doesy-full-256.png", 150)).pack()
        ctk.CTkLabel(frame, text="Hi, I'm Doesy. How can I help today?", text_color=TEXT,
                     font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(14, 2))
        ctk.CTkLabel(frame, text="Every answer cites the database rows or label pages it came from.",
                     text_color=MUTED, font=ctk.CTkFont(size=13)).pack(pady=(0, 16))
        for label, question in PRESETS:
            ctk.CTkButton(frame, text=label, width=340, height=40, corner_radius=12, fg_color=CARD, border_width=1,
                          border_color=BORDER, text_color=TEXT, hover_color=HOVER, font=ctk.CTkFont(size=13),
                          command=lambda q=question: self.send_preset(q)).pack(pady=4)
        self._welcome = frame

    def clear_welcome(self):
        if self._welcome is not None:
            self._welcome.destroy()
            self._welcome = None


if __name__ == "__main__":
    app = PharmaDesktopApp()
    app.mainloop()