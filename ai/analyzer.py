"""
Optional AI-powered screen analysis using the Anthropic Claude API.

If ANTHROPIC_API_KEY is not set, falls back to heuristic analysis only.
"""
from __future__ import annotations
import base64
import os
from pathlib import Path
from typing import Optional

from core.screen import guess_screen_type


def _api_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def analyze_screen(
    elements: list[dict],
    screenshot_path: Optional[Path] = None,
    xml: str = "",
) -> dict:
    """
    Analyze the current screen. Returns:
      {
        "screen_type": str,
        "description": str,
        "suggested_actions": list[str],
        "ai_powered": bool,
      }
    """
    screen_type = guess_screen_type(elements)

    if _api_available() and screenshot_path and screenshot_path.exists():
        try:
            return _claude_analyze(elements, screenshot_path, screen_type)
        except Exception as e:
            return _heuristic_analyze(elements, screen_type, str(e))
    else:
        return _heuristic_analyze(elements, screen_type)


def _claude_analyze(
    elements: list[dict],
    screenshot_path: Path,
    screen_type: str,
) -> dict:
    import anthropic

    client = anthropic.Anthropic()

    img_data = base64.standard_b64encode(screenshot_path.read_bytes()).decode()

    element_summary = "\n".join(
        f"  - {e['label']} ({e['class'].split('.')[-1]}, "
        f"{'clickable' if e['clickable'] else 'static'})"
        for e in elements[:30]
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_data,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        f"This is a screenshot of an Android app screen.\n"
                        f"UIAutomator found these elements:\n{element_summary}\n\n"
                        "In 2 sentences: (1) What screen/state is this? "
                        "(2) What are the most important actions a user would take here? "
                        "Be concrete and brief."
                    ),
                },
            ],
        }],
    )

    description = response.content[0].text.strip()
    suggested = _extract_suggestions(description, elements)

    return {
        "screen_type": screen_type,
        "description": description,
        "suggested_actions": suggested,
        "ai_powered": True,
    }


def _heuristic_analyze(
    elements: list[dict],
    screen_type: str,
    error: str = "",
) -> dict:
    clickable = [e for e in elements if e["clickable"]]
    inputs = [e for e in elements if "edittext" in e["class"].lower()
              or "textfield" in e["class"].lower()]

    if inputs:
        desc = f"Input form with {len(inputs)} text field(s) and {len(clickable)} tappable element(s)."
    elif clickable:
        desc = f"Screen with {len(clickable)} interactive element(s)."
    else:
        desc = "Screen with no interactive elements found (try scrolling)."

    if error:
        desc += f" (AI unavailable: {error})"

    suggested = _suggest_from_elements(elements)

    return {
        "screen_type": screen_type,
        "description": desc,
        "suggested_actions": suggested,
        "ai_powered": False,
    }


def _extract_suggestions(description: str, elements: list[dict]) -> list[str]:
    suggestions = _suggest_from_elements(elements)
    return suggestions[:5]


def _suggest_from_elements(elements: list[dict]) -> list[str]:
    suggestions = []
    for e in elements:
        if not e["clickable"] and "edittext" not in e["class"].lower():
            continue
        label = e["label"]
        if "edittext" in e["class"].lower() or "textfield" in e["class"].lower():
            suggestions.append(f"Type in '{label}'")
        elif e["clickable"]:
            suggestions.append(f"Tap '{label}'")
    return suggestions[:6]
