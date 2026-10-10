import os
import threading
import time
import uuid

import customtkinter as ctk
import requests

# Set dark theme and modern blue accent
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class PharmaDesktopApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Pharma AI Operations & Compliance Dashboard")
        self.geometry("1000x650")
        base_url = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
        self.backend_url = f"{base_url}/api/v1/chat"
        self.health_url = f"{base_url}/health"
        self.login_url = f"{base_url}/api/v1/auth/login"
        self.username = os.getenv("PHARMA_USER", "")
        self.password = os.getenv("PHARMA_PASSWORD", "")
        self.token = None
        self.session_id = uuid.uuid4().hex  # same id = the agent remembers the conversation

        # Grid layout (1 row, 2 columns)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # -------------------------------------------------------------
        # Sidebar Panel (Quick Status & Pre-built Queries)
        # -------------------------------------------------------------
        self.sidebar_frame = ctk.CTkFrame(self, width=240, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        
        self.logo_label = ctk.CTkLabel(
            self.sidebar_frame, 
            text="Pharma AI Terminal", 
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.logo_label.pack(padx=20, pady=(20, 10))

        self.status_badge = ctk.CTkLabel(
            self.sidebar_frame,
            text="● Checking service...",
            text_color="#9E9E9E",
            font=ctk.CTkFont(size=12)
        )
        self.status_badge.pack(padx=20, pady=(0, 20))

        # Quick Action Buttons
        self.quick_btn_label = ctk.CTkLabel(
            self.sidebar_frame, 
            text="Quick Audits:", 
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.quick_btn_label.pack(padx=20, pady=(10, 5), anchor="w")

        btn1 = ctk.CTkButton(
            self.sidebar_frame, 
            text="Check Amoxicillin Stock", 
            command=lambda: self.send_preset("What is the current stock level of Amoxicillin?")
        )
        btn1.pack(padx=20, pady=5, fill="x")

        btn2 = ctk.CTkButton(
            self.sidebar_frame, 
            text="Ibuprofen Expiry & Contraindications", 
            command=lambda: self.send_preset("Check expiration and contraindications for Ibuprofen batch IBU-9942.")
        )
        btn2.pack(padx=20, pady=5, fill="x")

        btn3 = ctk.CTkButton(
            self.sidebar_frame,
            text="What needs attention? (alerts)",
            command=lambda: self.send_preset("What is expired, expiring soon, or low on stock?")
        )
        btn3.pack(padx=20, pady=5, fill="x")

        btn_new = ctk.CTkButton(
            self.sidebar_frame,
            text="New conversation",
            fg_color="#555555",
            command=self.new_conversation
        )
        btn_new.pack(padx=20, pady=(20, 5), fill="x")

        # -------------------------------------------------------------
        # Main Area: Chat & Reasoning View
        # -------------------------------------------------------------
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        # Chat Log Box
        self.chat_display = ctk.CTkTextbox(self.main_frame, state="disabled", font=ctk.CTkFont(size=14))
        self.chat_display.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=10, pady=10)

        # User Input Box
        self.input_entry = ctk.CTkEntry(
            self.main_frame, 
            placeholder_text="Ask about drug stock, expiration dates, storage rules, or interactions...",
            font=ctk.CTkFont(size=13)
        )
        self.input_entry.grid(row=1, column=0, sticky="ew", padx=(10, 5), pady=10)
        self.input_entry.bind("<Return>", lambda event: self.send_message())

        # Send Button
        self.send_button = ctk.CTkButton(
            self.main_frame, 
            text="Ask Agent", 
            width=100, 
            command=self.send_message
        )
        self.send_button.grid(row=1, column=1, sticky="e", padx=(5, 10), pady=10)

        self.append_chat_message("System", "Welcome to the Pharma AI Operations Assistant. Type a query or use quick audits to interact with the microservice.")
        threading.Thread(target=self.health_loop, daemon=True).start()

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
            self.status_badge.configure(text="● Service Online", text_color="#4CAF50")
        else:
            self.status_badge.configure(text="● Service Offline", text_color="#F44336")

    def send_preset(self, query_text: str):
        self.input_entry.delete(0, "end")
        self.input_entry.insert(0, query_text)
        self.send_message()

    def send_message(self):
        query = self.input_entry.get().strip()
        if not query:
            return

        # Display user message
        self.append_chat_message("You", query)
        self.input_entry.delete(0, "end")
        self.send_button.configure(state="disabled", text="Thinking...")

        # Run backend request asynchronously in a background thread
        threading.Thread(target=self.query_backend_thread, args=(query,), daemon=True).start()

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
                agent_answer = data.get("response", "No response content received.") + self.format_sources(data.get("citations", []))
                self.after(0, self.append_chat_message, "Pharma AI Agent", agent_answer)
            elif response.status_code == 401:
                self.after(0, self.append_chat_message, "System Error", "Login failed: set PHARMA_USER and PHARMA_PASSWORD.")
            elif response.status_code == 429:
                self.after(0, self.append_chat_message, "System Error", "Too many requests: wait a moment and try again.")
            else:
                self.after(0, self.append_chat_message, "System Error", f"Server responded with code {response.status_code}")
        except Exception as e:
            self.after(0, self.append_chat_message, "System Error", f"Could not reach API service: {str(e)}")
        finally:
            self.after(0, self.reset_send_button)

    def new_conversation(self):
        self.session_id = uuid.uuid4().hex
        self.append_chat_message("System", "Started a new conversation (the agent forgot the previous one).")

    def reset_send_button(self):
        self.send_button.configure(state="normal", text="Ask Agent")

    def append_chat_message(self, sender: str, message: str):
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", f"[{sender}]\n{message}\n\n" + "-"*60 + "\n\n")
        self.chat_display.configure(state="disabled")
        self.chat_display.see("end")

if __name__ == "__main__":
    app = PharmaDesktopApp()
    app.mainloop()