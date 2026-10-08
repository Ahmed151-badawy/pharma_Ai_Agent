import customtkinter as ctk
import requests
import threading

# Set dark theme and modern blue accent
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class PharmaDesktopApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Pharma AI Operations & Compliance Dashboard")
        self.geometry("1000x650")
        self.backend_url = "http://127.0.0.1:8000/api/v1/chat"

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
            text="● Service Online (Port 8000)", 
            text_color="#4CAF50",
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

    def query_backend_thread(self, query: str):
        try:
            response = requests.post(
                self.backend_url, 
                json={"query": query}, 
                timeout=45
            )
            if response.status_code == 200:
                data = response.json()
                agent_answer = data.get("response", "No response content received.")
                self.after(0, self.append_chat_message, "Pharma AI Agent", agent_answer)
            else:
                self.after(0, self.append_chat_message, "System Error", f"Server responded with code {response.status_code}")
        except Exception as e:
            self.after(0, self.append_chat_message, "System Error", f"Could not reach API service: {str(e)}")
        finally:
            self.after(0, self.reset_send_button)

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