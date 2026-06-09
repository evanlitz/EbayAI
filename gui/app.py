import os
import queue
import threading
import customtkinter as ctk
from dotenv import load_dotenv
from llm.signals import score_items

import config
from ebay.client import EbayClient
from ebay.models import Item
import cache.db as cache_db
import watches.db as watches_db
import watches.auction_db as auction_db
import watches.notifier as notifier
from watches.monitor import WatchMonitor
from watches.auction_monitor import AuctionWatchMonitor
import llm.pipeline as pipeline
from llm.pipeline import filter_relevant
from llm.auction_score import compute_auction_score, compute_auction_breakdown, auction_score_to_stars
from llm.auction_prompts import AUCTION_RANKER_SYSTEM, AUCTION_QUERY_PARSER_SYSTEM
from .search_bar import SearchBar
from .results_list import ResultsList
from .auction_list import AuctionList
from .ai_panel import AIPanel
from .auction_panel import AuctionPanel
from .filter_chips import FilterChips
from .auction_filter_chips import AuctionFilterChips
from .settings_panel import SettingsPanel
from .watches_panel import WatchesPanel

load_dotenv()

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_NAV_SEARCH = "search"
_NAV_WATCHES = "watches"
_NAV_SETTINGS = "settings"
_NAV_AUCTIONS = "auctions"

_MSG_ITEMS = "items"
_MSG_ANALYSIS = "analysis"
_MSG_ANNOTATIONS = "annotations"
_MSG_STATUS = "status"
_MSG_ERROR = "error"
_MSG_DONE = "done"
_MSG_ITEM_ASPECTS = "item_aspects"
_MSG_MARKET_PRICE = "market_price"
_MSG_NOTIFICATION = "notification"
_MSG_AUCTION_ITEMS = "auction_items"
_MSG_AUCTION_ANALYSIS = "auction_analysis"
_MSG_AUCTION_ANNOTATIONS = "auction_annotations"
_MSG_AUCTION_DONE = "auction_done"
_MSG_VISION_RESULT = "vision_result"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("EbayAI — Find Best Deals")
        self.geometry("1280x780")
        self.minsize(960, 620)

        self._queue: queue.Queue = queue.Queue()
        self._current_items: list[Item] = []
        self._desired_attributes: dict = {}
        self._current_item_type: str = "other"
        self._current_signals: dict = {}
        self._current_market_data = None
        self._current_params: dict = {}
        self._current_annotations: dict = {}
        self._current_rank: dict = {}
        self._current_rank_item_lookup: dict = {}
        self._current_rank_score_data: dict = {}
        self._conversation: list[dict] = []
        self._ebay = _build_ebay_client()
        self._monitor: WatchMonitor | None = None
        self._auction_monitor: AuctionWatchMonitor | None = None
        self._unread_count: int = 0
        self._nav: str = _NAV_SEARCH
        # Auction state
        self._auction_items: list[Item] = []
        self._auction_market_data = None
        self._auction_params: dict = {}
        self._auction_annotations: dict = {}
        self._current_snipe: dict = {}
        self._current_snipe_item_lookup: dict = {}
        self._current_snipe_score_data: dict = {}

        self._build_layout()
        cache_db.purge_expired()
        watches_db.purge_old_seen_items()
        self._unread_count = watches_db.get_unread_count()
        self._update_watches_btn()
        self.after(100, self._poll_queue)
        self._start_monitor_if_needed()

    def _build_layout(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Top bar
        top_row = ctk.CTkFrame(self, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
        top_row.columnconfigure(0, weight=1)

        self.search_bar = SearchBar(top_row, on_search=self._on_new_search)
        self.search_bar.grid(row=0, column=0, sticky="ew")

        self._add_watch_btn = ctk.CTkButton(
            top_row, text="+ Add as Watch",
            width=120, height=36,
            fg_color="transparent", border_width=1,
            state="disabled",
            command=self._on_add_watch_btn,
        )
        self._add_watch_btn.grid(row=0, column=1, padx=(8, 0))

        self._auctions_btn = ctk.CTkButton(
            top_row, text="Auctions",
            width=84, height=36,
            fg_color="transparent", border_width=1,
            command=self._toggle_auctions,
        )
        self._auctions_btn.grid(row=0, column=2, padx=(4, 0))

        self._watches_btn = ctk.CTkButton(
            top_row, text="Watches",
            width=90, height=36,
            fg_color="transparent", border_width=1,
            command=self._toggle_watches,
        )
        self._watches_btn.grid(row=0, column=3, padx=(4, 0))

        ctk.CTkButton(
            top_row, text="Settings",
            width=84, height=36,
            fg_color="transparent", border_width=1,
            command=self._toggle_settings,
        ).grid(row=0, column=4, padx=(4, 0))

        # Filter chips — regular and auction, swapped by nav
        self.filter_chips = FilterChips(self, on_filter=self._on_chip_filter)
        self.filter_chips.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 6))

        self.auction_filter_chips = AuctionFilterChips(self, on_filter=self._on_auction_chip_filter)
        # Not gridded until _NAV_AUCTIONS

        # Main pane: fixed 320px left + flex right
        pane = ctk.CTkFrame(self, fg_color="transparent")
        pane.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 14))
        pane.columnconfigure(0, minsize=320, weight=0)
        pane.columnconfigure(1, weight=1)
        pane.rowconfigure(0, weight=1)

        # Left frame
        left_frame = ctk.CTkFrame(pane, fg_color="transparent")
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(0, weight=1)

        self.ai_panel = AIPanel(left_frame)
        self.ai_panel.grid(row=0, column=0, sticky="nsew")
        self.ai_panel.set_text(
            "Enter a search above to find the best eBay deals.\n\n"
            "The AI will analyze listings and explain which offer the best value."
        )

        self.settings_panel = SettingsPanel(
            left_frame,
            on_save=self._on_settings_save,
            on_cancel=lambda: self._set_nav(_NAV_SEARCH),
        )
        # Don't grid settings_panel yet — shown via nav

        self.auction_panel = AuctionPanel(left_frame)
        # Don't grid auction_panel yet — shown via nav

        # Right frame
        right_frame = ctk.CTkFrame(pane, fg_color="transparent")
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(0, weight=1)

        self.results_list = ResultsList(
            right_frame,
            on_row_expand=self._on_row_expand,
            on_watch_saved=self._on_watch_saved,
        )
        self.results_list.grid(row=0, column=0, sticky="nsew")

        self.auction_list = AuctionList(right_frame, on_row_expand=self._on_auction_row_expand)
        # Don't grid auction_list yet — shown via nav

        self.watches_panel = WatchesPanel(
            right_frame,
            on_change=self._on_watches_changed,
        )
        # Don't grid watches_panel yet — shown via nav

        self._left_frame = left_frame
        self._right_frame = right_frame

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    _NAV_BTN_ACTIVE   = ("#1d6ae5", "#1d6ae5")
    _NAV_BTN_INACTIVE = "transparent"

    def _set_nav(self, state: str):
        prev_nav = self._nav
        self._nav = state

        # Highlight active nav buttons
        self._auctions_btn.configure(
            fg_color=self._NAV_BTN_ACTIVE if state == _NAV_AUCTIONS else self._NAV_BTN_INACTIVE
        )

        # Swap chip row: auction chips in auction mode, regular chips otherwise
        if state == _NAV_AUCTIONS:
            self.filter_chips.grid_forget()
            self.auction_filter_chips.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 6))
        else:
            self.auction_filter_chips.grid_forget()
            self.filter_chips.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 6))

        # Left panel
        self.ai_panel.grid_forget()
        self.settings_panel.grid_forget()
        self.auction_panel.grid_forget()
        if state == _NAV_SETTINGS:
            self.settings_panel.grid(row=0, column=0, sticky="nsew")
            self.settings_panel.refresh()
        elif state == _NAV_AUCTIONS:
            self.auction_panel.grid(row=0, column=0, sticky="nsew")
            # Show intro text when entering auction mode with no results yet
            if not self._auction_items and prev_nav != _NAV_AUCTIONS:
                self.auction_panel.show_intro()
        else:
            self.ai_panel.grid(row=0, column=0, sticky="nsew")

        # Right panel
        self.results_list.grid_forget()
        self.auction_list.grid_forget()
        self.watches_panel.grid_forget()
        if state == _NAV_WATCHES:
            self.watches_panel.grid(row=0, column=0, sticky="nsew")
            self.watches_panel.refresh()
        elif state == _NAV_AUCTIONS:
            self.auction_list.grid(row=0, column=0, sticky="nsew")
        else:
            self.results_list.grid(row=0, column=0, sticky="nsew")

    def _toggle_auctions(self):
        if self._nav == _NAV_AUCTIONS:
            self._set_nav(_NAV_SEARCH)
        else:
            self._set_nav(_NAV_AUCTIONS)
            self._add_watch_btn.configure(state="disabled")

    def _toggle_watches(self):
        if self._nav == _NAV_WATCHES:
            self._set_nav(_NAV_SEARCH)
        else:
            self._unread_count = 0
            self._update_watches_btn()
            self._set_nav(_NAV_WATCHES)

    def _toggle_settings(self):
        if self._nav == _NAV_SETTINGS:
            self._set_nav(_NAV_SEARCH)
        else:
            self._set_nav(_NAV_SETTINGS)

    def _update_watches_btn(self):
        label = f"Watches ({self._unread_count})" if self._unread_count else "Watches"
        self._watches_btn.configure(text=label)

    def _on_add_watch_btn(self):
        if self._nav == _NAV_AUCTIONS:
            user_text = next(
                (m["content"] for m in reversed(self._conversation) if m["role"] == "user"), ""
            )
            self.auction_panel.show_watch_form(
                human_query=user_text or self._auction_params.get("q", ""),
                params=self._auction_params,
                on_save=self._on_auction_watch_saved,
            )
        else:
            if self._nav != _NAV_SEARCH:
                self._set_nav(_NAV_SEARCH)
            user_text = next(
                (m["content"] for m in reversed(self._conversation) if m["role"] == "user"), ""
            )
            self.ai_panel.show_watch_form(
                human_query=user_text or self._current_params.get("q", ""),
                params=self._current_params,
                on_save=self._on_watch_saved,
            )

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _on_settings_save(self, settings: dict):
        self._ebay.zip_code = settings.get("zip_code", "")

    # ------------------------------------------------------------------
    # Row expand (triggers aspect fetch)
    # ------------------------------------------------------------------

    def _on_row_expand(self, item: Item):
        if item.itemHref:
            self._run_worker(self._worker_fetch_aspects, item.itemId, item.itemHref)
        if os.getenv("VISION_MODEL") and item.imageUrl:
            item_type = self._current_params.get("item_type", "other")
            self._run_worker(
                self._worker_vision_analysis,
                item.itemId, item.imageUrl, item.title, item_type,
            )

    def _on_auction_row_expand(self, item: Item):
        if os.getenv("VISION_MODEL") and item.imageUrl:
            item_type = self._auction_params.get("item_type", "other")
            self._run_worker(
                self._worker_vision_analysis,
                item.itemId, item.imageUrl, item.title, item_type,
            )

    def _worker_fetch_aspects(self, item_id: str, href: str):
        try:
            data = self._ebay.get_item_by_href(href)
            aspects = data.get("localizedAspects", [])
            self._put((_MSG_ITEM_ASPECTS, (item_id, aspects)))
        except Exception:
            self._put((_MSG_ITEM_ASPECTS, (item_id, [])))

    def _worker_vision_analysis(self, item_id: str, image_url: str, title: str, item_type: str):
        from llm.vision import analyze_image
        try:
            result = analyze_image(image_url, item_type, title)
        except Exception as e:
            result = {
                "verdict": "inconclusive", "confidence": "low",
                "flags": [], "positive_signals": [], "notes": str(e)[:120],
            }
        self._put((_MSG_VISION_RESULT, (item_id, result)))

    def _maybe_inject_vision_caution(self, item_id: str, result: dict):
        """If vision flags the winner/runner_up, re-render the recommendation card with a caution."""
        if result.get("verdict") not in ("likely_replica", "caution"):
            return
        rank = self._current_rank
        if not rank:
            return
        winner = rank.get("winner") or {}
        runner_up = rank.get("runner_up") or {}
        if winner.get("itemId") != item_id and (not runner_up or runner_up.get("itemId") != item_id):
            return
        import copy
        updated = copy.deepcopy(rank)
        caution = self._build_vision_caution_text(result)
        if winner.get("itemId") == item_id:
            updated["winner"]["caution"] = caution
        else:
            updated["runner_up"]["caution"] = caution
        self.ai_panel.set_recommendation(
            updated,
            item_lookup=self._current_rank_item_lookup,
            on_exclude=self._on_exclude_pick,
            score_data=self._current_rank_score_data,
        )

    def _maybe_inject_vision_caution_auction(self, item_id: str, result: dict):
        """Same as above but for the auction snipe card."""
        if result.get("verdict") not in ("likely_replica", "caution"):
            return
        snipe = self._current_snipe
        if not snipe:
            return
        snipe_pick = snipe.get("snipe") or {}
        runner_up = snipe.get("runner_up") or {}
        if snipe_pick.get("itemId") != item_id and (not runner_up or runner_up.get("itemId") != item_id):
            return
        import copy
        updated = copy.deepcopy(snipe)
        caution = self._build_vision_caution_text(result)
        if snipe_pick.get("itemId") == item_id:
            updated["snipe"]["caution"] = caution
        else:
            updated["runner_up"]["caution"] = caution
        self.auction_panel.set_snipe(
            updated,
            item_lookup=self._current_snipe_item_lookup,
            score_data=self._current_snipe_score_data,
        )

    @staticmethod
    def _build_vision_caution_text(result: dict) -> str:
        verdict = result.get("verdict", "")
        label = "Replica concern" if verdict == "likely_replica" else "Authenticity caution"
        confidence = result.get("confidence", "")
        flags = result.get("flags", [])
        parts = [f"Vision: {label}"]
        if confidence:
            parts.append(f"({confidence} confidence)")
        if flags:
            parts.append("— " + "; ".join(flags[:2]))
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Chip filter
    # ------------------------------------------------------------------

    def _on_chip_filter(self, filters: dict):
        if not self._current_items:
            return
        base = self._current_items if not filters else pipeline.apply_filter(self._current_items, filters)
        self.results_list.load(
            base[:50],
            desired=self._desired_attributes,
            item_type=self._current_item_type,
            signals=self._current_signals,
            market_data=self._current_market_data,
            annotations=self._current_annotations,
            params=self._current_params,
        )

    def _on_auction_chip_filter(self, spec: dict):
        self._apply_auction_filter(spec)

    def _apply_auction_filter(self, spec: dict):
        from llm.auction_score import hours_remaining as _hr
        items = list(self._auction_items)

        if not items:
            return

        if "time_max_hours" in spec:
            h_max = spec["time_max_hours"]
            filtered = [i for i in items
                        if (h := _hr(i)) is not None and 0 < h <= h_max]
            if filtered:
                items = filtered

        if "bids_max" in spec:
            filtered = [i for i in items if (i.bidCount or 0) <= spec["bids_max"]]
            if filtered:
                items = filtered

        sort_by = spec.get("sort_by", "score")
        if sort_by == "time":
            items = sorted(items, key=lambda i: _hr(i) or float("inf"))
        elif sort_by == "bids":
            items = sorted(items, key=lambda i: i.bidCount or 0)
        # default "score" — already sorted by auction score from the worker

        self.auction_list.load(
            items[:50], market_data=self._auction_market_data,
            annotations=self._auction_annotations,
        )
        if items:
            self.after(150, lambda: self.auction_list.expand_item(items[0].itemId))

    def _on_auction_followup(self):
        text = self.auction_panel.get_followup_text().strip()
        if not text:
            return
        self.auction_panel.clear_followup()
        self.auction_panel.set_followup_enabled(False)
        self.search_bar.set_enabled(False)

        # Pattern-match common auction refinements client-side (no LLM needed)
        low = text.lower()
        spec = None
        if any(w in low for w in ("ending soon", "2 hour", "2h", "<2", "under 2")):
            spec = {"time_max_hours": 2}
        elif any(w in low for w in ("today", "12 hour", "12h", "this hour")):
            spec = {"time_max_hours": 12}
        elif any(w in low for w in ("no bid", "zero bid", "0 bid", "nobody bid")):
            spec = {"bids_max": 0}
        elif any(w in low for w in ("fewest", "least bid", "low bid")):
            spec = {"sort_by": "bids"}
        elif any(w in low for w in ("sort time", "soonest", "ending first", "time order")):
            spec = {"sort_by": "time"}
        elif any(w in low for w in ("reset", "all", "clear filter", "best score")):
            spec = {}

        if spec is not None:
            self._apply_auction_filter(spec)
            self.search_bar.set_enabled(True)
            self.auction_panel.set_followup_enabled(True, self._on_auction_followup)
            return

        # If it looks like a new search, run one
        self._run_worker(self._worker_auction_followup, text)

    def _worker_auction_followup(self, user_text: str):
        try:
            self._put((_MSG_STATUS, "Processing..."))
            action_dict = pipeline.handle_followup(
                user_text, self._auction_items, []
            )
            action = action_dict.get("action", "new_search")

            if action == "filter":
                items = pipeline.apply_filter(self._auction_items, action_dict.get("filters", {}))
                self._put((_MSG_AUCTION_ITEMS, (items, self._auction_market_data, self._auction_params)))
                self._put((_MSG_AUCTION_DONE, self._auction_params))

            elif action == "refine":
                items = pipeline.apply_refinement(
                    self._auction_items, action_dict.get("keep_only", {}),
                    annotations=self._auction_annotations,
                )
                self._put((_MSG_AUCTION_ITEMS, (items, self._auction_market_data, self._auction_params)))
                self._put((_MSG_AUCTION_DONE, self._auction_params))

            else:
                # Treat as new auction search
                self._put((_MSG_STATUS, f'New auction search for "{user_text}"...'))
                self._worker_auction_search(user_text)
        except Exception as e:
            self._put((_MSG_ERROR, str(e)))

    # ------------------------------------------------------------------
    # Search flow
    # ------------------------------------------------------------------

    def _on_new_search(self, text: str):
        self._add_watch_btn.configure(state="disabled")
        self.search_bar.set_enabled(False)
        self.search_bar.set_query_display("")

        if self._nav == _NAV_AUCTIONS:
            self._auction_items = []
            self._auction_market_data = None
            self._auction_params = {}
            self._auction_annotations = {}
            self._current_snipe = {}
            self._current_snipe_item_lookup = {}
            self._current_snipe_score_data = {}
            self.auction_list.clear()
            self.auction_panel.clear()
            self.auction_panel.hide_watch_form()
            self.auction_panel.set_followup_enabled(False)
            self.auction_panel.set_loading_text("Searching for auctions...")
            self.auction_filter_chips.reset()
            self.auction_filter_chips.set_enabled(False)
            self._run_worker(self._worker_auction_search, text)
            return

        self._conversation.clear()
        self._current_items.clear()
        self._desired_attributes = {}
        self._current_item_type = "other"
        self._current_signals = {}
        self._current_market_data = None
        self._current_params = {}
        self._current_annotations = {}
        self._current_rank = {}
        self._current_rank_item_lookup = {}
        self._current_rank_score_data = {}
        self.results_list.clear()
        self.ai_panel.clear()
        self.ai_panel.hide_watch_form()
        self.ai_panel.set_followup_enabled(False)
        self.filter_chips.reset()
        self.filter_chips.set_enabled(False)
        # Return to search nav if in watches/settings
        if self._nav not in (_NAV_SEARCH, _NAV_AUCTIONS):
            self._set_nav(_NAV_SEARCH)
        self._run_worker(self._worker_new_search, text)

    def _worker_new_search(self, user_text: str):
        try:
            self._put((_MSG_STATUS, "Parsing query..."))
            params = pipeline.parse_query(user_text)
            item_type = params.get("item_type", "other")
            q_bare = params.get("q") or params.get("q_refined", user_text)
            q_display = params.get("q_refined") or q_bare

            market_result = [None]
            market_done = threading.Event()
            if item_type != "other":
                def _do_market():
                    try:
                        cached_mp = cache_db.get_market_price(q_bare, item_type)
                        if cached_mp is not None:
                            market_result[0] = cached_mp
                        else:
                            data = self._ebay.fetch_market_price(q_bare, item_type)
                            if data is not None:
                                cache_db.set_market_price(q_bare, item_type, data)
                            market_result[0] = data
                    except Exception:
                        pass
                    finally:
                        market_done.set()
                threading.Thread(target=_do_market, daemon=True).start()
            else:
                market_done.set()

            self._put((_MSG_STATUS, f'Searching eBay for "{q_display}"...'))
            cached = cache_db.get(params)
            if cached is not None:
                raw_items = [Item(**d) for d in cached]
                self._put((_MSG_STATUS, f"Loaded {len(raw_items)} listings from cache. Filtering..."))
                items = filter_relevant(raw_items, user_text, params=params)
            else:
                raw_items = self._ebay.search(params)
                if not raw_items:
                    self._put((_MSG_ANALYSIS, "No listings found. Try broadening your search."))
                    self._put((_MSG_DONE, None))
                    return
                self._put((_MSG_STATUS, f"Found {len(raw_items)} listings. Filtering..."))
                items = filter_relevant(raw_items, user_text, params=params)
                cache_db.set(params, [i.__dict__ for i in items])

            if not items:
                self._put((_MSG_ANALYSIS, "No listings found after filtering. Try broadening your search."))
                self._put((_MSG_DONE, None))
                return

            signals = score_items(items, item_type)
            desired = params.get("desired_attributes", {})

            self._put((_MSG_ITEMS, (items, desired, item_type, signals, params)))

            self._put((_MSG_STATUS, "Fetching market price data..."))
            market_done.wait(timeout=3.0)
            market_data = market_result[0]

            if market_data is not None:
                self._put((_MSG_MARKET_PRICE, (market_data, signals)))

            # Run annotation and ranking in parallel — both are independent LLM calls.
            # Ranking proceeds without annotation context so the winner appears sooner;
            # annotation updates tier badges on the rows once complete.
            self._put((_MSG_STATUS, "Analyzing listings..."))
            history = [{"role": "user", "content": user_text}]
            ann_result = [{}]
            rec_result = [{"winner": None, "runner_up": None}]

            def _do_annotate():
                ann_result[0] = pipeline.annotate_listings(items, item_type, signals)

            def _do_rank():
                rec_result[0] = pipeline.rank_listings(
                    items, history,
                    desired_attributes=desired,
                    item_type=item_type,
                    signals=signals,
                    market_data=market_data,
                    annotations={},
                )

            ann_thread = threading.Thread(target=_do_annotate, daemon=True)
            rank_thread = threading.Thread(target=_do_rank, daemon=True)
            ann_thread.start()
            rank_thread.start()
            ann_thread.join(timeout=20.0)
            rank_thread.join(timeout=20.0)

            annotations = ann_result[0]
            self._put((_MSG_ANNOTATIONS, annotations))
            self._put((_MSG_ANALYSIS, rec_result[0]))
            self._put((_MSG_DONE, {"params": params, "user_text": user_text, "explanation": ""}))
        except Exception as e:
            self._put((_MSG_ERROR, str(e)))

    def _worker_auction_search(self, user_text: str):
        try:
            self._put((_MSG_STATUS, "Parsing auction query..."))
            params = pipeline.parse_query(user_text, system_override=AUCTION_QUERY_PARSER_SYSTEM)
            params["buying_options"] = "AUCTION"
            item_type = params.get("item_type", "other")
            q_bare = params.get("q") or params.get("q_refined", user_text)

            market_result = [None]
            market_done = threading.Event()
            if item_type != "other":
                def _do_market():
                    try:
                        cached_mp = cache_db.get_market_price(q_bare, item_type)
                        if cached_mp is not None:
                            market_result[0] = cached_mp
                        else:
                            data = self._ebay.fetch_market_price(q_bare, item_type)
                            if data is not None:
                                cache_db.set_market_price(q_bare, item_type, data)
                            market_result[0] = data
                    except Exception:
                        pass
                    finally:
                        market_done.set()
                threading.Thread(target=_do_market, daemon=True).start()
            else:
                market_done.set()

            self._put((_MSG_STATUS, f'Searching eBay auctions for "{params.get("q_refined", q_bare)}"...'))
            raw_items = self._ebay.search(params)
            if not raw_items:
                self._put((_MSG_AUCTION_ANALYSIS, {"snipe": None, "runner_up": None}))
                self._put((_MSG_AUCTION_DONE, None))
                return

            self._put((_MSG_STATUS, f"Found {len(raw_items)} auctions. Filtering..."))
            items = filter_relevant(raw_items, user_text, params=params)
            if not items:
                items = raw_items  # don't return empty if filter is too aggressive

            self._put((_MSG_STATUS, f"{len(items)} auctions after filtering. Scoring..."))
            market_done.wait(timeout=3.0)
            market_data = market_result[0]

            signals = score_items(items, item_type)

            scored = sorted(
                items,
                key=lambda i: compute_auction_score(i, market_data, raw_items),
                reverse=True,
            )

            self._put((_MSG_AUCTION_ITEMS, (scored, market_data, params)))

            if market_data is not None:
                self._put((_MSG_MARKET_PRICE, (market_data, {})))

            self._put((_MSG_STATUS, "Classifying auctions..."))
            annotations = pipeline.annotate_listings(items, item_type, signals)
            self._put((_MSG_AUCTION_ANNOTATIONS, annotations))

            self._put((_MSG_STATUS, "Picking best snipe..."))
            top = scored[:5]
            item_lookup = {i.itemId: i for i in top}
            score_data = {
                i.itemId: compute_auction_breakdown(i, market_data, top)
                for i in top
            }
            snipe_result = pipeline.rank_auctions(
                top, market_data, AUCTION_RANKER_SYSTEM,
                signals=signals, annotations=annotations,
            )
            self._put((_MSG_AUCTION_ANALYSIS, (snipe_result, item_lookup, score_data)))
            self._put((_MSG_AUCTION_DONE, params))
        except Exception as e:
            self._put((_MSG_ERROR, str(e)))

    # ------------------------------------------------------------------
    # Follow-up flow
    # ------------------------------------------------------------------

    def _on_followup(self):
        text = self.ai_panel.get_followup_text().strip()
        if not text:
            return
        self.ai_panel.clear_followup()
        self.ai_panel.set_followup_enabled(False)
        self.search_bar.set_enabled(False)
        self._run_worker(self._worker_followup, text)

    def _worker_followup(self, user_text: str):
        try:
            self._put((_MSG_STATUS, "Processing follow-up..."))
            action_dict = pipeline.handle_followup(user_text, self._current_items, self._conversation)

            if action_dict["action"] == "filter":
                items = pipeline.apply_filter(self._current_items, action_dict.get("filters", {}))
                self._put((_MSG_STATUS, f"Filtered to {len(items)} listings."))
                self._put((_MSG_ITEMS, (items, self._desired_attributes, self._current_item_type, self._current_signals, self._current_params)))
                rec = pipeline.rank_listings(
                    items, self._conversation,
                    desired_attributes=self._desired_attributes,
                    item_type=self._current_item_type,
                    signals=self._current_signals,
                    market_data=self._current_market_data,
                    annotations=self._current_annotations,
                )
                self._put((_MSG_ANALYSIS, rec))
                self._put((_MSG_DONE, {"user_text": user_text, "explanation": ""}))

            elif action_dict["action"] == "refine":
                items = pipeline.apply_refinement(
                    self._current_items,
                    action_dict.get("keep_only", {}),
                    annotations=self._current_annotations,
                )
                self._put((_MSG_STATUS, f"Refined to {len(items)} listings."))
                self._put((_MSG_ITEMS, (items, self._desired_attributes, self._current_item_type, self._current_signals, self._current_params)))
                rec = pipeline.rank_listings(
                    items, self._conversation,
                    desired_attributes=self._desired_attributes,
                    item_type=self._current_item_type,
                    signals=self._current_signals,
                    market_data=self._current_market_data,
                    annotations=self._current_annotations,
                )
                self._put((_MSG_ANALYSIS, rec))
                self._put((_MSG_DONE, {"user_text": user_text, "explanation": ""}))

            else:
                params = action_dict.get("params", {"q": user_text})
                item_type = params.get("item_type", self._current_item_type)
                desired = params.get("desired_attributes") or self._desired_attributes
                q_bare = params.get("q") or user_text
                self._put((_MSG_STATUS, f'New search for "{params.get("q", user_text)}"...'))

                market_result = [None]
                market_done = threading.Event()
                if item_type != "other":
                    def _do_market():
                        try:
                            cached_mp = cache_db.get_market_price(q_bare, item_type)
                            if cached_mp is not None:
                                market_result[0] = cached_mp
                            else:
                                data = self._ebay.fetch_market_price(q_bare, item_type)
                                if data is not None:
                                    cache_db.set_market_price(q_bare, item_type, data)
                                market_result[0] = data
                        except Exception:
                            pass
                        finally:
                            market_done.set()
                    threading.Thread(target=_do_market, daemon=True).start()
                else:
                    market_done.set()

                cached = cache_db.get(params)
                if cached is not None:
                    items = [Item(**d) for d in cached]
                else:
                    raw_items = self._ebay.search(params)
                    items = filter_relevant(raw_items, user_text, params=params)
                    cache_db.set(params, [i.__dict__ for i in items])
                signals = score_items(items, item_type)
                self._put((_MSG_ITEMS, (items, desired, item_type, signals, params)))

                self._put((_MSG_STATUS, "Fetching market price data..."))
                market_done.wait(timeout=3.0)
                market_data = market_result[0]
                self._put((_MSG_MARKET_PRICE, (market_data, signals)))

                self._put((_MSG_STATUS, "Classifying listings..."))
                annotations = pipeline.annotate_listings(items, item_type, signals)
                self._put((_MSG_ANNOTATIONS, annotations))

                self._put((_MSG_STATUS, "Picking best deal..."))
                rec = pipeline.rank_listings(
                    items, self._conversation,
                    desired_attributes=desired,
                    item_type=item_type,
                    signals=signals,
                    market_data=market_data,
                    annotations=annotations,
                )
                self._put((_MSG_ANALYSIS, rec))
                self._put((_MSG_DONE, {"user_text": user_text, "explanation": ""}))
        except Exception as e:
            self._put((_MSG_ERROR, str(e)))

    # ------------------------------------------------------------------
    # Threading helpers
    # ------------------------------------------------------------------

    def _run_worker(self, fn, *args):
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _put(self, msg):
        self._queue.put(msg)

    def _poll_queue(self):
        try:
            while True:
                msg_type, payload = self._queue.get_nowait()
                self._handle_message(msg_type, payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _handle_message(self, msg_type: str, payload):
        if msg_type == _MSG_STATUS:
            if self._nav == _NAV_AUCTIONS:
                self.auction_panel.set_status(payload)
            else:
                self.ai_panel.set_status(payload)

        elif msg_type == _MSG_ITEMS:
            if isinstance(payload, tuple) and len(payload) >= 5:
                items, desired, item_type, signals, params = payload[:5]
                self._current_item_type = item_type
                self._current_signals = signals
                self._current_params = params
                self._desired_attributes = desired
            elif isinstance(payload, tuple) and len(payload) == 4:
                items, desired, item_type, signals = payload
                self._current_item_type = item_type
                self._current_signals = signals
                self._desired_attributes = desired
            elif isinstance(payload, tuple) and len(payload) == 3:
                items, desired, item_type = payload
                self._current_item_type = item_type
                self._desired_attributes = desired
            else:
                items = payload
            self._current_items = list(items)
            self.results_list.load(
                self._current_items[:50],
                desired=self._desired_attributes,
                item_type=self._current_item_type,
                signals=self._current_signals,
                market_data=self._current_market_data,
                annotations=self._current_annotations,
                params=self._current_params,
            )
            # Auto-expand rank #1 immediately so user sees the best deal right away
            if self._current_items:
                best_id = self._current_items[0].itemId
                self.after(150, lambda bid=best_id: self.results_list.expand_item(bid))

        elif msg_type == _MSG_MARKET_PRICE:
            market_data, signals = payload
            self._current_market_data = market_data
            self._current_signals = signals
            self.results_list.update_market_data(market_data, signals)

        elif msg_type == _MSG_ANNOTATIONS:
            self._current_annotations = payload or {}
            self.results_list.update_annotations(self._current_annotations)

        elif msg_type == _MSG_ANALYSIS:
            if isinstance(payload, dict):
                from llm.deal_score import compute_score_breakdown
                item_lookup = {i.itemId: i for i in self._current_items}
                score_data = {
                    item.itemId: compute_score_breakdown(
                        item,
                        self._current_signals.get(item.itemId),
                        self._current_market_data,
                        self._current_items,
                        self._desired_attributes,
                    )
                    for item in self._current_items[:10]
                }
                self._current_rank = payload
                self._current_rank_item_lookup = item_lookup
                self._current_rank_score_data = score_data
                self.ai_panel.set_recommendation(
                    payload,
                    item_lookup=item_lookup,
                    on_exclude=self._on_exclude_pick,
                    score_data=score_data,
                )
            else:
                self.ai_panel.set_text(str(payload))

        elif msg_type == _MSG_AUCTION_ITEMS:
            items, market_data, params = payload
            self._auction_items = list(items)
            self._auction_market_data = market_data
            self._auction_params = params
            self.auction_list.load(
                self._auction_items[:50], market_data=market_data,
                annotations=self._auction_annotations,
            )
            if self._auction_items:
                best_id = self._auction_items[0].itemId
                self.after(150, lambda bid=best_id: self.auction_list.expand_item(bid))

        elif msg_type == _MSG_AUCTION_ANNOTATIONS:
            self._auction_annotations = payload or {}
            self.auction_list.update_annotations(self._auction_annotations)

        elif msg_type == _MSG_AUCTION_ANALYSIS:
            snipe_result, item_lookup, score_data = payload
            self._current_snipe = snipe_result
            self._current_snipe_item_lookup = item_lookup
            self._current_snipe_score_data = score_data
            self.auction_panel.set_snipe(snipe_result, item_lookup=item_lookup, score_data=score_data)

        elif msg_type == _MSG_VISION_RESULT:
            item_id, result = payload
            if self._nav == _NAV_AUCTIONS:
                self.auction_list.update_vision(item_id, result)
                self._maybe_inject_vision_caution_auction(item_id, result)
            else:
                self.results_list.update_vision(item_id, result)
                self._maybe_inject_vision_caution(item_id, result)

        elif msg_type == _MSG_AUCTION_DONE:
            self.auction_panel.set_status("")
            if payload:
                q_refined = payload.get("q_refined", "")
                if q_refined:
                    self.search_bar.set_query_display(q_refined)
            self.search_bar.set_enabled(True)
            self.auction_filter_chips.set_enabled(True)
            self.auction_filter_chips.reset()
            if self._auction_items:
                self._add_watch_btn.configure(state="normal")
                self.auction_panel.set_followup_enabled(True, self._on_auction_followup)

        elif msg_type == _MSG_ERROR:
            self.search_bar.set_enabled(True)
            if self._nav == _NAV_AUCTIONS:
                self.auction_panel.set_status("")
                self.auction_panel.set_text(f"Error: {payload}")
                self.auction_filter_chips.set_enabled(bool(self._auction_items))
                self.auction_panel.set_followup_enabled(
                    bool(self._auction_items), self._on_auction_followup
                )
            else:
                self.ai_panel.set_status("")
                self.ai_panel.set_text(f"Error: {payload}")
                self.filter_chips.set_enabled(True)
                self.ai_panel.set_followup_enabled(bool(self._current_items), self._on_followup)

        elif msg_type == _MSG_ITEM_ASPECTS:
            item_id, aspects = payload
            self.results_list.update_aspects(item_id, aspects)

        elif msg_type == _MSG_NOTIFICATION:
            _, _, _, stars = payload
            self._unread_count += 1
            self._update_watches_btn()

        elif msg_type == _MSG_DONE:
            self.ai_panel.set_status("")
            if payload:
                user_text = payload.get("user_text", "")
                params = payload.get("params", {})
                if user_text:
                    self._conversation.append({"role": "user", "content": user_text})
                q_refined = params.get("q_refined", "")
                if q_refined:
                    self.search_bar.set_query_display(q_refined)
                if params:
                    self._current_params = params
                if self._current_items and params:
                    self._add_watch_btn.configure(state="normal")
            self.search_bar.set_enabled(True)
            self.filter_chips.set_enabled(True)
            self.filter_chips.reset()
            self.ai_panel.set_followup_enabled(bool(self._current_items), self._on_followup)

    # ------------------------------------------------------------------
    # Exclude pick + rerank
    # ------------------------------------------------------------------

    def _on_exclude_pick(self, item_id: str):
        self._current_items = [i for i in self._current_items if i.itemId != item_id]
        self.ai_panel.set_loading_text("Finding next best option...")
        self.ai_panel.set_status("Re-ranking...")
        self._run_worker(self._worker_rerank)

    def _worker_rerank(self):
        try:
            rec = pipeline.rank_listings(
                self._current_items, self._conversation,
                desired_attributes=self._desired_attributes,
                item_type=self._current_item_type,
                signals=self._current_signals,
                market_data=self._current_market_data,
                annotations=self._current_annotations,
            )
            self._put((_MSG_ANALYSIS, rec))
            self._put((_MSG_DONE, {"user_text": "", "explanation": ""}))
        except Exception as e:
            self._put((_MSG_ERROR, str(e)))

    # ------------------------------------------------------------------
    # Watch + monitor
    # ------------------------------------------------------------------

    def _on_watch_saved(self, watch_id: str):
        self._start_monitor_if_needed()

    def _on_watches_changed(self):
        self._start_monitor_if_needed()

    def _start_monitor_if_needed(self):
        if self._monitor is None and watches_db.get_enabled_watches():
            self._monitor = WatchMonitor(self._ebay, self._on_alert)
            self._monitor.start()
        if self._auction_monitor is None and auction_db.get_enabled_auction_watches():
            self._auction_monitor = AuctionWatchMonitor(self._ebay, self._on_auction_alert)
            self._auction_monitor.start()

    def _on_auction_watch_saved(self, watch_id: str):
        self._start_monitor_if_needed()

    def _on_auction_alert(self, watch, item, alert_type: str, score: float, stars: int, market_data=None):
        watches_db.save_notification(watch.id, item, score, stars)
        notifier.send_toast(watch.name, item, stars)
        self._put((_MSG_NOTIFICATION, (watch, item, score, stars)))

        webhook = config.load().get("slack_webhook", "").strip()
        if webhook:
            self._run_worker(
                self._worker_slack_auction_alert,
                watch.name, item, alert_type, market_data, webhook,
            )

    def _worker_slack_auction_alert(self, watch_name, item, alert_type, market_data, webhook_url):
        from notifications.slack import send_auction_alert
        send_auction_alert(watch_name, item, alert_type, market_data, webhook_url)

    def _on_alert(self, watch, item, score: float, stars: int, signals: dict = None, market_data=None):
        watches_db.save_notification(watch.id, item, score, stars)
        notifier.send_toast(watch.name, item, stars)
        self._put((_MSG_NOTIFICATION, (watch, item, score, stars)))

        webhook = config.load().get("slack_webhook", "").strip()
        if webhook:
            item_type = watch.params.get("item_type", "other")
            self._run_worker(
                self._worker_slack_alert,
                watch.name, item, stars, signals or {}, market_data, webhook, item_type,
            )

    def _worker_slack_alert(self, watch_name, item, stars, signals, market_data, webhook_url, item_type):
        from llm.pipeline import generate_notif_message, annotate_listings
        from notifications.slack import send_slack_alert
        annotation = annotate_listings([item], item_type, signals).get(item.itemId, {})
        llm_msg = generate_notif_message(item, annotation, market_data)
        send_slack_alert(watch_name, item, stars, annotation, llm_msg, market_data, webhook_url)




def _build_ebay_client() -> EbayClient:
    client_id = os.getenv("EBAY_CLIENT_ID", "")
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "")
    marketplace = os.getenv("EBAY_MARKETPLACE", "EBAY_US")
    sandbox = os.getenv("EBAY_SANDBOX", "false").lower() == "true"
    if not client_id or not client_secret:
        raise RuntimeError("EBAY_CLIENT_ID and EBAY_CLIENT_SECRET must be set in .env")
    zip_code = config.load().get("zip_code", "")
    return EbayClient(client_id, client_secret, marketplace, sandbox, zip_code=zip_code)
