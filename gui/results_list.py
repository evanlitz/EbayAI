import threading
import webbrowser
from io import BytesIO

import requests
import customtkinter as ctk
from PIL import Image

import watches.db as watches_db
from ebay.models import Item
from llm.deal_score import compute_deal_score, compute_score_breakdown, score_to_stars
from gui.tooltips import make_help_btn

_SCORE_COLORS = {5: "#22c55e", 4: "#84cc16", 3: "#eab308", 2: "#f97316", 1: "#ef4444"}

_TIER_COLORS: dict[str, str] = {
    "authentic": "#22c55e", "psa graded": "#22c55e", "bgs graded": "#22c55e",
    "deadstock": "#22c55e", "sealed": "#22c55e", "certified refurb": "#22c55e",
    "swingman": "#84cc16", "raw": "#84cc16", "near-ds": "#84cc16",
    "fan": "#eab308", "lot": "#eab308", "used": "#eab308",
    "replica": "#ef4444", "reprint": "#ef4444", "parts only": "#ef4444",
    "unknown": "#6b7280", "standard": "#6b7280", "quality": "#6b7280",
}

_IMG_SIZE = (160, 160)


def _fmt_ship(cost) -> str:
    if cost is None:
        return "Calc."
    if cost == 0.0:
        return "Free"
    return f"${cost:.2f}"


def _sep(parent, row: int, col: int = 0, colspan: int = 2):
    ctk.CTkFrame(parent, height=1, fg_color=("gray75", "gray35")).grid(
        row=row, column=col, columnspan=colspan, sticky="ew", pady=(6, 4))


class _ExpandableRow(ctk.CTkFrame):
    """Single accordion row — header always visible, detail panel built lazily on first expand."""

    def __init__(
        self, master, *, item: Item, rank: int,
        desired: dict, item_type: str, signals: dict, market_data, annotation: dict,
        params: dict, all_items: list, on_expand=None, on_watch_saved=None, **kwargs
    ):
        self._item = item
        self._rank = rank
        self._desired = desired
        self._item_type = item_type
        self._signals = signals or {}
        self._market_data = market_data
        self._annotation = annotation or {}
        self._params = params
        self._all_items = all_items
        self._on_expand = on_expand
        self._on_watch_saved = on_watch_saved
        self._expanded = False
        self._detail_panel = None
        self._ctk_img = None
        self._img_label = None
        self._ann_badge_lbl = None
        self._detail_ann_badge = None
        self._detail_ann_note = None
        self._aspects_frame = None
        self._watch_form = None
        self._watch_form_row = 0
        self._watch_stars_var = None
        self._watch_name_entry = None
        self._watch_price_entry = None
        self._watch_interval_entry = None
        self._watch_error_lbl = None
        self._watch_toggle_btn = None
        self._accent_bar = None
        self._star_lbl = None
        self._chevron = None
        self._vision_verdict_lbl = None
        self._vision_content = None
        self._pending_vision: dict | None = None

        self._deal = compute_deal_score(
            item, self._signals.get(item.itemId),
            market_data, all_items or [], desired=desired,
        )
        self._stars = score_to_stars(self._deal)
        self._accent_color = _SCORE_COLORS[self._stars]

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

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=self._bg, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.columnconfigure(6, weight=1)
        self._hdr = hdr

        self._accent_bar = ctk.CTkFrame(hdr, width=4, fg_color=self._accent_color, corner_radius=0)
        self._accent_bar.grid(row=0, column=0, sticky="ns", padx=(0, 6), pady=0)

        self._star_lbl = ctk.CTkLabel(
            hdr,
            text="★" * self._stars + "☆" * (5 - self._stars),
            font=ctk.CTkFont(size=13),
            text_color=self._accent_color,
            width=68, anchor="w",
        )
        self._star_lbl.grid(row=0, column=1, padx=(0, 2), pady=(5, 5), sticky="w")

        ctk.CTkLabel(
            hdr, text=f"#{self._rank}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray50", "gray55"),
            width=28, anchor="w",
        ).grid(row=0, column=2, padx=(0, 4), pady=(5, 5), sticky="w")

        ctk.CTkLabel(
            hdr, text=f"${self._item.totalCost:.2f}",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            width=78, anchor="w",
        ).grid(row=0, column=3, padx=(0, 4), pady=(5, 5), sticky="w")

        cond = (self._item.condition or "")[:14]
        ctk.CTkLabel(
            hdr, text=cond,
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray65"),
            width=100, anchor="w",
        ).grid(row=0, column=4, padx=(0, 4), pady=(5, 5), sticky="w")

        tier = self._annotation.get("tier", "")
        tc = _TIER_COLORS.get(tier.lower(), "#6b7280") if tier else "#6b7280"
        self._ann_badge_lbl = ctk.CTkLabel(
            hdr,
            text=f" {tier} " if tier else "",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="white",
            fg_color=tc if tier else "transparent",
            corner_radius=4,
            width=88, anchor="w",
        )
        self._ann_badge_lbl.grid(row=0, column=5, padx=(0, 6), pady=(5, 5), sticky="w")

        title_text = self._item.title[:85] + ("…" if len(self._item.title) > 85 else "")
        ctk.CTkLabel(
            hdr, text=title_text,
            font=ctk.CTkFont(size=12),
            anchor="w",
        ).grid(row=0, column=6, padx=(0, 4), pady=(5, 5), sticky="ew")

        self._chevron = ctk.CTkLabel(
            hdr, text="▼",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray55"),
            width=24, anchor="e",
        )
        self._chevron.grid(row=0, column=7, padx=(0, 8), pady=(5, 5), sticky="e")

        # Bind click on all header children — CTkLabel doesn't propagate Button-1
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
    # Detail panel (lazy build)
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
        right.columnconfigure(0, minsize=88, weight=0)
        right.columnconfigure(1, weight=1)
        self._right_frame = right

        r = self._populate_info(right, 0)
        r = self._populate_annotation(right, r)
        r = self._populate_vision_check(right, r)
        r = self._populate_score(right, r)
        r = self._populate_attributes(right, r)
        r = self._populate_buttons(right, r)
        self._populate_watch_form(right, r)

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

    def _populate_info(self, parent, r: int) -> int:
        ship_str = _fmt_ship(self._item.shippingCost)
        buying = ", ".join(self._item.buyingOptions) if self._item.buyingOptions else "—"
        rows = [
            ("Total",     f"${self._item.totalCost:.2f}", True),
            ("Price",     f"${self._item.price:.2f}",     True),
            ("Shipping",  ship_str,                        False),
            ("Condition", self._item.condition or "—",    False),
            ("Seller",    f"{self._item.sellerFeedbackPct:.1f}%  ({self._item.sellerFeedbackScore:,} ratings)", False),
            ("Top Rated", "Yes" if self._item.topRated else "No", False),
            ("Returns",   "Accepted" if self._item.returnsAccepted else "Not accepted", False),
            ("Buying",    buying, False),
        ]
        if self._item.itemEndDate:
            rows.append(("Ends", self._item.itemEndDate[:10], False))

        for label, value, mono in rows:
            ctk.CTkLabel(
                parent, text=label + ":",
                font=ctk.CTkFont(size=12, weight="bold"),
                anchor="w", width=88,
            ).grid(row=r, column=0, sticky="w", pady=2)
            ctk.CTkLabel(
                parent, text=value,
                font=ctk.CTkFont(family="Consolas" if mono else None, size=12),
                anchor="w", wraplength=360, justify="left",
            ).grid(row=r, column=1, sticky="w", padx=(6, 0), pady=2)
            r += 1

        _sep(parent, r)
        return r + 1

    def _populate_annotation(self, parent, r: int) -> int:
        tier = self._annotation.get("tier", "")
        tc = _TIER_COLORS.get(tier.lower(), "#6b7280") if tier else "#6b7280"

        ann_frame = ctk.CTkFrame(parent, fg_color="transparent")
        ann_frame.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(2, 6))
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

        note = self._annotation.get("note", "")
        self._detail_ann_note = ctk.CTkLabel(
            ann_frame, text=note or "No classification yet.",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
            anchor="w", wraplength=380, justify="left",
        )
        self._detail_ann_note.grid(row=0, column=1, sticky="ew")

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

    def _populate_score(self, parent, r: int) -> int:
        breakdown = compute_score_breakdown(
            self._item,
            self._signals.get(self._item.itemId),
            self._market_data,
            self._all_items or [],
            self._desired,
        )
        total = breakdown.get("total", 0.0)
        ctk.CTkLabel(
            parent, text=f"SCORE  {total:.2f}",
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
                anchor="w", width=88,
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

    def _populate_attributes(self, parent, r: int) -> int:
        ctk.CTkLabel(
            parent, text="ITEM ATTRIBUTES",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray45", "gray55"),
            anchor="w",
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(0, 2))
        r += 1

        self._aspects_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._aspects_frame.grid(row=r, column=0, columnspan=2, sticky="ew")
        self._aspects_frame.columnconfigure(0, minsize=90, weight=0)
        self._aspects_frame.columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self._aspects_frame, text="Loading attributes...",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray60"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        _sep(parent, r + 1)
        return r + 2

    def _populate_buttons(self, parent, r: int) -> int:
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.grid(row=r, column=0, columnspan=2, sticky="w", pady=(0, 4))

        ctk.CTkButton(
            btn_frame, text="Open on eBay →", height=32,
            font=ctk.CTkFont(size=12),
            command=lambda: webbrowser.open(self._item.itemWebURL, new=2) if self._item.itemWebURL else None,
        ).pack(side="left", padx=(0, 8))

        self._watch_toggle_btn = ctk.CTkButton(
            btn_frame, text="+ Add Watch", height=32,
            font=ctk.CTkFont(size=12),
            fg_color="transparent", border_width=1,
            command=self._toggle_watch_form,
        )
        self._watch_toggle_btn.pack(side="left")

        return r + 1

    def _populate_watch_form(self, parent, r: int):
        self._watch_form_row = r
        frm = ctk.CTkFrame(parent, fg_color=("gray88", "gray19"), corner_radius=6)
        frm.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        frm.grid_forget()
        frm.columnconfigure(1, weight=1)
        self._watch_form = frm

        ctk.CTkLabel(
            frm, text="SAVE WATCH",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray45", "gray55"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 6))

        _nf = ctk.CTkFrame(frm, fg_color="transparent")
        _nf.grid(row=1, column=0, sticky="w", padx=(10, 6), pady=3)
        ctk.CTkLabel(_nf, text="Name:", font=ctk.CTkFont(size=12, weight="bold"), anchor="w").pack(side="left")
        make_help_btn(_nf, "Label shown in Slack alerts.").pack(side="left", padx=(4, 0))
        name_val = (self._params.get("q_refined") or self._params.get("q", ""))[:60]
        self._watch_name_entry = ctk.CTkEntry(frm, placeholder_text="Watch name")
        self._watch_name_entry.insert(0, name_val)
        self._watch_name_entry.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=3)

        _pf = ctk.CTkFrame(frm, fg_color="transparent")
        _pf.grid(row=2, column=0, sticky="w", padx=(10, 6), pady=3)
        ctk.CTkLabel(_pf, text="Max price:", font=ctk.CTkFont(size=12, weight="bold"), anchor="w").pack(side="left")
        make_help_btn(_pf, "Alert only when total cost\n(price + shipping) is at or\nbelow this amount.").pack(side="left", padx=(4, 0))
        self._watch_price_entry = ctk.CTkEntry(frm, placeholder_text="e.g. 75", width=110)
        self._watch_price_entry.grid(row=2, column=1, sticky="w", padx=(0, 10), pady=3)

        _sf = ctk.CTkFrame(frm, fg_color="transparent")
        _sf.grid(row=3, column=0, sticky="w", padx=(10, 6), pady=3)
        ctk.CTkLabel(_sf, text="Min stars:", font=ctk.CTkFont(size=12, weight="bold"), anchor="w").pack(side="left")
        make_help_btn(_sf, "Minimum deal score.\n3★ = any good deal\n4★ = strong deal\n5★ = exceptional only").pack(side="left", padx=(4, 0))
        self._watch_stars_var = ctk.IntVar(value=3)
        stars_row = ctk.CTkFrame(frm, fg_color="transparent")
        stars_row.grid(row=3, column=1, sticky="w", pady=3)
        for val, label in [(3, "3 ★"), (4, "4 ★"), (5, "5 ★")]:
            ctk.CTkRadioButton(
                stars_row, text=label, value=val, variable=self._watch_stars_var,
                font=ctk.CTkFont(size=12),
            ).pack(side="left", padx=(0, 10))

        _ef = ctk.CTkFrame(frm, fg_color="transparent")
        _ef.grid(row=4, column=0, sticky="w", padx=(10, 6), pady=3)
        ctk.CTkLabel(_ef, text="Every:", font=ctk.CTkFont(size=12, weight="bold"), anchor="w").pack(side="left")
        make_help_btn(_ef, "Minutes between eBay checks.").pack(side="left", padx=(4, 0))
        int_row = ctk.CTkFrame(frm, fg_color="transparent")
        int_row.grid(row=4, column=1, sticky="w", pady=3)
        self._watch_interval_entry = ctk.CTkEntry(int_row, width=60)
        self._watch_interval_entry.insert(0, "10")
        self._watch_interval_entry.pack(side="left")
        ctk.CTkLabel(int_row, text=" minutes", font=ctk.CTkFont(size=12)).pack(side="left")

        self._watch_error_lbl = ctk.CTkLabel(
            frm, text="", font=ctk.CTkFont(size=11), text_color="#ef4444", anchor="w")
        self._watch_error_lbl.grid(row=5, column=0, columnspan=2, sticky="w", padx=10)

        save_row = ctk.CTkFrame(frm, fg_color="transparent")
        save_row.grid(row=6, column=0, columnspan=2, sticky="w", padx=10, pady=(4, 10))
        ctk.CTkButton(
            save_row, text="Save Watch", height=30,
            font=ctk.CTkFont(size=12),
            command=self._save_watch,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            save_row, text="Cancel", height=30,
            font=ctk.CTkFont(size=12),
            fg_color="transparent", border_width=1,
            command=self._toggle_watch_form,
        ).pack(side="left")

    def _toggle_watch_form(self):
        if self._watch_form is None:
            return
        if self._watch_form.winfo_ismapped():
            self._watch_form.grid_forget()
            if self._watch_toggle_btn:
                self._watch_toggle_btn.configure(text="+ Add Watch")
        else:
            self._watch_form.grid(
                row=self._watch_form_row, column=0, columnspan=2,
                sticky="ew", pady=(0, 8),
            )
            if self._watch_toggle_btn:
                self._watch_toggle_btn.configure(text="— Cancel")

    def _save_watch(self):
        name = self._watch_name_entry.get().strip()
        if not name:
            self._watch_error_lbl.configure(text="Name is required.")
            return
        price_str = self._watch_price_entry.get().strip()
        price_max = None
        if price_str:
            try:
                price_max = float(price_str)
            except ValueError:
                self._watch_error_lbl.configure(text="Max price must be a number.")
                return
        min_stars = self._watch_stars_var.get() if self._watch_stars_var else 3
        interval_str = self._watch_interval_entry.get().strip()
        try:
            interval_min = max(1, int(interval_str))
        except ValueError:
            interval_min = 10
        self._watch_error_lbl.configure(text="")
        watch_id = watches_db.create_watch(
            name=name, params=self._params,
            price_max=price_max, min_stars=min_stars,
            interval_seconds=interval_min * 60,
        )
        self._toggle_watch_form()
        if self._on_watch_saved:
            self._on_watch_saved(watch_id)

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

    # ------------------------------------------------------------------
    # Public in-place update API
    # ------------------------------------------------------------------

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
            self._detail_ann_note.configure(text=note or "No classification yet.")

    def set_market_data(self, market_data, signals: dict):
        self._market_data = market_data
        self._signals = signals or {}
        self._deal = compute_deal_score(
            self._item, self._signals.get(self._item.itemId),
            market_data, self._all_items or [], desired=self._desired,
        )
        new_stars = score_to_stars(self._deal)
        if new_stars != self._stars:
            self._stars = new_stars
            self._accent_color = _SCORE_COLORS[self._stars]
            if self._accent_bar and self._accent_bar.winfo_exists():
                self._accent_bar.configure(fg_color=self._accent_color)
            if self._star_lbl and self._star_lbl.winfo_exists():
                self._star_lbl.configure(
                    text="★" * self._stars + "☆" * (5 - self._stars),
                    text_color=self._accent_color,
                )

    def update_aspects(self, aspects: list):
        if self._aspects_frame is None or not self._aspects_frame.winfo_exists():
            return
        for w in self._aspects_frame.winfo_children():
            w.destroy()
        if not aspects:
            ctk.CTkLabel(
                self._aspects_frame, text="No attributes available.",
                font=ctk.CTkFont(size=11),
                text_color=("gray50", "gray60"), anchor="w",
            ).grid(row=0, column=0, columnspan=2, sticky="w")
            return
        self._aspects_frame.columnconfigure(0, minsize=90, weight=0)
        self._aspects_frame.columnconfigure(1, weight=1)
        for i, asp in enumerate(aspects[:25]):
            ctk.CTkLabel(
                self._aspects_frame,
                text=(asp.get("name", "") or "") + ":",
                font=ctk.CTkFont(size=11, weight="bold"),
                anchor="w", width=90,
            ).grid(row=i, column=0, sticky="w", pady=1)
            ctk.CTkLabel(
                self._aspects_frame,
                text=asp.get("value", "") or "",
                font=ctk.CTkFont(size=11),
                anchor="w", wraplength=260, justify="left",
            ).grid(row=i, column=1, sticky="w", padx=(4, 0), pady=1)

    @property
    def item_id(self) -> str:
        return self._item.itemId


# ===========================================================================


class ResultsList(ctk.CTkFrame):
    """Accordion results widget — replaces ResultsTable."""

    def __init__(self, master, on_row_expand=None, on_watch_saved=None, **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)
        self._on_row_expand = on_row_expand
        self._on_watch_saved = on_watch_saved

        self._rows: list[_ExpandableRow] = []
        self._items: list[Item] = []
        self._desired: dict = {}
        self._item_type: str = "other"
        self._signals: dict = {}
        self._market_data = None
        self._annotations: dict = {}
        self._params: dict = {}
        self._expanded_id: str = ""
        self._pending_load = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", label_text="")
        self._scroll.grid(row=0, column=0, sticky="nsew")
        self._scroll.columnconfigure(0, weight=1)
        self._scroll.update_idletasks()

    def load(
        self, items, desired=None, item_type="other",
        signals=None, market_data=None, annotations=None, params=None,
    ):
        self._items = list(items)
        self._desired = desired or {}
        self._item_type = item_type
        self._signals = signals or {}
        self._market_data = market_data
        self._annotations = annotations or {}
        self._params = params or {}
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
            ann = self._annotations.get(item.itemId, {})
            row = _ExpandableRow(
                self._scroll,
                item=item,
                rank=rank,
                desired=self._desired,
                item_type=self._item_type,
                signals=self._signals,
                market_data=self._market_data,
                annotation=ann,
                params=self._params,
                all_items=self._items,
                on_expand=self._on_row_expanded,
                on_watch_saved=self._on_watch_saved,
            )
            row.grid(row=rank - 1, column=0, sticky="ew", pady=1)
            self._rows.append(row)

        if restore_id:
            for row in self._rows:
                if row.item_id == restore_id:
                    row.expand()
                    break

    def _on_row_expanded(self, expanding_row: _ExpandableRow):
        if self._expanded_id and self._expanded_id != expanding_row.item_id:
            for row in self._rows:
                if row.item_id == self._expanded_id:
                    row.collapse()
                    break
        self._expanded_id = expanding_row.item_id
        if self._on_row_expand:
            self._on_row_expand(expanding_row._item)

    def update_annotations(self, annotations: dict):
        self._annotations = annotations or {}
        for row in self._rows:
            if row.winfo_exists():
                row.set_annotation(self._annotations.get(row.item_id, {}))

    def update_vision(self, item_id: str, result: dict):
        for row in self._rows:
            if row.item_id == item_id and row.winfo_exists():
                row.update_vision_result(result)
                return

    def update_market_data(self, market_data, signals: dict):
        self._market_data = market_data
        self._signals = signals or {}
        for row in self._rows:
            if row.winfo_exists():
                row.set_market_data(market_data, signals)

    def update_aspects(self, item_id: str, aspects: list):
        for row in self._rows:
            if row.item_id == item_id and row.winfo_exists():
                row.update_aspects(aspects)
                return

    def clear(self):
        self.load([])

    def expand_item(self, item_id: str):
        for row in self._rows:
            if row.item_id == item_id and row.winfo_exists():
                row.expand()
                return
