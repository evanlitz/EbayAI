import threading
import webbrowser
from io import BytesIO

import requests
import customtkinter as ctk
from PIL import Image

from ebay.models import Item
from llm.auction_score import (
    compute_auction_score, compute_auction_breakdown,
    auction_score_to_stars, hours_remaining,
)

_SCORE_COLORS = {5: "#22c55e", 4: "#84cc16", 3: "#eab308", 2: "#f97316", 1: "#ef4444"}
_IMG_SIZE = (160, 160)

# Bid competition palette
_BID_COLORS = {
    "none":     ("#22c55e", "#16a34a"),   # 0 bids — pure opportunity
    "low":      ("#84cc16", "#65a30d"),   # 1-3 bids
    "moderate": ("#eab308", "#a16207"),   # 4-8 bids
    "high":     ("#f97316", "#c2410c"),   # 9-14 bids
    "hot":      ("#ef4444", "#b91c1c"),   # 15+ bids
}

_TIER_COLORS: dict[str, str] = {
    "authentic": "#22c55e", "psa graded": "#22c55e", "bgs graded": "#22c55e",
    "deadstock": "#22c55e", "sealed": "#22c55e", "certified refurb": "#22c55e",
    "swingman": "#84cc16", "raw": "#84cc16", "near-ds": "#84cc16",
    "fan": "#eab308", "lot": "#eab308", "used": "#eab308",
    "replica": "#ef4444", "reprint": "#ef4444", "parts only": "#ef4444",
    "unknown": "#6b7280", "standard": "#6b7280", "quality": "#6b7280",
}


def _bid_level(count: int) -> str:
    if count == 0:   return "none"
    if count <= 3:   return "low"
    if count <= 8:   return "moderate"
    if count <= 14:  return "high"
    return "hot"


def _bid_label(count: int) -> str:
    if count == 0:   return "NO BIDS"
    if count == 1:   return "1 BID"
    return f"{count} BIDS"


def _fmt_hours(h: float | None) -> str:
    if h is None:
        return "—"
    if h <= 0:
        return "ENDED"
    if h < 1:
        m = int(h * 60)
        return f"{m}m"
    if h < 24:
        whole = int(h)
        mins = int((h - whole) * 60)
        return f"{whole}h {mins:02d}m" if mins else f"{whole}h"
    return f"{h / 24:.1f}d"


def _time_color(h: float | None) -> str:
    if h is None or h <= 0:
        return "#6b7280"
    if h < 2:
        return "#ef4444"
    if h < 12:
        return "#f97316"
    if h < 48:
        return "#eab308"
    return "#6b7280"


def _fmt_ship(cost) -> str:
    if cost is None:
        return "Calc."
    if cost == 0.0:
        return "Free"
    return f"${cost:.2f}"


def _sep(parent, row: int, col: int = 0, colspan: int = 2):
    ctk.CTkFrame(parent, height=1, fg_color=("gray75", "gray35")).grid(
        row=row, column=col, columnspan=colspan, sticky="ew", pady=(6, 4))


class _AuctionRow(ctk.CTkFrame):
    """Single accordion row for an auction item."""

    def __init__(
        self, master, *, item: Item, rank: int,
        market_data, all_items: list, annotation: dict = None,
        on_expand=None, **kwargs
    ):
        self._item = item
        self._rank = rank
        self._market_data = market_data
        self._all_items = all_items
        self._annotation = annotation or {}
        self._on_expand = on_expand
        self._expanded = False
        self._detail_panel = None
        self._ctk_img = None
        self._img_label = None
        self._chevron = None
        self._accent_bar = None
        self._ann_badge_lbl = None
        self._detail_ann_badge = None
        self._detail_ann_note = None
        self._vision_verdict_lbl = None
        self._vision_content = None
        self._pending_vision: dict | None = None
        self._time_lbl = None
        self._time_badge = None
        self._tick_after_id = None

        self._score = compute_auction_score(item, market_data, all_items)
        self._stars = auction_score_to_stars(self._score)
        self._accent_color = _SCORE_COLORS[self._stars]

        bid = item.currentBidPrice or item.price
        self._bid = bid
        count = item.bidCount or 0
        self._bid_count = count
        self._bid_level = _bid_level(count)

        if rank == 1:
            self._bg = ("#dcfce7", "#14532d")
        elif rank % 2 == 0:
            self._bg = ("gray92", "gray17")
        else:
            self._bg = ("gray98", "gray14")

        kwargs.setdefault("fg_color", self._bg)
        kwargs["corner_radius"] = 0
        super().__init__(master, **kwargs)
        self.columnconfigure(0, weight=1)
        self._build_header()
        self._start_tick()

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=self._bg, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.columnconfigure(7, weight=1)
        self._hdr = hdr

        # Col 0: accent bar — color = auction score quality
        self._accent_bar = ctk.CTkFrame(hdr, width=5, fg_color=self._accent_color, corner_radius=0)
        self._accent_bar.grid(row=0, column=0, sticky="ns", padx=(0, 8), pady=0)

        # Col 1: rank
        ctk.CTkLabel(
            hdr, text=f"#{self._rank}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray50", "gray55"),
            width=26, anchor="w",
        ).grid(row=0, column=1, padx=(0, 6), pady=(5, 5), sticky="w")

        # Col 2: current bid — HERO number, large, accent colored
        ctk.CTkLabel(
            hdr, text=f"${self._bid:.2f}",
            font=ctk.CTkFont(family="Consolas", size=17, weight="bold"),
            text_color=self._accent_color,
            width=96, anchor="w",
        ).grid(row=0, column=2, padx=(0, 6), pady=(5, 5), sticky="w")

        # Col 3: bid count — colored badge by competition level
        bid_lbl = _bid_label(self._bid_count)
        bid_fg, _ = _BID_COLORS[self._bid_level]
        ctk.CTkLabel(
            hdr,
            text=f" {bid_lbl} ",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="white",
            fg_color=bid_fg,
            corner_radius=4,
            width=72, anchor="center",
        ).grid(row=0, column=3, padx=(0, 6), pady=(5, 5), sticky="w")

        # Col 4: vs market % — only when market data available
        if self._market_data and self._market_data.median > 0:
            pct = (self._bid - self._market_data.median) / self._market_data.median * 100
            sign = "+" if pct >= 0 else ""
            mkt_text = f"{sign}{pct:.0f}%"
            mkt_color = "#22c55e" if pct < 0 else "#f97316"
            ctk.CTkLabel(
                hdr, text=mkt_text,
                font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
                text_color=mkt_color,
                width=54, anchor="w",
            ).grid(row=0, column=4, padx=(0, 6), pady=(5, 5), sticky="w")
        else:
            ctk.CTkFrame(hdr, width=54, fg_color="transparent").grid(row=0, column=4)

        # Col 5: time remaining — color by urgency
        h = hours_remaining(self._item)
        time_color = _time_color(h)
        self._time_lbl = ctk.CTkLabel(
            hdr, text=_fmt_hours(h),
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color=time_color,
            width=66, anchor="w",
        )
        self._time_lbl.grid(row=0, column=5, padx=(0, 6), pady=(5, 5), sticky="w")

        # Col 6: tier badge (populated after annotations arrive; empty/transparent until then)
        tier = self._annotation.get("tier", "")
        tc = _TIER_COLORS.get(tier.lower(), "#6b7280") if tier else "#6b7280"
        self._ann_badge_lbl = ctk.CTkLabel(
            hdr,
            text=f" {tier} " if tier else "",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="white",
            fg_color=tc if tier else "transparent",
            corner_radius=4,
            width=80, anchor="center",
        )
        self._ann_badge_lbl.grid(row=0, column=6, padx=(0, 6), pady=(5, 5), sticky="w")

        # Col 7: title (flex)
        title_text = self._item.title[:88] + ("…" if len(self._item.title) > 88 else "")
        ctk.CTkLabel(
            hdr, text=title_text,
            font=ctk.CTkFont(size=12),
            anchor="w",
        ).grid(row=0, column=7, padx=(0, 4), pady=(5, 5), sticky="ew")

        # Col 8: chevron
        self._chevron = ctk.CTkLabel(
            hdr, text="▼",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray55"),
            width=24, anchor="e",
        )
        self._chevron.grid(row=0, column=8, padx=(0, 8), pady=(5, 5), sticky="e")

        self._bind_header_click(hdr)

    def _bind_header_click(self, widget):
        widget.configure(cursor="hand2")
        widget.bind("<Button-1>", lambda e: self.toggle())
        for child in widget.winfo_children():
            try:
                child.configure(cursor="hand2")
            except Exception:
                pass
            child.bind("<Button-1>", lambda e: self.toggle())
            for gc in child.winfo_children():
                try:
                    gc.configure(cursor="hand2")
                except Exception:
                    pass
                gc.bind("<Button-1>", lambda e: self.toggle())

    # ------------------------------------------------------------------
    # Live countdown
    # ------------------------------------------------------------------

    def _start_tick(self):
        self._tick_after_id = self.after(60_000, self._tick_time)

    def _tick_time(self):
        if not self.winfo_exists():
            return
        h = hours_remaining(self._item)
        if self._time_lbl and self._time_lbl.winfo_exists():
            self._time_lbl.configure(
                text=_fmt_hours(h),
                text_color=_time_color(h),
            )
        if h is not None and h > 0:
            self._tick_after_id = self.after(60_000, self._tick_time)

    # ------------------------------------------------------------------
    # Expand / collapse
    # ------------------------------------------------------------------

    def toggle(self):
        if self._expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self):
        if self._expanded:
            return
        if self._on_expand:
            self._on_expand(self)
        self._expanded = True
        if self._chevron:
            self._chevron.configure(text="▲")
        if self._detail_panel is None:
            self._build_detail()
        self._detail_panel.grid(row=1, column=0, sticky="nsew")

    def collapse(self):
        if not self._expanded:
            return
        self._expanded = False
        if self._chevron:
            self._chevron.configure(text="▼")
        if self._detail_panel is not None:
            self._detail_panel.grid_forget()

    # ------------------------------------------------------------------
    # Detail panel
    # ------------------------------------------------------------------

    def _build_detail(self):
        dp = ctk.CTkFrame(self, fg_color=("gray94", "gray16"), corner_radius=0)
        dp.columnconfigure(1, weight=1)
        self._detail_panel = dp

        self._img_label = ctk.CTkLabel(
            dp, text="Loading\nimage...",
            width=_IMG_SIZE[0], height=_IMG_SIZE[1],
            fg_color=("gray82", "gray22"),
            corner_radius=8,
            font=ctk.CTkFont(size=11),
        )
        self._img_label.grid(row=0, column=0, rowspan=50, padx=(12, 8), pady=(12, 12), sticky="n")

        right = ctk.CTkFrame(dp, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(0, 12), pady=(10, 10))
        right.columnconfigure(0, minsize=110, weight=0)
        right.columnconfigure(1, weight=1)

        r = self._populate_auction_hero(right, 0)
        r = self._populate_annotation(right, r)
        r = self._populate_vision_check(right, r)
        r = self._populate_info(right, r)
        r = self._populate_score(right, r)
        r = self._populate_buttons(right, r)

        if self._pending_vision is not None:
            pv = self._pending_vision
            self._pending_vision = None
            self.after(0, lambda: self.update_vision_result(pv))

        if self._item.imageUrl:
            threading.Thread(
                target=self._load_image,
                args=(self._img_label, self._item.imageUrl),
                daemon=True,
            ).start()
        else:
            self._img_label.configure(text="No image")

    def _populate_auction_hero(self, parent, r: int) -> int:
        """Top section: the key auction numbers — bid, competition, time."""
        hero = ctk.CTkFrame(parent, fg_color=("gray88", "gray20"), corner_radius=8)
        hero.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        hero.columnconfigure(0, weight=1)
        hero.columnconfigure(1, weight=1)
        hero.columnconfigure(2, weight=1)
        r += 1

        # Current bid
        bid_col = ctk.CTkFrame(hero, fg_color="transparent")
        bid_col.grid(row=0, column=0, padx=12, pady=(10, 10), sticky="w")
        ctk.CTkLabel(
            bid_col, text="CURRENT BID",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("gray50", "gray55"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            bid_col, text=f"${self._bid:.2f}",
            font=ctk.CTkFont(family="Consolas", size=24, weight="bold"),
            text_color=self._accent_color,
            anchor="w",
        ).pack(anchor="w")

        if self._market_data and self._market_data.median > 0:
            pct = (self._bid - self._market_data.median) / self._market_data.median * 100
            sign = "+" if pct >= 0 else ""
            mkt_color = "#22c55e" if pct < 0 else "#f97316"
            ctk.CTkLabel(
                bid_col,
                text=f"{sign}{pct:.0f}% vs ${self._market_data.median:.0f} median",
                font=ctk.CTkFont(size=11),
                text_color=mkt_color,
                anchor="w",
            ).pack(anchor="w", pady=(2, 0))

        # Bid competition
        comp_col = ctk.CTkFrame(hero, fg_color="transparent")
        comp_col.grid(row=0, column=1, padx=8, pady=(10, 10))
        ctk.CTkLabel(
            comp_col, text="BIDS",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("gray50", "gray55"),
        ).pack()
        bid_fg, _ = _BID_COLORS[self._bid_level]
        ctk.CTkLabel(
            comp_col, text=str(self._bid_count),
            font=ctk.CTkFont(family="Consolas", size=28, weight="bold"),
            text_color=bid_fg,
        ).pack()
        level_labels = {
            "none": "No competition",
            "low": "Low competition",
            "moderate": "Contested",
            "high": "Heavily contested",
            "hot": "HOT — very active",
        }
        ctk.CTkLabel(
            comp_col,
            text=level_labels[self._bid_level],
            font=ctk.CTkFont(size=10),
            text_color=bid_fg,
        ).pack()

        # Time remaining
        h = hours_remaining(self._item)
        time_col = ctk.CTkFrame(hero, fg_color="transparent")
        time_col.grid(row=0, column=2, padx=12, pady=(10, 10), sticky="e")
        ctk.CTkLabel(
            time_col, text="TIME LEFT",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("gray50", "gray55"),
        ).pack()
        ctk.CTkLabel(
            time_col, text=_fmt_hours(h),
            font=ctk.CTkFont(family="Consolas", size=22, weight="bold"),
            text_color=_time_color(h),
        ).pack()
        if self._item.itemEndDate:
            end_str = self._item.itemEndDate[:10]
            ctk.CTkLabel(
                time_col, text=f"Ends {end_str}",
                font=ctk.CTkFont(size=10),
                text_color=("gray50", "gray55"),
            ).pack()

        return r

    def _populate_annotation(self, parent, r: int) -> int:
        tier = self._annotation.get("tier", "")
        note = self._annotation.get("note", "")
        flags = self._annotation.get("flags", [])
        if not tier and not note:
            return r

        tc = _TIER_COLORS.get(tier.lower(), "#6b7280") if tier else "#6b7280"
        ann_frame = ctk.CTkFrame(parent, fg_color="transparent")
        ann_frame.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ann_frame.columnconfigure(1, weight=1)

        self._detail_ann_badge = ctk.CTkLabel(
            ann_frame,
            text=f" {tier} " if tier else " — ",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="white",
            fg_color=tc,
            corner_radius=4,
        )
        self._detail_ann_badge.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self._detail_ann_note = ctk.CTkLabel(
            ann_frame, text=note or "",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
            anchor="w", wraplength=360, justify="left",
        )
        self._detail_ann_note.grid(row=0, column=1, sticky="ew")

        if flags:
            flag_lbl = ctk.CTkLabel(
                parent,
                text="  ".join(flags),
                font=ctk.CTkFont(size=10),
                text_color="#f97316",
                anchor="w", wraplength=380, justify="left",
            )
            flag_lbl.grid(row=r + 1, column=0, columnspan=2, sticky="w", pady=(0, 4))
            r += 1

        _sep(parent, r + 1)
        return r + 2

    def _populate_vision_check(self, parent, r: int) -> int:
        hdr_row = ctk.CTkFrame(parent, fg_color="transparent")
        hdr_row.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(2, 0))

        ctk.CTkLabel(
            hdr_row, text="VISUAL CHECK",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray45", "gray55"), anchor="w",
        ).pack(side="left")

        self._vision_verdict_lbl = ctk.CTkLabel(
            hdr_row, text="",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="white", fg_color="transparent",
            corner_radius=4,
        )
        self._vision_verdict_lbl.pack(side="left", padx=(8, 0))

        self._vision_content = ctk.CTkFrame(parent, fg_color="transparent")
        self._vision_content.grid(row=r + 1, column=0, columnspan=2, sticky="ew")

        import os
        placeholder = "Analyzing image..." if os.getenv("VISION_MODEL") else "Vision model not configured"
        ctk.CTkLabel(
            self._vision_content, text=placeholder,
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray60"), anchor="w",
        ).pack(anchor="w")

        _sep(parent, r + 2)
        return r + 3

    _VERDICT_COLORS = {
        "likely_authentic": "#22c55e",
        "caution":          "#eab308",
        "likely_replica":   "#ef4444",
        "inconclusive":     "#6b7280",
    }
    _VERDICT_LABELS = {
        "likely_authentic": "LIKELY AUTHENTIC",
        "caution":          "CAUTION",
        "likely_replica":   "LIKELY REPLICA",
        "inconclusive":     "INCONCLUSIVE",
    }

    def update_vision_result(self, result: dict):
        if self._vision_content is None or not self._vision_content.winfo_exists():
            self._pending_vision = result
            return

        for w in self._vision_content.winfo_children():
            w.destroy()

        verdict = result.get("verdict", "inconclusive")
        confidence = result.get("confidence", "low")
        flags = result.get("flags", [])
        positive = result.get("positive_signals", [])
        notes = result.get("notes", "")

        color = self._VERDICT_COLORS.get(verdict, "#6b7280")
        label = self._VERDICT_LABELS.get(verdict, verdict.upper())

        if self._vision_verdict_lbl and self._vision_verdict_lbl.winfo_exists():
            self._vision_verdict_lbl.configure(text=f" {label} ", fg_color=color)

        for flag in flags:
            row = ctk.CTkFrame(self._vision_content, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text="!", font=ctk.CTkFont(size=11, weight="bold"),
                         text_color="#f97316", width=14, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=flag, font=ctk.CTkFont(size=11),
                         text_color=("gray35", "gray65"), anchor="w",
                         wraplength=310, justify="left").pack(side="left", fill="x", expand=True)

        for sig in positive:
            row = ctk.CTkFrame(self._vision_content, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text="*", font=ctk.CTkFont(size=11),
                         text_color="#22c55e", width=14, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=sig, font=ctk.CTkFont(size=11),
                         text_color=("gray35", "gray65"), anchor="w",
                         wraplength=310, justify="left").pack(side="left", fill="x", expand=True)

        conf_text = f"Confidence: {confidence}"
        if notes:
            conf_text += f" — {notes}"
        ctk.CTkLabel(
            self._vision_content, text=conf_text,
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray60"),
            anchor="w", wraplength=350, justify="left",
        ).pack(anchor="w", pady=(4, 0))

    def _populate_info(self, parent, r: int) -> int:
        ship_str = _fmt_ship(self._item.shippingCost)
        rows_data = [
            ("Condition", self._item.condition or "—", False),
            ("Seller",    f"{self._item.sellerFeedbackPct:.1f}%  ({self._item.sellerFeedbackScore:,} ratings)", False),
            ("Top Rated", "Yes" if self._item.topRated else "No", False),
            ("Returns",   "Accepted" if self._item.returnsAccepted else "Not accepted", False),
            ("Shipping",  ship_str, False),
        ]
        if self._market_data and self._market_data.median > 0:
            rows_data.append((
                "Market median",
                f"${self._market_data.median:.0f}  ({self._market_data.sample_size} recent sales)",
                False,
            ))

        for label, value, mono in rows_data:
            ctk.CTkLabel(
                parent, text=label + ":",
                font=ctk.CTkFont(size=12, weight="bold"),
                anchor="w", width=110,
            ).grid(row=r, column=0, sticky="w", pady=2)
            ctk.CTkLabel(
                parent, text=value,
                font=ctk.CTkFont(family="Consolas" if mono else None, size=12),
                anchor="w", wraplength=360, justify="left",
            ).grid(row=r, column=1, sticky="w", padx=(6, 0), pady=2)
            r += 1

        _sep(parent, r)
        return r + 1

    def _populate_score(self, parent, r: int) -> int:
        breakdown = compute_auction_breakdown(self._item, self._market_data, self._all_items)
        total = breakdown.get("total", 0.0)
        ctk.CTkLabel(
            parent, text=f"AUCTION SCORE  {total:.2f}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray45", "gray55"),
            anchor="w",
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(0, 4))
        r += 1

        for comp in breakdown.get("components", []):
            pct = f"{int(comp['weight'] * 100)}%"
            ctk.CTkLabel(
                parent, text=f"{comp['label']}  {pct}",
                font=ctk.CTkFont(size=11),
                anchor="w", width=120,
            ).grid(row=r, column=0, sticky="w", pady=2)

            wrap = ctk.CTkFrame(parent, fg_color="transparent")
            wrap.grid(row=r, column=1, sticky="w", padx=(4, 0), pady=2)
            bar = ctk.CTkProgressBar(wrap, width=90, height=8)
            bar.set(comp["score"])
            bar.pack(side="left")

            note_txt = f"  {comp['score']:.2f}"
            if comp.get("note"):
                note_txt += f"  {comp['note']}"
            ctk.CTkLabel(
                wrap, text=note_txt,
                font=ctk.CTkFont(size=10),
                text_color=("gray40", "gray60"),
            ).pack(side="left")
            r += 1

        _sep(parent, r)
        return r + 1

    def _populate_buttons(self, parent, r: int) -> int:
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.grid(row=r, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ctk.CTkButton(
            btn_frame, text="Open on eBay ->", height=32,
            font=ctk.CTkFont(size=12),
            command=lambda: webbrowser.open(self._item.itemWebURL, new=2) if self._item.itemWebURL else None,
        ).pack(side="left", padx=(0, 8))
        return r + 1

    def _load_image(self, label, url: str):
        try:
            resp = requests.get(url, timeout=8)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            img.thumbnail(_IMG_SIZE, Image.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self._ctk_img = ctk_img
            if label.winfo_exists():
                self.after(0, lambda: label.configure(image=ctk_img, text=""))
        except Exception:
            if label.winfo_exists():
                self.after(0, lambda: label.configure(text="Image\nunavailable"))

    def set_annotation(self, annotation: dict):
        self._annotation = annotation or {}
        tier = self._annotation.get("tier", "")
        tc = _TIER_COLORS.get(tier.lower(), "#6b7280") if tier else "#6b7280"
        if self._ann_badge_lbl and self._ann_badge_lbl.winfo_exists():
            self._ann_badge_lbl.configure(
                text=f" {tier} " if tier else "",
                fg_color=tc if tier else "transparent",
            )
        if self._detail_ann_badge and self._detail_ann_badge.winfo_exists():
            self._detail_ann_badge.configure(
                text=f" {tier} " if tier else " — ", fg_color=tc)
        if self._detail_ann_note and self._detail_ann_note.winfo_exists():
            note = self._annotation.get("note", "")
            self._detail_ann_note.configure(text=note or "")

    def set_market_data(self, market_data, all_items: list):
        self._market_data = market_data
        self._all_items = all_items
        self._score = compute_auction_score(self._item, market_data, all_items)
        new_stars = auction_score_to_stars(self._score)
        if new_stars != self._stars:
            self._stars = new_stars
            self._accent_color = _SCORE_COLORS[self._stars]
            if self._accent_bar and self._accent_bar.winfo_exists():
                self._accent_bar.configure(fg_color=self._accent_color)

    @property
    def item_id(self) -> str:
        return self._item.itemId


# ===========================================================================


class AuctionList(ctk.CTkFrame):
    """Accordion auction results widget — mirrors ResultsList public API."""

    def __init__(self, master, on_row_expand=None, **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)
        self._on_row_expand = on_row_expand

        self._rows: list[_AuctionRow] = []
        self._items: list[Item] = []
        self._market_data = None
        self._annotations: dict = {}
        self._expanded_id: str = ""
        self._pending_load = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", label_text="")
        self._scroll.grid(row=0, column=0, sticky="nsew")
        self._scroll.columnconfigure(0, weight=1)
        self._scroll.update_idletasks()

    def load(self, items, market_data=None, annotations=None):
        self._items = list(items)
        self._market_data = market_data
        if annotations is not None:
            self._annotations = annotations
        if self._pending_load is not None:
            try:
                self.after_cancel(self._pending_load)
            except Exception:
                pass
        self._pending_load = self.after(0, self._do_load)

    def _do_load(self):
        self._pending_load = None
        restore_id = self._expanded_id

        for row in self._rows:
            if row.winfo_exists():
                row.destroy()
        self._rows.clear()
        self._expanded_id = ""

        for rank, item in enumerate(self._items, start=1):
            row = _AuctionRow(
                self._scroll,
                item=item,
                rank=rank,
                market_data=self._market_data,
                all_items=self._items,
                annotation=self._annotations.get(item.itemId, {}),
                on_expand=self._on_row_expanded,
            )
            row.grid(row=rank - 1, column=0, sticky="ew", pady=1)
            self._rows.append(row)

        if restore_id:
            for row in self._rows:
                if row.item_id == restore_id:
                    row.expand()
                    break

    def _on_row_expanded(self, expanding_row: _AuctionRow):
        if self._expanded_id and self._expanded_id != expanding_row.item_id:
            for row in self._rows:
                if row.item_id == self._expanded_id:
                    row.collapse()
                    break
        self._expanded_id = expanding_row.item_id
        if self._on_row_expand:
            self._on_row_expand(expanding_row._item)

    def update_vision(self, item_id: str, result: dict):
        for row in self._rows:
            if row.item_id == item_id and row.winfo_exists():
                row.update_vision_result(result)
                return

    def update_annotations(self, annotations: dict):
        self._annotations = annotations or {}
        for row in self._rows:
            if row.winfo_exists():
                row.set_annotation(self._annotations.get(row.item_id, {}))

    def update_market_data(self, market_data):
        self._market_data = market_data
        for row in self._rows:
            if row.winfo_exists():
                row.set_market_data(market_data, self._items)

    def clear(self):
        self.load([])

    def expand_item(self, item_id: str):
        for row in self._rows:
            if row.item_id == item_id and row.winfo_exists():
                row.expand()
                return
