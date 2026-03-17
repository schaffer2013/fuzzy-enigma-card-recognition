from tkinter import Text, ttk


def make_panel(parent, title: str):
    frame = ttk.LabelFrame(parent, text=title, padding=12)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    return frame


def make_readonly_text(parent, *, height: int = 8, width: int = 40) -> Text:
    text = Text(parent, height=height, width=width, wrap="word")
    text.configure(state="disabled")
    return text


def set_readonly_text(widget: Text, value: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", value)
    widget.configure(state="disabled")
