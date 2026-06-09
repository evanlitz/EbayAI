import webbrowser
import customtkinter as ctk
import watches.auction_db as auction_db
from gui.tooltips import make_help_btn


def _open_url(url: str):
    if not url:
        return
    webbrowser.open(url, new=2)


class AuctionPanel(ctk.CTkFrame):
    """Left sidebar for auction mode — mirrors AIPanel structure."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.status_label = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray60"),
            anchor="w",
        )
        self.status_label.grid(row=0, column=0, sticky="ew", padx=2, pady=(2, 0))

        self.textbox = ctk.CTkTextbox(
            self, font=ctk.CTkFont(size=13), wrap="word", state="disabled")
        self.textbox.grid(row=1, column=0, sticky="nsew", padx=2, pady=(4, 4))

        self._rec_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._rec_scroll.grid(row=1, column=0, sticky="nsew", padx=2, pady=(4, 4))
        self._rec_scroll.update_idletasks()
        self._rec_scroll.grid_forget()

        followup_frame = ctk.CTkFrame(self, fg_color="transparent")
        followup_frame.grid(row=2, column=0, sticky="ew", padx=2, pady=(0, 2))
        followup_frame.columnconfigure(0, weight=1)

        self.followup_entry = ctk.CTkEntry(
            followup_frame,
            placeholder_text='Narrow — e.g. "ending today" or "under $30"',
            height=36,
            font=ctk.CTkFont(size=13),
        )
        self.followup_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.followup_btn = ctk.CTkButton(
            followup_frame, text="Refine", width=80, height=36, state="disabled")
        self.followup_btn.grid(row=0, column=1)

        # Watch form (hidden until show_watch_form is called)
        self._watch_form = ctk.CTkFrame(self, fg_color=("gray90", "gray18"), corner_radius=8)

        fi = ctk.CTkFrame(self._watch_form, fg_color="transparent")
        fi.pack(fill="x", padx=10, pady=(8, 4))
        fi.columnconfigure(1, weight=1)

        _nf = ctk.CTkFrame(fi, fg_color="transparent")
        _nf.grid(row=0, column=0, sticky="w", pady=(0, 4))
        ctk.CTkLabel(_nf, text="Name", font=ctk.CTkFont(size=12), anchor="w").pack(side="left")
        make_help_btn(_nf, "Label for this watch.\nShown in Slack alert messages.").pack(side="left", padx=(3, 0))
        self._wf_name = ctk.CTkEntry(fi, placeholder_text="friendly label")
        self._wf_name.grid(row=0, column=1, columnspan=3, sticky="ew", pady=(0, 4))

        ctk.CTkLabel(fi, text="Search", font=ctk.CTkFont(size=12), anchor="w",
                     width=68).grid(row=1, column=0, sticky="w", pady=(0, 4))
        self._wf_query_label = ctk.CTkLabel(
            fi, text="", font=ctk.CTkFont(size=11),
            text_color=("gray45", "gray60"), anchor="w", wraplength=200,
        )
        self._wf_query_label.grid(row=1, column=1, columnspan=3, sticky="w", pady=(0, 4))

        _mf = ctk.CTkFrame(fi, fg_color="transparent")
        _mf.grid(row=2, column=0, sticky="w")
        ctk.CTkLabel(_mf, text="Max $", font=ctk.CTkFont(size=12), anchor="w").pack(side="left")
        make_help_btn(_mf, "Skip items above this bid.\nLeave blank for no limit.").pack(side="left", padx=(3, 0))
        self._wf_price = ctk.CTkEntry(fi, placeholder_text="optional", width=80)
        self._wf_price.grid(row=2, column=1, sticky="w")

        _pf = ctk.CTkFrame(fi, fg_color="transparent")
        _pf.grid(row=2, column=2, sticky="w", padx=(10, 0))
        ctk.CTkLabel(_pf, text="Poll (min)", font=ctk.CTkFont(size=12), anchor="w").pack(side="left")
        make_help_btn(_pf, "Minutes between normal checks.\nDefault: 30").pack(side="left", padx=(3, 0))
        self._wf_interval = ctk.CTkEntry(fi, placeholder_text="30", width=50)
        self._wf_interval.grid(row=2, column=3, sticky="w")

        _sf = ctk.CTkFrame(fi, fg_color="transparent")
        _sf.grid(row=3, column=0, sticky="w", pady=(6, 0))
        ctk.CTkLabel(_sf, text="Snipe (min)", font=ctk.CTkFont(size=12), anchor="w").pack(side="left")
        make_help_btn(_sf, "Fast-check interval when any item\nends within the End window.\nDefault: 5").pack(side="left", padx=(3, 0))
        self._wf_snipe = ctk.CTkEntry(fi, placeholder_text="5", width=50)
        self._wf_snipe.grid(row=3, column=1, sticky="w", pady=(6, 0))

        _ef = ctk.CTkFrame(fi, fg_color="transparent")
        _ef.grid(row=3, column=2, sticky="w", padx=(10, 0), pady=(6, 0))
        ctk.CTkLabel(_ef, text="End window (h)", font=ctk.CTkFont(size=12), anchor="w").pack(side="left")
        make_help_btn(_ef, "Hours-to-end threshold where Poll\nswitches to Snipe interval.\nDefault: 12").pack(side="left", padx=(3, 0))
        self._wf_window = ctk.CTkEntry(fi, placeholder_text="12", width=50)
        self._wf_window.grid(row=3, column=3, sticky="w", pady=(6, 0))

        alerts_row = ctk.CTkFrame(fi, fg_color="transparent")
        alerts_row.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self._wf_alert_new = ctk.BooleanVar(value=True)
        self._wf_alert_soon = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(alerts_row, text="New listing alerts",
                        variable=self._wf_alert_new,
                        font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 3))
        make_help_btn(alerts_row, "Alert when a new matching\nauction appears.").pack(side="left", padx=(0, 10))
        ctk.CTkCheckBox(alerts_row, text="Ending soon alerts",
                        variable=self._wf_alert_soon,
                        font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 3))
        make_help_btn(alerts_row, "Alert when a tracked auction\nenters the end window.").pack(side="left")

        self._wf_error = ctk.CTkLabel(
            self._watch_form, text="", font=ctk.CTkFont(size=11),
            text_color="#ef4444", anchor="w",
        )
        self._wf_error.pack(fill="x", padx=10, pady=(0, 2))

        wf_btns = ctk.CTkFrame(self._watch_form, fg_color="transparent")
        wf_btns.pack(anchor="w", padx=10, pady=(0, 8))
        ctk.CTkButton(wf_btns, text="Save Watch", width=100, height=28,
                      font=ctk.CTkFont(size=12),
                      command=self._save_watch).pack(side="left", padx=(0, 8))
        ctk.CTkButton(wf_btns, text="Cancel", width=80, height=28,
                      font=ctk.CTkFont(size=12),
                      fg_color="transparent", border_width=1,
                      command=self._close_watch_form).pack(side="left")

        self._watch_params: dict = {}
        self._watch_on_save = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    _INTRO_TEXT = (
        "AUCTION SNIPING\n\n"
        "Search for any item above to find live auctions.\n\n"
        "Snipe Score weights:\n"
        "  Value vs market   40%  — bid vs sold median\n"
        "  Time opportunity  30%  — <2h = prime window\n"
        "  Seller            15%  — feedback & Top Rated\n"
        "  Bid competition   10%  — fewer bids = better\n"
        "  Condition          5%\n\n"
        "Use the filter chips to narrow by end time or bid count.\n"
        "The refine box below accepts plain English: \"ending today\", "
        "\"no bids\", \"sort by time\"."
    )

    def show_intro(self):
        self._show_textbox()
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.insert("end", self._INTRO_TEXT)
        self.textbox.configure(state="disabled")

    def set_status(self, text: str):
        self.status_label.configure(text=text)

    def set_text(self, text: str):
        self._show_textbox()
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.insert("end", text)
        self.textbox.configure(state="disabled")

    def set_loading_text(self, text: str):
        self._show_textbox()
        self.set_text(text)

    def set_snipe(self, data: dict, item_lookup: dict = None, score_data: dict = None):
        """Render snipe pick + runner-up cards. data has 'snipe' and 'runner_up' keys."""
        self._show_rec_scroll()
        for w in self._rec_scroll.winfo_children():
            w.destroy()

        snipe = data.get("snipe")
        runner_up = data.get("runner_up")

        if not snipe:
            self._show_textbox()
            self.set_text("Analysis complete — see ranked results in the list.")
            return

        self._build_pick_card(self._rec_scroll, "Best Snipe", snipe, item_lookup,
                              header_color="#22c55e",
                              breakdown=(score_data or {}).get((snipe or {}).get("itemId", "")))
        if runner_up and runner_up.get("itemId"):
            sep = ctk.CTkFrame(self._rec_scroll, height=1, fg_color=("gray70", "gray40"))
            sep.pack(fill="x", pady=8)
            self._build_pick_card(self._rec_scroll, "Runner Up", runner_up, item_lookup,
                                  header_color="#84cc16",
                                  breakdown=(score_data or {}).get(runner_up.get("itemId", "")))

    def _build_pick_card(self, parent, header: str, pick: dict, item_lookup,
                         header_color: str, breakdown: dict = None):
        card = ctk.CTkFrame(parent, fg_color=("gray95", "gray18"), corner_radius=8)
        card.pack(fill="x", padx=4, pady=4)
        card.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card, text=header,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=header_color, anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 2))

        item_id = pick.get("itemId", "")
        item = (item_lookup or {}).get(item_id)
        title = item.title if item else item_id
        url = item.itemWebURL if item else None

        ctk.CTkLabel(
            card, text=title[:72] + ("…" if len(title) > 72 else ""),
            font=ctk.CTkFont(size=12),
            anchor="w", wraplength=260, justify="left",
        ).pack(fill="x", padx=10, pady=(0, 4))

        for reason in pick.get("reasons", []):
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=1)
            ctk.CTkLabel(row, text="*", font=ctk.CTkFont(size=12), width=12, anchor="w").pack(side="left")
            ctk.CTkLabel(
                row, text=reason,
                font=ctk.CTkFont(size=12),
                anchor="w", wraplength=245, justify="left",
            ).pack(side="left", fill="x", expand=True)

        caution = pick.get("caution")
        if caution:
            ctk.CTkLabel(
                card, text=f"  {caution}",
                font=ctk.CTkFont(size=11),
                text_color="#f97316",
                anchor="w", wraplength=260, justify="left",
            ).pack(fill="x", padx=10, pady=(2, 4))

        if breakdown and breakdown.get("components"):
            ctk.CTkFrame(card, height=1, fg_color=("gray75", "gray35")).pack(
                fill="x", padx=10, pady=(4, 6))

            sf = ctk.CTkFrame(card, fg_color="transparent")
            sf.pack(fill="x", padx=10, pady=(0, 4))
            sf.columnconfigure(1, weight=0)

            total = breakdown.get("total", 0.0)
            ctk.CTkLabel(sf, text=f"SCORE  {total:.2f}",
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=("gray45", "gray55"),
                         anchor="w").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 3))

            for i, comp in enumerate(breakdown["components"], start=1):
                pct_str = f"{int(comp['weight'] * 100)}%"
                ctk.CTkLabel(sf, text=f"{comp['label']} {pct_str}",
                             font=ctk.CTkFont(size=10),
                             text_color=("gray40", "gray60"),
                             anchor="w", width=120,
                             ).grid(row=i, column=0, sticky="w", pady=1)

                bar = ctk.CTkProgressBar(sf, width=80, height=7)
                bar.set(comp["score"])
                bar.grid(row=i, column=1, sticky="w", padx=(4, 4), pady=1)

                note = comp.get("note", "")
                lbl = f"{comp['score']:.2f}"
                if note:
                    lbl += f"  {note}"
                ctk.CTkLabel(sf, text=lbl,
                             font=ctk.CTkFont(size=10),
                             text_color=("gray40", "gray60"),
                             anchor="w", wraplength=130, justify="left",
                             ).grid(row=i, column=2, sticky="w", pady=1)

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(4, 8))
        if url:
            ctk.CTkButton(btn_row, text="Open on eBay ->", height=30,
                          font=ctk.CTkFont(size=12),
                          command=lambda u=url: _open_url(u),
                          ).pack(side="left")

    def _show_textbox(self):
        self._rec_scroll.grid_forget()
        self.textbox.grid(row=1, column=0, sticky="nsew", padx=2, pady=(4, 4))

    def _show_rec_scroll(self):
        self.textbox.grid_forget()
        self._rec_scroll.grid(row=1, column=0, sticky="nsew", padx=2, pady=(4, 4))

    def show_watch_form(self, human_query: str, params: dict, on_save=None):
        self._watch_params = params
        self._watch_on_save = on_save
        self._wf_name.delete(0, "end")
        self._wf_name.insert(0, human_query[:60])
        self._wf_query_label.configure(text=params.get("q_refined") or params.get("q", ""))
        self._wf_price.delete(0, "end")
        self._wf_interval.delete(0, "end")
        self._wf_snipe.delete(0, "end")
        self._wf_window.delete(0, "end")
        self._wf_alert_new.set(True)
        self._wf_alert_soon.set(True)
        self._wf_error.configure(text="")
        self._watch_form.grid(row=3, column=0, sticky="ew", padx=2, pady=(4, 4))
        self._wf_name.focus()

    def hide_watch_form(self):
        self._watch_form.grid_forget()

    def _close_watch_form(self):
        self._watch_form.grid_forget()

    def _save_watch(self):
        name = self._wf_name.get().strip()
        if not name:
            self._wf_error.configure(text="Name is required.")
            return

        price_raw = self._wf_price.get().strip()
        price_max = None
        if price_raw:
            try:
                price_max = float(price_raw.lstrip("$"))
            except ValueError:
                self._wf_error.configure(text="Max price must be a number.")
                return

        def _parse_int(entry, default: int) -> int | None:
            raw = entry.get().strip()
            if not raw:
                return default
            try:
                val = int(raw)
                return max(1, val)
            except ValueError:
                return None

        interval_min = _parse_int(self._wf_interval, 30)
        snipe_min = _parse_int(self._wf_snipe, 5)
        window_h = _parse_int(self._wf_window, 12)

        if interval_min is None or snipe_min is None or window_h is None:
            self._wf_error.configure(text="Intervals must be whole numbers.")
            return

        watch_id = auction_db.create_auction_watch(
            name=name,
            params=self._watch_params,
            price_max=price_max,
            interval_seconds=interval_min * 60,
            snipe_interval_seconds=snipe_min * 60,
            ending_window_hours=window_h,
            alert_new_listing=self._wf_alert_new.get(),
            alert_ending_soon=self._wf_alert_soon.get(),
        )
        self._close_watch_form()
        if self._watch_on_save:
            self._watch_on_save(watch_id)

    def clear(self):
        self._show_textbox()
        self.set_text("")
        self.set_status("")
        for w in self._rec_scroll.winfo_children():
            w.destroy()

    def set_followup_enabled(self, enabled: bool, on_submit=None):
        state = "normal" if enabled else "disabled"
        self.followup_entry.configure(state=state)
        self.followup_btn.configure(state=state)
        if on_submit:
            self.followup_btn.configure(command=on_submit)
            self.followup_entry.bind("<Return>", lambda e: on_submit())

    def get_followup_text(self) -> str:
        return self.followup_entry.get().strip()

    def clear_followup(self):
        self.followup_entry.delete(0, "end")
