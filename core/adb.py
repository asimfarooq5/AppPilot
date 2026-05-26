"""
Universal ADB / UIAutomator helpers — works with any installed Android app.
"""
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


def run(*args, device: Optional[str] = None, capture: bool = False):
    cmd = ["adb"]
    if device:
        cmd += ["-s", device]
    cmd += list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if capture:
        return result.stdout.strip()
    return result.returncode == 0


def list_devices() -> list[dict]:
    out = run("devices", capture=True)
    devices = []
    for line in out.splitlines()[1:]:
        if "\t" in line:
            parts = line.split("\t", 1)
            serial, state = parts[0].strip(), parts[1].strip()
            devices.append({"serial": serial, "state": state})
    return devices


def list_packages(device: str, third_party_only: bool = True) -> list[str]:
    args = ["shell", "pm", "list", "packages"]
    if third_party_only:
        args.append("-3")
    out = run(*args, device=device, capture=True)
    packages = []
    for line in out.splitlines():
        if line.startswith("package:"):
            packages.append(line[8:].strip())
    return sorted(packages)


def get_app_label(device: str, package: str) -> str:
    out = run("shell", "dumpsys", "package", package, device=device, capture=True)
    for line in out.splitlines():
        if "versionName" in line:
            pass
        if "applicationInfo" in line and "label=" in line:
            m = re.search(r'label="([^"]+)"', line)
            if m:
                return m.group(1)
    # Fallback: title-case the last dotted segment
    return package.split(".")[-1].replace("_", " ").title()


def get_current_package(device: str) -> str:
    """Return the package name of the currently focused activity."""
    out = run("shell", "dumpsys", "window", "windows", device=device, capture=True)
    m = re.search(r"mCurrentFocus.*?([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)", out, re.I)
    if m:
        return m.group(1)
    return ""


def force_stop(package: str, device: str) -> None:
    run("shell", "am", "force-stop", package, device=device)
    time.sleep(0.5)


def launch_app(package: str, device: str) -> None:
    force_stop(package, device)
    run("shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1",
        device=device)
    time.sleep(4)


def back(device: str) -> None:
    run("shell", "input", "keyevent", "KEYCODE_BACK", device=device)
    time.sleep(1)


def home(device: str) -> None:
    run("shell", "input", "keyevent", "KEYCODE_HOME", device=device)
    time.sleep(0.5)


def tap(x: int, y: int, device: str, wait: float = 0.8) -> None:
    run("shell", "input", "tap", str(x), str(y), device=device)
    time.sleep(wait)


def type_text(text: str, device: str) -> None:
    # Replace spaces with %s (Android input text quirk)
    safe = text.replace(" ", "%s")
    run("shell", "input", "text", safe, device=device)
    time.sleep(0.5)


def clear_field(device: str) -> None:
    """Select all and delete."""
    run("shell", "input", "keyevent", "--longpress", "KEYCODE_A", device=device)
    time.sleep(0.3)
    run("shell", "input", "keyevent", "KEYCODE_DEL", device=device)
    time.sleep(0.3)


def swipe(x1: int, y1: int, x2: int, y2: int, ms: int, device: str) -> None:
    run("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms),
        device=device)
    time.sleep(0.8)


def key_event(keycode: str, device: str) -> None:
    run("shell", "input", "keyevent", keycode, device=device)
    time.sleep(0.5)


def screencap(dest: Path, device: str) -> None:
    remote = "/sdcard/_aat_cap.png"
    run("shell", "screencap", "-p", remote, device=device)
    run("pull", remote, str(dest), device=device)


def dump_ui(device: str) -> str:
    run("shell", "uiautomator", "dump", "/sdcard/_aat_ui.xml", device=device)
    return run("shell", "cat", "/sdcard/_aat_ui.xml", device=device, capture=True)


# ── Element parsing ───────────────────────────────────────────────────────────

def _parse_bounds(bounds_str: str) -> tuple[int, int, int, int]:
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
    if not m:
        return (0, 0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))


def parse_elements(xml: str) -> list[dict]:
    """Parse UIAutomator XML into a flat list of element dicts."""
    elements = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return elements

    for node in root.iter("node"):
        desc = node.get("content-desc", "").strip()
        text = node.get("text", "").strip()
        res_id = node.get("resource-id", "").strip()
        cls = node.get("class", "")
        clickable = node.get("clickable", "false") == "true"
        long_clickable = node.get("long-clickable", "false") == "true"
        scrollable = node.get("scrollable", "false") == "true"
        enabled = node.get("enabled", "false") == "true"
        checkable = node.get("checkable", "false") == "true"
        checked = node.get("checked", "false") == "true"
        bounds_str = node.get("bounds", "")

        # Best display label
        label = desc or text
        if not label and res_id:
            label = res_id.split("/")[-1].replace("_", " ")
        if not label:
            continue

        x1, y1, x2, y2 = _parse_bounds(bounds_str)
        if x1 == x2 or y1 == y2:
            continue

        elements.append({
            "class": cls,
            "desc": desc,
            "text": text,
            "resource_id": res_id,
            "label": label,
            "clickable": clickable or long_clickable,
            "scrollable": scrollable,
            "checkable": checkable,
            "checked": checked,
            "enabled": enabled,
            "bounds": (x1, y1, x2, y2),
            "cx": (x1 + x2) // 2,
            "cy": (y1 + y2) // 2,
        })

    return elements


def screen_fingerprint(elements: list[dict]) -> frozenset:
    """A set of labels that identifies a screen (used to detect navigation)."""
    return frozenset(e["label"] for e in elements if e["clickable"])
