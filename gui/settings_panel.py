import customtkinter as ctk
import config


class SettingsPanel(ctk.CTkFrame):
    """In-app settings panel — replaces SettingsWindow popup."""

    def __init__(self, master, on_save=None, on_cancel=None, **kwargs):
        kwargs.setdefault("fg_color", ("gray95", "gray14"))
        super().__init__(master, **kwargs)
        self._on_save = on_save
        self._on_cancel = on_cancel

        self.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="SETTINGS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray50", "gray55"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(20, 12))

        # ZIP Code
        ctk.CTkLabel(
            self, text="ZIP Code",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 2))

        ctk.CTkLabel(
            self,
            text="Calculates shipping and surfaces nearby listings.",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray55"),
            anchor="w",
            wraplength=270,
            justify="left",
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(0, 6))

        settings = config.load()

        zip_row = ctk.CTkFrame(self, fg_color="transparent")
        zip_row.grid(row=3, column=0, sticky="w", padx=16, pady=(0, 4))

        self._zip_entry = ctk.CTkEntry(zip_row, placeholder_text="e.g. 90210", width=130)
        self._zip_entry.insert(0, settings.get("zip_code", ""))
        self._zip_entry.pack(side="left")

        self._zip_error = ctk.CTkLabel(
            zip_row, text="",
            font=ctk.CTkFont(size=11),
            text_color="#ef4444",
        )
        self._zip_error.pack(side="left", padx=(8, 0))

        # Slack Webhook
        ctk.CTkLabel(
            self, text="Slack Webhook URL",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).grid(row=4, column=0, sticky="w", padx=16, pady=(16, 2))

        ctk.CTkLabel(
            self,
            text="Incoming Webhook from api.slack.com — watch alerts are posted here.",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray55"),
            anchor="w",
            wraplength=270,
            justify="left",
        ).grid(row=5, column=0, sticky="w", padx=16, pady=(0, 6))

        self._webhook_entry = ctk.CTkEntry(
            self,
            placeholder_text="https://hooks.slack.com/services/...",
            width=280,
        )
        self._webhook_entry.insert(0, settings.get("slack_webhook", ""))
        self._webhook_entry.grid(row=6, column=0, sticky="w", padx=16, pady=(0, 4))

        self._webhook_error = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=11),
            text_color="#ef4444",
            anchor="w",
        )
        self._webhook_error.grid(row=7, column=0, sticky="w", padx=16)

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=8, column=0, sticky="w", padx=16, pady=(20, 16))

        ctk.CTkButton(btn_frame, text="Save", width=90, command=self._save).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            btn_frame, text="Cancel", width=90,
            fg_color="transparent", border_width=1,
            command=self._cancel,
        ).pack(side="left")

        self._zip_entry.bind("<Return>", lambda e: self._save())

    def _save(self):
        zip_code = self._zip_entry.get().strip()
        if zip_code and (not zip_code.isdigit() or len(zip_code) != 5):
            self._zip_error.configure(text="Must be a 5-digit ZIP")
            return
        self._zip_error.configure(text="")

        webhook = self._webhook_entry.get().strip()
        if webhook and not webhook.startswith("https://hooks.slack.com/"):
            self._webhook_error.configure(text="Must be a hooks.slack.com URL")
            return
        self._webhook_error.configure(text="")

        settings = config.load()
        settings["zip_code"] = zip_code
        settings["slack_webhook"] = webhook
        config.save(settings)

        if self._on_save:
            self._on_save(settings)
        self._cancel()

    def _cancel(self):
        if self._on_cancel:
            self._on_cancel()

    def refresh(self):
        """Reload values from disk (called when panel is shown)."""
        settings = config.load()
        self._zip_entry.delete(0, "end")
        self._zip_entry.insert(0, settings.get("zip_code", ""))
        self._webhook_entry.delete(0, "end")
        self._webhook_entry.insert(0, settings.get("slack_webhook", ""))
        self._zip_error.configure(text="")
        self._webhook_error.configure(text="")
