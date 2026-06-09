import time
import webbrowser
import customtkinter as ctk
import watches.db as watches_db
import watches.auction_db as auction_db


def _fmt_time(ts: float) -> str:
    if ts == 0:
        return "never"
    delta = time.time() - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


def _fmt_next(watch) -> str:
    if not watch.enabled:
        return "paused"
    due_in = (watch.last_checked_at + watch.interval_seconds) - time.time()
    if due_in <= 0:
        return "soon"
    if due_in < 60:
        return f"{int(due_in)}s"
    return f"{int(due_in / 60)}m"


_STAR_COLORS = {
    5: "#22c55e", 4: "#22c55e",
    3: "#eab308",
    2: "#ef4444", 1: "#ef4444",
}


class WatchesPanel(ctk.CTkFrame):
    """In-app watches and notifications panel — replaces WatchesWindow popup."""

    def __init__(self, master, on_change=None, **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)
        self._on_change = on_change

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self, text="WATCHES & NOTIFICATIONS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray50", "gray55"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(12, 6))

        self._tabs = ctk.CTkTabview(self, anchor="nw")
        self._tabs.grid(row=1, column=0, sticky="nsew")
        self._tabs.add("Active Watches")
        self._tabs.add("Auction Watches")
        self._tabs.add("Notifications")

        self._build_watches_tab(self._tabs.tab("Active Watches"))
        self._build_auction_watches_tab(self._tabs.tab("Auction Watches"))
        self._build_notifications_tab(self._tabs.tab("Notifications"))

    # ------------------------------------------------------------------
    # Watches tab
    # ------------------------------------------------------------------

    def _build_watches_tab(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        self._watches_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent", label_text="")
        self._watches_scroll.columnconfigure(0, weight=1)
        self._watches_scroll.grid(row=0, column=0, sticky="nsew")

    def _refresh_watches(self):
        for w in self._watches_scroll.winfo_children():
            w.destroy()

        watches = watches_db.get_all_watches()
        if not watches:
            ctk.CTkLabel(
                self._watches_scroll,
                text="No watches yet. Run a search and click 'Add to Watches' to create one.",
                font=ctk.CTkFont(size=12),
                text_color=("gray50", "gray60"),
                wraplength=500,
            ).grid(row=0, column=0, pady=24)
            return

        self._watches_scroll.columnconfigure(0, weight=1)
        for i, watch in enumerate(watches):
            self._add_watch_row(i, watch)

    def _add_watch_row(self, row_idx: int, watch):
        bg = ("gray92", "gray17") if row_idx % 2 == 0 else ("gray96", "gray14")
        row = ctk.CTkFrame(self._watches_scroll, fg_color=bg, corner_radius=6)
        row.grid(row=row_idx, column=0, sticky="ew", pady=2, padx=2)
        row.columnconfigure(0, weight=1)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 2))
        info.columnconfigure(0, weight=1)

        # Name + dot
        name_row = ctk.CTkFrame(info, fg_color="transparent")
        name_row.grid(row=0, column=0, sticky="ew")
        dot_color = "#22c55e" if watch.enabled else "#94a3b8"
        ctk.CTkLabel(name_row, text="●", text_color=dot_color,
                     font=ctk.CTkFont(size=10)).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(name_row, text=watch.name,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     anchor="w").pack(side="left")

        # Details
        stars_str = "★" * watch.min_stars + "☆" * (5 - watch.min_stars)
        price_str = f"  ·  max ${watch.price_max:.0f}" if watch.price_max else ""
        interval_min = watch.interval_seconds // 60
        details = (
            f"min {stars_str}{price_str}  ·  every {interval_min}m  ·  "
            f"checked {_fmt_time(watch.last_checked_at)}  ·  next {_fmt_next(watch)}"
        )
        ctk.CTkLabel(info, text=details,
                     font=ctk.CTkFont(size=11),
                     text_color=("gray45", "gray60"),
                     anchor="w").grid(row=1, column=0, sticky="w")

        # Action buttons
        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.grid(row=0, column=1, padx=(0, 8), pady=4)

        toggle_label = "Pause" if watch.enabled else "Resume"
        ctk.CTkButton(
            btn_frame, text=toggle_label, width=80, height=28,
            font=ctk.CTkFont(size=12),
            fg_color="transparent", border_width=1,
            command=lambda wid=watch.id: self._toggle(wid),
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            btn_frame, text="Delete", width=64, height=28,
            font=ctk.CTkFont(size=12),
            fg_color="transparent", border_width=1,
            text_color=("#dc2626", "#f87171"),
            border_color=("#dc2626", "#f87171"),
            hover_color=("#fee2e2", "#3f1010"),
            command=lambda wid=watch.id: self._delete(wid),
        ).pack(side="left")

    def _toggle(self, watch_id: str):
        watches_db.toggle_enabled(watch_id)
        self._refresh_watches()
        if self._on_change:
            self._on_change()

    def _delete(self, watch_id: str):
        watches_db.delete_watch(watch_id)
        self._refresh_watches()
        if self._on_change:
            self._on_change()

    # ------------------------------------------------------------------
    # Auction Watches tab
    # ------------------------------------------------------------------

    def _build_auction_watches_tab(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        self._auction_watches_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent", label_text="")
        self._auction_watches_scroll.columnconfigure(0, weight=1)
        self._auction_watches_scroll.grid(row=0, column=0, sticky="nsew")

    def _refresh_auction_watches(self):
        for w in self._auction_watches_scroll.winfo_children():
            w.destroy()

        watches = auction_db.get_all_auction_watches()
        if not watches:
            ctk.CTkLabel(
                self._auction_watches_scroll,
                text="No auction watches yet. Run an auction search and click '+ Add as Watch'.",
                font=ctk.CTkFont(size=12),
                text_color=("gray50", "gray60"),
                wraplength=500,
            ).grid(row=0, column=0, pady=24)
            return

        self._auction_watches_scroll.columnconfigure(0, weight=1)
        for i, watch in enumerate(watches):
            self._add_auction_watch_row(i, watch)

    def _add_auction_watch_row(self, row_idx: int, watch):
        bg = ("gray92", "gray17") if row_idx % 2 == 0 else ("gray96", "gray14")
        row = ctk.CTkFrame(self._auction_watches_scroll, fg_color=bg, corner_radius=6)
        row.grid(row=row_idx, column=0, sticky="ew", pady=2, padx=2)
        row.columnconfigure(0, weight=1)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 2))
        info.columnconfigure(0, weight=1)

        name_row = ctk.CTkFrame(info, fg_color="transparent")
        name_row.grid(row=0, column=0, sticky="ew")
        dot_color = "#22c55e" if watch.enabled else "#94a3b8"
        ctk.CTkLabel(name_row, text="●", text_color=dot_color,
                     font=ctk.CTkFont(size=10)).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(name_row, text=watch.name,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     anchor="w").pack(side="left")

        price_str = f"  ·  max ${watch.price_max:.0f}" if watch.price_max else ""
        interval_min = watch.interval_seconds // 60
        snipe_min = watch.snipe_interval_seconds // 60
        alerts = []
        if watch.alert_new_listing:
            alerts.append("new listing")
        if watch.alert_ending_soon:
            alerts.append(f"ending <{watch.ending_window_hours}h")
        alert_str = ", ".join(alerts) if alerts else "no alerts"
        details = (
            f"poll {interval_min}m  ·  snipe {snipe_min}m{price_str}  ·  "
            f"{alert_str}  ·  checked {_fmt_time(watch.last_checked_at)}"
        )
        ctk.CTkLabel(info, text=details,
                     font=ctk.CTkFont(size=11),
                     text_color=("gray45", "gray60"),
                     anchor="w").grid(row=1, column=0, sticky="w")

        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.grid(row=0, column=1, padx=(0, 8), pady=4)

        toggle_label = "Pause" if watch.enabled else "Resume"
        ctk.CTkButton(
            btn_frame, text=toggle_label, width=80, height=28,
            font=ctk.CTkFont(size=12),
            fg_color="transparent", border_width=1,
            command=lambda wid=watch.id: self._toggle_auction(wid),
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            btn_frame, text="Delete", width=64, height=28,
            font=ctk.CTkFont(size=12),
            fg_color="transparent", border_width=1,
            text_color=("#dc2626", "#f87171"),
            border_color=("#dc2626", "#f87171"),
            hover_color=("#fee2e2", "#3f1010"),
            command=lambda wid=watch.id: self._delete_auction(wid),
        ).pack(side="left")

    def _toggle_auction(self, watch_id: str):
        auction_db.toggle_enabled(watch_id)
        self._refresh_auction_watches()
        if self._on_change:
            self._on_change()

    def _delete_auction(self, watch_id: str):
        auction_db.delete_auction_watch(watch_id)
        self._refresh_auction_watches()
        if self._on_change:
            self._on_change()

    # ------------------------------------------------------------------
    # Notifications tab
    # ------------------------------------------------------------------

    def _build_notifications_tab(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        self._notif_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent", label_text="")
        self._notif_scroll.columnconfigure(0, weight=1)
        self._notif_scroll.grid(row=0, column=0, sticky="nsew")

        btn_row = ctk.CTkFrame(tab, fg_color="transparent")
        btn_row.grid(row=1, column=0, sticky="e", pady=(4, 0))
        ctk.CTkButton(
            btn_row, text="Dismiss all", width=100, height=28,
            font=ctk.CTkFont(size=12),
            fg_color="transparent", border_width=1,
            command=self._dismiss_all,
        ).pack()

    def _refresh_notifications(self):
        for w in self._notif_scroll.winfo_children():
            w.destroy()

        notifs = watches_db.get_notifications(limit=60)
        if not notifs:
            ctk.CTkLabel(
                self._notif_scroll,
                text="No notifications yet.",
                font=ctk.CTkFont(size=12),
                text_color=("gray50", "gray60"),
            ).grid(row=0, column=0, pady=24)
            return

        self._notif_scroll.columnconfigure(0, weight=1)
        for idx, notif in enumerate(notifs):
            self._add_notif_row(idx, notif)

    def _add_notif_row(self, row_idx: int, notif: dict):
        dismissed = notif.get("dismissed", 0)
        bg = ("gray92", "gray17") if row_idx % 2 == 0 else ("gray96", "gray14")
        row = ctk.CTkFrame(self._notif_scroll, fg_color=bg, corner_radius=6)
        row.grid(row=row_idx, column=0, sticky="ew", pady=2, padx=2)
        row.columnconfigure(1, weight=1)

        stars = notif.get("stars", 1)
        star_text = "★" * stars + "☆" * (5 - stars)
        item = notif.get("item", {})
        price = item.get("totalCost", 0)
        title = item.get("title", "")[:70]
        url = item.get("itemWebURL", "")
        watch_name = notif.get("watch_name", "")
        age = _fmt_time(notif.get("created_at", 0))
        star_color = _STAR_COLORS.get(stars, "#6b7280")
        text_color = ("gray60", "gray50") if dismissed else ("gray10", "gray90")

        ctk.CTkLabel(
            row, text=star_text,
            font=ctk.CTkFont(size=13),
            text_color=star_color, width=70, anchor="w",
        ).grid(row=0, column=0, padx=(8, 4), pady=(6, 2), sticky="w")

        ctk.CTkLabel(
            row, text=f"${price:.2f}  —  {title}",
            font=ctk.CTkFont(size=12),
            text_color=text_color, anchor="w",
        ).grid(row=0, column=1, sticky="ew", padx=4, pady=(6, 2))

        ctk.CTkLabel(
            row, text=f"{watch_name}  ·  {age}",
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray55"), anchor="w",
        ).grid(row=1, column=1, sticky="w", padx=4, pady=(0, 4))

        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.grid(row=0, column=2, rowspan=2, padx=(4, 8), pady=4)

        if url:
            ctk.CTkButton(
                btn_frame, text="Open", width=64, height=26,
                font=ctk.CTkFont(size=12),
                command=lambda u=url: webbrowser.open(u, new=2),
            ).pack(pady=(0, 3))

        if not dismissed:
            ctk.CTkButton(
                btn_frame, text="x", width=30, height=26,
                font=ctk.CTkFont(size=12),
                fg_color="transparent", border_width=1,
                command=lambda nid=notif["id"]: self._dismiss(nid),
            ).pack()

    def _dismiss(self, notif_id: str):
        watches_db.dismiss_notification(notif_id)
        self._refresh_notifications()

    def _dismiss_all(self):
        for n in watches_db.get_notifications(limit=200):
            if not n.get("dismissed"):
                watches_db.dismiss_notification(n["id"])
        self._refresh_notifications()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def refresh(self):
        """Call when the panel becomes visible."""
        self._refresh_watches()
        self._refresh_auction_watches()
        self._refresh_notifications()
