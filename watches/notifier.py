from __future__ import annotations


def send_toast(watch_name: str, item, stars: int) -> None:
    try:
        from winotify import Notification, audio
        star_str = "★" * stars + "☆" * (5 - stars)
        notif = Notification(
            app_id="EbayAI",
            title=f"New Deal {star_str} — ${item.totalCost:.2f}",
            msg=item.title[:80],
            duration="long",
        )
        notif.add_actions(label="Open on eBay", launch=item.itemWebURL)
        notif.set_audio(audio.Default, loop=False)
        notif.show()
    except Exception:
        pass
