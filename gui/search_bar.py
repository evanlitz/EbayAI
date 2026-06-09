import customtkinter as ctk


class SearchBar(ctk.CTkFrame):
    def __init__(self, master, on_search, **kwargs):
        super().__init__(master, **kwargs)
        self.on_search = on_search

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)

        self.entry = ctk.CTkEntry(
            self,
            placeholder_text='Search eBay — e.g. "best deal on airpods pro under $150"',
            height=40,
            font=ctk.CTkFont(size=14),
        )
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.entry.bind("<Return>", self._on_enter)

        self.button = ctk.CTkButton(
            self,
            text="Search",
            width=100,
            height=40,
            font=ctk.CTkFont(size=14),
            command=self._fire,
        )
        self.button.grid(row=0, column=1)

        self._query_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray60"),
            anchor="w",
        )
        self._query_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))

    def _on_enter(self, _event):
        self._fire()

    def _fire(self):
        text = self.entry.get().strip()
        if text:
            self.on_search(text)

    def set_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.entry.configure(state=state)
        self.button.configure(state=state)

    def get_text(self) -> str:
        return self.entry.get().strip()

    def set_query_display(self, text: str):
        if text:
            self._query_label.configure(text=f'Searched eBay for: "{text}"')
        else:
            self._query_label.configure(text="")
