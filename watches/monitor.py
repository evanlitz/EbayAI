from __future__ import annotations
import threading
import time

import cache.db as cache_db
from llm.signals import score_items
from llm.deal_score import compute_deal_score, score_to_stars
import watches.db as watches_db
from watches.db import Watch


class WatchMonitor:
    def __init__(self, ebay_client, on_alert):
        self._client = ebay_client
        self._on_alert = on_alert  # on_alert(watch, item, score, stars)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        print("[WATCH MONITOR] started")
        while not self._stop.wait(30):
            self._tick()

    def _tick(self) -> None:
        now = time.time()
        for watch in watches_db.get_enabled_watches():
            due_in = (watch.last_checked_at + watch.interval_seconds) - now
            if due_in <= 0:
                print(f"[WATCH] scheduling poll for '{watch.name}'")
                threading.Thread(
                    target=self._poll, args=(watch,), daemon=True
                ).start()
            else:
                print(f"[WATCH] '{watch.name}' next check in {int(due_in)}s")

    def _poll(self, watch: Watch) -> None:
        print(f"\n[WATCH] polling '{watch.name}'  baseline_done={watch.baseline_done}")
        try:
            items = self._client.search_new_listings(watch.params, limit=50)
        except Exception as e:
            print(f"[WATCH] '{watch.name}' — eBay search failed: {e}")
            return

        print(f"[WATCH] '{watch.name}' — {len(items)} listings from eBay")

        seen = watches_db.get_seen_ids(watch.id)
        new_items = [i for i in items if i.itemId not in seen]

        watches_db.mark_seen(watch.id, [i.itemId for i in items])
        watches_db.update_last_checked(watch.id, time.time())

        if not watch.baseline_done:
            watches_db.set_baseline_done(watch.id)
            print(f"[WATCH] '{watch.name}' — baseline set ({len(items)} items marked seen). Next check in {watch.interval_seconds}s.")
            return

        print(f"[WATCH] '{watch.name}' — {len(new_items)} new items since last check")
        if not new_items:
            return

        item_type = watch.params.get("item_type", "other")
        q = watch.params.get("q", watch.name)
        market_data = cache_db.get_market_price(q, item_type)
        signals = score_items(new_items, item_type)
        desired = watch.params.get("desired_attributes") or {}

        for item in new_items:
            if watch.price_max is not None and item.totalCost > watch.price_max:
                print(f"[WATCH] skip '{item.title[:50]}' — ${item.totalCost:.2f} > price_max ${watch.price_max:.2f}")
                continue
            sig = signals.get(item.itemId)
            score = compute_deal_score(item, sig, market_data, new_items, desired)
            stars = score_to_stars(score)
            print(f"[WATCH] '{item.title[:50]}' — score={score:.3f} stars={stars} (min={watch.min_stars})")
            if stars >= watch.min_stars:
                try:
                    self._on_alert(watch, item, score, stars, signals=signals, market_data=market_data)
                    print(f"[WATCH] ALERT fired for '{item.title[:50]}'")
                except Exception as e:
                    print(f"[WATCH] alert handler failed: {e}")
