from __future__ import annotations
import threading
import time

import cache.db as cache_db
from llm.auction_score import (
    compute_auction_score, auction_score_to_stars,
    is_ending_soon_by_date,
)
import watches.auction_db as auction_db
from watches.auction_db import AuctionWatch


class AuctionWatchMonitor:
    def __init__(self, ebay_client, on_alert):
        self._client = ebay_client
        # on_alert(watch, item, alert_type, score, stars, market_data)
        # alert_type: "new_listing" | "ending_soon"
        self._on_alert = on_alert
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        print("[AUCTION MONITOR] started")
        while not self._stop.wait(30):
            self._tick()

    def _tick(self) -> None:
        now = time.time()
        for watch in auction_db.get_enabled_auction_watches():
            seen_dates = auction_db.get_seen_with_end_dates(watch.id)
            any_ending_soon = any(
                is_ending_soon_by_date(ed, watch.ending_window_hours)
                for ed in seen_dates.values()
                if ed
            )
            effective_interval = (
                watch.snipe_interval_seconds if any_ending_soon
                else watch.interval_seconds
            )
            due_in = (watch.last_checked_at + effective_interval) - now
            if due_in <= 0:
                mode = "snipe" if any_ending_soon else "normal"
                print(f"[AUCTION] scheduling poll for '{watch.name}' [{mode}]")
                threading.Thread(
                    target=self._poll, args=(watch,), daemon=True
                ).start()
            else:
                print(f"[AUCTION] '{watch.name}' next check in {int(due_in)}s")

    def _poll(self, watch: AuctionWatch) -> None:
        print(f"\n[AUCTION] polling '{watch.name}'  baseline_done={watch.baseline_done}")
        try:
            items = self._client.search_new_listings(watch.params, limit=50)
        except Exception as e:
            print(f"[AUCTION] '{watch.name}' — eBay search failed: {e}")
            return

        print(f"[AUCTION] '{watch.name}' — {len(items)} listings from eBay")

        seen_ids = auction_db.get_seen_ids(watch.id)
        seen_dates = auction_db.get_seen_with_end_dates(watch.id)
        alerted_ids = auction_db.get_ending_soon_alerted_ids(watch.id)

        new_items = [i for i in items if i.itemId not in seen_ids]
        existing_items = [i for i in items if i.itemId in seen_ids]

        # Upsert seen items (updates end_dates for existing, adds new ones)
        auction_db.mark_seen(watch.id, items)
        auction_db.update_last_checked(watch.id, time.time())

        if not watch.baseline_done:
            auction_db.set_baseline_done(watch.id)
            print(f"[AUCTION] '{watch.name}' — baseline set ({len(items)} items). Next check in {watch.interval_seconds}s.")
            return

        item_type = watch.params.get("item_type", "other")
        q = watch.params.get("q", watch.name)
        market_data = cache_db.get_market_price(q, item_type)

        # New listing alerts
        if watch.alert_new_listing and new_items:
            print(f"[AUCTION] '{watch.name}' — {len(new_items)} new listings")
            for item in new_items:
                if watch.price_max is not None:
                    bid = item.currentBidPrice or item.price
                    if bid > watch.price_max:
                        continue
                score = compute_auction_score(item, market_data, new_items)
                stars = auction_score_to_stars(score)
                print(f"[AUCTION] new '{item.title[:50]}' — score={score:.3f}")
                try:
                    self._on_alert(watch, item, "new_listing", score, stars, market_data)
                except Exception as e:
                    print(f"[AUCTION] alert handler failed: {e}")

        # Ending soon alerts (items that just crossed the window threshold)
        if watch.alert_ending_soon:
            for item in existing_items:
                if item.itemId in alerted_ids:
                    continue
                if not item.itemEndDate:
                    continue
                if is_ending_soon_by_date(item.itemEndDate, watch.ending_window_hours):
                    if watch.price_max is not None:
                        bid = item.currentBidPrice or item.price
                        if bid > watch.price_max:
                            continue
                    score = compute_auction_score(item, market_data, existing_items)
                    stars = auction_score_to_stars(score)
                    print(f"[AUCTION] ending soon '{item.title[:50]}' — score={score:.3f}")
                    auction_db.mark_ending_soon_alerted(watch.id, item.itemId)
                    try:
                        self._on_alert(watch, item, "ending_soon", score, stars, market_data)
                    except Exception as e:
                        print(f"[AUCTION] ending-soon alert handler failed: {e}")
