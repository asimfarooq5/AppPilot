#!/usr/bin/env python3
"""
Non-interactive demo: train a 3-step flow on DeskConn, replay it,
then generate a pytest file.
"""
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from core import adb
from core.recorder import FlowRecorder, FlowPlayer, load_flows
from core.screen import render_elements, guess_screen_type
from ai.analyzer import analyze_screen
from generate.pytest_gen import generate

console = Console()
PACKAGE = "com.example.deskconn_mobile_app"
SHOT_DIR = Path("reports/screenshots/demo")
SHOT_DIR.mkdir(parents=True, exist_ok=True)


def step(title: str):
    console.print()
    console.rule(f"[bold cyan]{title}[/bold cyan]")


def inspect_screen(device: str, label: str, step_num: int) -> tuple[list[dict], dict]:
    xml = adb.dump_ui(device)
    elements = adb.parse_elements(xml)
    shot = SHOT_DIR / f"step_{step_num:02d}_{label}.png"
    adb.screencap(shot, device)
    analysis = analyze_screen(elements, shot, xml)
    console.print(Panel(
        f"[bold]{analysis['screen_type']}[/bold]"
        + ("  [green](AI)[/green]" if analysis["ai_powered"] else "  [dim](heuristic)[/dim]")
        + f"\n[dim]{analysis['description']}[/dim]",
        title=f"[cyan]{label}[/cyan]",
        border_style="cyan",
    ))
    interactive = [e for e in elements if e["clickable"]]
    if interactive:
        console.print(render_elements(elements))
    return elements, analysis


def find_element(elements: list[dict], hint: str) -> dict | None:
    hint_l = hint.lower()
    for e in elements:
        if hint_l in e["label"].lower() or hint_l in e["desc"].lower():
            return e
    return None


def main():
    console.print(Panel.fit(
        "[bold cyan]Universal Android App Trainer — Demo[/bold cyan]\n"
        "[dim]Training a flow on DeskConn, then replaying it[/dim]",
        border_style="cyan",
    ))

    # ── 1. Device ─────────────────────────────────────────────────────────────
    step("1 · Detect device")
    devices = adb.list_devices()
    device = devices[0]["serial"]
    console.print(f"[green]Device:[/green] {device}")

    pkgs = adb.list_packages(device, third_party_only=True)
    console.print(f"[green]{len(pkgs)} third-party apps installed[/green]")
    dc = [p for p in pkgs if "deskconn" in p or "example" in p]
    console.print("[dim]DeskConn-family apps: " + ", ".join(dc) + "[/dim]")

    # ── 2. Launch ─────────────────────────────────────────────────────────────
    step("2 · Launch DeskConn")
    adb.launch_app(PACKAGE, device)
    console.print("[green]App launched[/green]")

    # ── 3. Inspect home screen ────────────────────────────────────────────────
    step("3 · Inspect home screen")
    elements, analysis = inspect_screen(device, "home_screen", 1)

    interactive = [e for e in elements if e["clickable"]]
    console.print(f"[green]{len(interactive)} tappable elements found[/green]")

    # ── 4. Train a flow ───────────────────────────────────────────────────────
    step("4 · Record flow: 'launch_to_desktop'")
    recorder = FlowRecorder()
    recorder.screenshot("home")

    # Skip pure system-bar buttons; prefer desktop entries (short labels, mid-screen)
    _SKIP = {"navigate up", "open navigation menu", "toggle theme", "back",
             "home", "menu", "overflow", "more options"}
    desktop_el = None
    for e in interactive:
        if e["label"].lower() in _SKIP:
            continue
        # prefer entries in the middle vertical zone (not top bar)
        if e["cy"] > 400:
            desktop_el = e
            break
    # fallback: any non-skip element
    if not desktop_el:
        for e in interactive:
            if e["label"].lower() not in _SKIP:
                desktop_el = e
                break

    if desktop_el:
        console.print(f"[cyan]→ tap '{desktop_el['label']}'[/cyan]")
        recorder.tap(desktop_el)
        adb.tap(desktop_el["cx"], desktop_el["cy"], device)
        time.sleep(2.5)

        elements2, analysis2 = inspect_screen(device, "after_first_tap", 2)
        recorder.screenshot("after_tap")

        # Assert on a real visible element — prefer elements with a content-desc
        # (those are explicitly labelled by the app, not resource-id fallbacks)
        assert_el = next(
            (e for e in elements2 if e["desc"] and e["clickable"]), None
        ) or next((e for e in elements2 if e["desc"]), None)
        if assert_el:
            recorder.assert_present(assert_el["desc"])
            console.print(f"[dim]  + assert '{assert_el['desc']}' visible[/dim]")
    else:
        console.print("[yellow]No tappable element found; recording screenshot only[/yellow]")

    recorder.save(PACKAGE, "launch_to_desktop")
    console.print(f"[green]Flow saved: {len(recorder.actions())} steps[/green]")

    # ── 5. Show saved flows ───────────────────────────────────────────────────
    step("5 · Saved flows for package")
    flows = load_flows(PACKAGE)
    for name, actions in flows.items():
        console.print(f"  [bold]{name}[/bold]  ({len(actions)} steps)")
        for a in actions:
            console.print(f"    [dim]{a}[/dim]")

    # ── 6. Replay ─────────────────────────────────────────────────────────────
    step("6 · Replay 'launch_to_desktop'")
    adb.launch_app(PACKAGE, device)
    player = FlowPlayer(device, SHOT_DIR)
    ok = player.play(flows["launch_to_desktop"])
    if ok:
        console.print("[green]✓ Replay PASSED[/green]")
    else:
        console.print("[red]✗ Replay FAILED[/red]")
        for f in player.failures:
            console.print(f"[red]  {f}[/red]")

    # ── 7. Generate pytest ────────────────────────────────────────────────────
    step("7 · Generate pytest file")
    out = generate(PACKAGE, Path("tests/generated"))
    console.print(f"[green]Generated:[/green] {out}")
    console.print()
    console.print(out.read_text())

    console.print()
    console.print(Panel.fit(
        "[bold green]Demo complete![/bold green]\n"
        f"[dim]Screenshots in {SHOT_DIR}\n"
        f"Test file:   {out}[/dim]",
        border_style="green",
    ))


if __name__ == "__main__":
    main()
