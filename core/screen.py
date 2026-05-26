"""
Screen rendering and heuristic analysis.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ── Heuristic screen type detection ──────────────────────────────────────────

_LOGIN_HINTS = {"log in", "login", "sign in", "signin", "username", "password",
                "email", "forgot password", "create account"}
_HOME_HINTS = {"home", "dashboard", "feed", "timeline", "for you", "discover"}
_LIST_HINTS = {"list", "search", "filter", "sort", "items", "results"}
_SETTINGS_HINTS = {"settings", "preferences", "account", "profile", "privacy",
                   "notifications", "logout", "sign out"}
_MEDIA_HINTS = {"play", "pause", "volume", "fullscreen", "seek", "player"}
_FORM_HINTS = {"submit", "save", "send", "confirm", "next", "continue"}


def guess_screen_type(elements: list[dict]) -> str:
    labels = {e["label"].lower() for e in elements}
    descs = {e["desc"].lower() for e in elements}
    all_text = labels | descs

    scores = {
        "Login / Sign-in": len(all_text & _LOGIN_HINTS),
        "Home / Feed": len(all_text & _HOME_HINTS),
        "List / Search": len(all_text & _LIST_HINTS),
        "Settings / Profile": len(all_text & _SETTINGS_HINTS),
        "Media Player": len(all_text & _MEDIA_HINTS),
        "Form / Input": len(all_text & _FORM_HINTS),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Unknown"


def widget_type(element: dict) -> str:
    cls = element["class"].lower()
    if "edittext" in cls or "textfield" in cls:
        return "input"
    if "button" in cls:
        return "button"
    if "checkbox" in cls:
        return "checkbox"
    if "switch" in cls or "toggle" in cls:
        return "switch"
    if "imageview" in cls and element["clickable"]:
        return "image-button"
    if element["scrollable"]:
        return "scroll-container"
    if element["clickable"]:
        return "tappable"
    return "label"


def render_elements(elements: list[dict], show_all: bool = False) -> str:
    """Return a rich-markup table string for the element list."""
    from rich.table import Table
    from rich import box
    from io import StringIO
    from rich.console import Console

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Label", min_width=30)
    table.add_column("Type", width=16)
    table.add_column("Position", width=16)

    indexed = []
    for el in elements:
        if not show_all and not el["clickable"] and not el["scrollable"]:
            continue
        indexed.append(el)

    for i, el in enumerate(indexed, 1):
        wt = widget_type(el)
        colour = {
            "input": "green",
            "button": "bright_blue",
            "checkbox": "yellow",
            "switch": "yellow",
            "image-button": "magenta",
            "tappable": "cyan",
            "scroll-container": "dim",
            "label": "dim",
        }.get(wt, "white")
        pos = f"({el['cx']},{el['cy']})"
        table.add_row(
            str(i),
            f"[{colour}]{el['label'][:48]}[/{colour}]",
            f"[{colour}]{wt}[/{colour}]",
            pos,
        )

    buf = StringIO()
    console = Console(file=buf, highlight=False, width=100)
    console.print(table)
    return buf.getvalue()
