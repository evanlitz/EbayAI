import customtkinter as ctk

# Each chip: (label, filter_spec)
# filter_spec keys understood by _apply_auction_filter in app.py:
#   time_max_hours  — keep only items ending within N hours
#   bids_max        — keep only items with <= N bids
#   sort_by         — "time" (soonest first) | "score" (default, highest score first)
AUCTION_CHIPS = [
    ("All",           {}),
    ("Ending <2h",    {"time_max_hours": 2}),
    ("Today",         {"time_max_hours": 12}),
    ("No Bids",       {"bids_max": 0}),
    ("Fewest Bids",   {"sort_by": "bids"}),
    ("Sort: End Time",{"sort_by": "time"}),
]

_ACTIVE_COLOR  = ("#1d6ae5", "#1d6ae5")
_INACTIVE_COLOR = ("gray75", "gray30")


class AuctionFilterChips(ctk.CTkFrame):
    def __init__(self, master, on_filter, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._on_filter = on_filter
        self._buttons: list[ctk.CTkButton] = []
        self._active = 0

        for i, (label, _) in enumerate(AUCTION_CHIPS):
            width = 110 if "Time" in label else (96 if "Bids" in label else 80)
            btn = ctk.CTkButton(
                self,
                text=label,
                width=width,
                height=28,
                font=ctk.CTkFont(size=12),
                corner_radius=14,
                command=lambda idx=i: self._select(idx),
            )
            btn.pack(side="left", padx=(0, 6))
            self._buttons.append(btn)

        self._refresh_colors()

    def _select(self, idx: int):
        self._active = idx
        self._refresh_colors()
        self._on_filter(AUCTION_CHIPS[idx][1])

    def _refresh_colors(self):
        for i, btn in enumerate(self._buttons):
            btn.configure(fg_color=_ACTIVE_COLOR if i == self._active else _INACTIVE_COLOR)

    def set_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for btn in self._buttons:
            btn.configure(state=state)

    def reset(self):
        self._active = 0
        self._refresh_colors()
