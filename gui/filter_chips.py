import customtkinter as ctk

CHIPS = [
    ("All",           {}),
    ("New",           {"condition": "NEW"}),
    ("Used",          {"condition": "USED"}),
    ("Free Shipping", {"free_shipping_only": True}),
    ("Returns",       {"returns_only": True}),
]

_ACTIVE_COLOR = ("#1d6ae5", "#1d6ae5")
_INACTIVE_COLOR = ("gray75", "gray30")


class FilterChips(ctk.CTkFrame):
    def __init__(self, master, on_filter, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._on_filter = on_filter
        self._buttons: list[ctk.CTkButton] = []
        self._active = 0

        for i, (label, _) in enumerate(CHIPS):
            btn = ctk.CTkButton(
                self,
                text=label,
                width=100 if label == "Free Shipping" else 72,
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
        self._on_filter(CHIPS[idx][1])

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
