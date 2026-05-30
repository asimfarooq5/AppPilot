"""
Flow recording — saves user interactions as JSON and replays them.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Optional

from core import adb


DATA_DIR = Path(__file__).parent.parent / "data"


def _app_dir(package: str) -> Path:
    d = DATA_DIR / package
    d.mkdir(parents=True, exist_ok=True)
    return d


def _flows_path(package: str) -> Path:
    return _app_dir(package) / "flows.json"


def load_flows(package: str) -> dict:
    p = _flows_path(package)
    if p.exists():
        return json.loads(p.read_text())
    return {}


def save_flows(package: str, flows: dict) -> None:
    _flows_path(package).write_text(json.dumps(flows, indent=2))


def list_flows(package: str) -> list[str]:
    return list(load_flows(package).keys())


# ── Action types ──────────────────────────────────────────────────────────────
#
#  { "action": "tap",       "label": "Log In",  "cx": 540, "cy": 1200 }
#  { "action": "type",      "text": "hello" }
#  { "action": "clear" }
#  { "action": "scroll",    "direction": "down", "steps": 1 }
#  { "action": "back" }
#  { "action": "home" }
#  { "action": "key",       "keycode": "KEYCODE_ENTER" }
#  { "action": "wait",      "seconds": 2 }
#  { "action": "assert",    "label": "Welcome",  "present": true }
#  { "action": "screenshot","name": "after_login" }


class FlowRecorder:
    def __init__(self):
        self._actions: list[dict] = []

    def tap(self, element: dict) -> dict:
        a = {"action": "tap", "label": element["label"],
             "cx": element["cx"], "cy": element["cy"]}
        self._actions.append(a)
        return a

    def type_text(self, text: str) -> dict:
        a = {"action": "type", "text": text}
        self._actions.append(a)
        return a

    def clear(self) -> dict:
        a = {"action": "clear"}
        self._actions.append(a)
        return a

    def scroll(self, direction: str = "down", steps: int = 1) -> dict:
        a = {"action": "scroll", "direction": direction, "steps": steps}
        self._actions.append(a)
        return a

    def back(self) -> dict:
        a = {"action": "back"}
        self._actions.append(a)
        return a

    def home(self) -> dict:
        a = {"action": "home"}
        self._actions.append(a)
        return a

    def key(self, keycode: str) -> dict:
        a = {"action": "key", "keycode": keycode}
        self._actions.append(a)
        return a

    def wait(self, seconds: float) -> dict:
        a = {"action": "wait", "seconds": seconds}
        self._actions.append(a)
        return a

    def assert_present(self, label: str, present: bool = True) -> dict:
        a = {"action": "assert", "label": label, "present": present}
        self._actions.append(a)
        return a

    def screenshot(self, name: str) -> dict:
        a = {"action": "screenshot", "name": name}
        self._actions.append(a)
        return a

    def undo_last(self) -> Optional[dict]:
        if self._actions:
            return self._actions.pop()
        return None

    def actions(self) -> list[dict]:
        return list(self._actions)

    def save(self, package: str, flow_name: str) -> None:
        flows = load_flows(package)
        flows[flow_name] = self._actions
        save_flows(package, flows)


# ── Replay ────────────────────────────────────────────────────────────────────

_SCREEN_W = 1440  # fallback; overridden by device


def _swipe_for_scroll(direction: str, steps: int, device: str) -> None:
    for _ in range(steps):
        if direction == "down":
            adb.swipe(720, 2400, 720, 800, 400, device)
        elif direction == "up":
            adb.swipe(720, 800, 720, 2400, 400, device)
        elif direction == "right":
            adb.swipe(200, 1200, 1200, 1200, 400, device)
        elif direction == "left":
            adb.swipe(1200, 1200, 200, 1200, 400, device)


class FlowPlayer:
    def __init__(self, device: str, screenshot_dir: Path, log=None):
        self.device = device
        self.screenshot_dir = screenshot_dir
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._step = 0
        self.failures: list[str] = []
        self._log = log or print

    def play(self, actions: list[dict]) -> bool:
        total = len(actions)
        for i, action in enumerate(actions, 1):
            self._log(f"  [{i}/{total}] {self._describe(action)}")
            ok = self._dispatch(action)
            if not ok:
                return False
        return True

    def _describe(self, action: dict) -> str:
        kind = action["action"]
        if kind == "tap":
            return f"tap [cyan]{action.get('label', '?')!r}[/cyan]"
        if kind == "type":
            return f"type [cyan]{action['text']!r}[/cyan]"
        if kind == "clear":
            return "clear field"
        if kind == "scroll":
            return f"scroll {action.get('direction', 'down')}"
        if kind == "back":
            return "back"
        if kind == "home":
            return "home"
        if kind == "key":
            return f"key {action.get('keycode', '')}"
        if kind == "wait":
            return f"wait {action.get('seconds', 1)}s"
        if kind == "assert":
            flag = "present" if action.get("present", True) else "absent"
            return f"assert [cyan]{action.get('label', '?')!r}[/cyan] {flag}"
        if kind == "screenshot":
            return f"screenshot [dim]{action.get('name', '')!r}[/dim]"
        return kind

    def _dispatch(self, action: dict) -> bool:
        kind = action["action"]

        if kind == "tap":
            self._smart_tap(action)
        elif kind == "type":
            adb.type_text(action["text"], self.device)
        elif kind == "clear":
            adb.clear_field(self.device)
        elif kind == "scroll":
            _swipe_for_scroll(action.get("direction", "down"),
                              action.get("steps", 1), self.device)
        elif kind == "back":
            adb.back(self.device)
        elif kind == "home":
            adb.home(self.device)
        elif kind == "key":
            adb.key_event(action["keycode"], self.device)
        elif kind == "wait":
            time.sleep(action.get("seconds", 1))
        elif kind == "assert":
            return self._check_assert(action)
        elif kind == "screenshot":
            self._take_screenshot(action.get("name", "step"))
        return True

    def _smart_tap(self, action: dict) -> None:
        label = action.get("label", "")
        cx, cy = action["cx"], action["cy"]

        if label:
            xml = adb.dump_ui(self.device)
            elements = adb.parse_elements(xml)

            # Exact label match first, then substring fallback
            match = next((e for e in elements if e["label"] == label), None)
            if not match:
                match = next(
                    (e for e in elements
                     if label in e["label"] or e["label"] in label),
                    None,
                )

            if match:
                self._log(
                    f"      [green]✓[/green] matched [cyan]{label!r}[/cyan] "
                    f"at ({match['cx']},{match['cy']})"
                )
                adb.tap(match["cx"], match["cy"], self.device)
                time.sleep(0.5)
                return

            self._log(
                f"      [yellow]⚠[/yellow] [cyan]{label!r}[/cyan] not on screen "
                f"— falling back to recorded ({cx},{cy})"
            )

        adb.tap(cx, cy, self.device)
        time.sleep(0.5)

    def _check_assert(self, action: dict) -> bool:
        xml = adb.dump_ui(self.device)
        label = action["label"]
        found = label in xml
        expected = action.get("present", True)
        if found != expected:
            msg = (f"Assert FAILED: '{label}' should be "
                   f"{'present' if expected else 'absent'} but was not")
            self._log(f"      [red]✗[/red] {msg}")
            self.failures.append(msg)
            return False
        self._log(f"      [green]✓[/green] assert '{label}' {('present' if expected else 'absent')}")
        return True

    def _take_screenshot(self, name: str) -> Path:
        self._step += 1
        path = self.screenshot_dir / f"{self._step:03d}_{name}.png"
        adb.screencap(path, self.device)
        self._log(f"      [dim]saved: {path}[/dim]")
        return path
