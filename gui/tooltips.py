import tkinter as tk
import customtkinter as ctk


class _HelpTip:
    _current: "tk.Toplevel | None" = None
    _anchor = None

    @classmethod
    def toggle(cls, anchor, text: str):
        if cls._current is not None and cls._anchor is anchor:
            cls.dismiss()
            return
        cls.dismiss()
        try:
            root = anchor.winfo_toplevel()
            tip = tk.Toplevel(root)
            tip.overrideredirect(True)
            tip.attributes("-topmost", True)

            bg = "#2b2b2b"
            tip.configure(bg=bg)

            lbl = tk.Label(
                tip, text=text,
                bg=bg, fg="#f0f0f0",
                font=("Segoe UI", 11),
                justify="left",
                wraplength=260,
                padx=10, pady=8,
            )
            lbl.pack()
            tip.update_idletasks()

            x = anchor.winfo_rootx() + anchor.winfo_width() + 6
            y = anchor.winfo_rooty()
            tip_w = tip.winfo_width()
            screen_w = tip.winfo_screenwidth()
            if x + tip_w > screen_w - 10:
                x = anchor.winfo_rootx() - tip_w - 6
            tip.geometry(f"+{x}+{y}")

            tip.bind("<Button-1>", lambda e: cls.dismiss())
            lbl.bind("<Button-1>", lambda e: cls.dismiss())

            cls._current = tip
            cls._anchor = anchor
        except Exception:
            pass

    @classmethod
    def dismiss(cls):
        if cls._current is not None:
            try:
                if cls._current.winfo_exists():
                    cls._current.destroy()
            except Exception:
                pass
        cls._current = None
        cls._anchor = None


def make_help_btn(parent, tip_text: str, **kwargs) -> ctk.CTkButton:
    """Small circular ? button that toggles a dark tooltip on click."""
    btn = ctk.CTkButton(
        parent, text="?",
        width=18, height=18,
        font=ctk.CTkFont(size=10),
        fg_color=("gray72", "gray33"),
        hover_color=("gray60", "gray45"),
        text_color=("gray20", "gray90"),
        corner_radius=9,
        **kwargs,
    )
    btn.configure(command=lambda b=btn: _HelpTip.toggle(b, tip_text))
    return btn
