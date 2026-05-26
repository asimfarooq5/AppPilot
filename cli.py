#!/usr/bin/env python3
"""
Universal Android App Trainer — interactive CLI.

Usage:
  python cli.py                   # full interactive mode
  python cli.py train <package>   # jump straight to train mode
  python cli.py run   <package>   # run all flows for a package
  python cli.py list  <package>   # list recorded flows
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.prompt import Prompt, Confirm

from core import adb
from core.screen import render_elements, guess_screen_type
from core.recorder import (
    FlowRecorder, FlowPlayer, load_flows, save_flows, list_flows
)
from ai.analyzer import analyze_screen
from generate.pytest_gen import generate as gen_pytest

console = Console()
SCREENSHOT_DIR = Path("reports/screenshots")
TESTS_DIR = Path("tests/generated")


# ── Helpers ───────────────────────────────────────────────────────────────────

def banner():
    console.print(Panel.fit(
        "[bold cyan]Universal Android App Trainer[/bold cyan]\n"
        "[dim]Train flows for any Android app, then replay as pytest tests[/dim]",
        border_style="cyan",
    ))
    console.print()


def pick(prompt_text: str, items: list[str], allow_skip: bool = False) -> int:
    """Show a numbered list and return the 0-based index of the chosen item."""
    for i, item in enumerate(items, 1):
        console.print(f"  [dim]{i:2}[/dim]  {item}")
    console.print()
    while True:
        raw = Prompt.ask(prompt_text)
        if allow_skip and raw.strip() == "":
            return -1
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(items):
                return idx
        except ValueError:
            pass
        console.print("[red]Invalid choice — enter a number from the list.[/red]")


def select_device() -> str:
    devices = adb.list_devices()
    online = [d for d in devices if d["state"] == "device"]
    if not online:
        console.print("[red]No ADB device found. Connect a device and retry.[/red]")
        sys.exit(1)
    if len(online) == 1:
        console.print(f"[green]Using device:[/green] {online[0]['serial']}")
        return online[0]["serial"]
    console.print("[bold]Select device:[/bold]")
    labels = [f"{d['serial']}  ({d['state']})" for d in online]
    idx = pick("Device number", labels)
    return online[idx]["serial"]


def select_app(device: str) -> tuple[str, str]:
    """Returns (package, label)."""
    console.print("\n[bold]Fetching installed apps…[/bold]")
    packages = adb.list_packages(device, third_party_only=True)
    console.print(f"Found [cyan]{len(packages)}[/cyan] third-party apps.\n")

    query = Prompt.ask("Filter by name (or press Enter to see all)").strip().lower()
    filtered = [p for p in packages if not query or query in p.lower()]

    if not filtered:
        console.print("[yellow]No apps matched. Showing all.[/yellow]")
        filtered = packages

    if len(filtered) > 40:
        console.print(f"[yellow]{len(filtered)} matches — showing first 40. Refine your filter.[/yellow]")
        filtered = filtered[:40]

    # Build label map (fetching labels is slow; show package names with a hint)
    labels = []
    for p in filtered:
        # Show only the last two dotted segments for readability
        short = ".".join(p.split(".")[-2:])
        labels.append(f"{p}  [dim]({short})[/dim]")

    console.print("\n[bold]Select app:[/bold]")
    idx = pick("App number", labels)
    pkg = filtered[idx]

    label = adb.get_app_label(device, pkg)
    return pkg, label


# ── Main menu ─────────────────────────────────────────────────────────────────

def app_menu(device: str, package: str, label: str):
    while True:
        console.print()
        console.rule(f"[bold cyan]{label}[/bold cyan]  [dim]{package}[/dim]")
        flows = list_flows(package)

        t = Table(box=box.SIMPLE, show_header=False)
        t.add_row("[1]", "[bold]Train a new flow[/bold]",
                  "Record a new interaction sequence")
        t.add_row("[2]", "[bold]Run saved flows[/bold]",
                  f"{len(flows)} flow(s) recorded")
        t.add_row("[3]", "[bold]Auto-explore[/bold]",
                  "Let the tool tap every element automatically")
        t.add_row("[4]", "[bold]Generate pytest file[/bold]",
                  f"Export flows → tests/generated/test_{package.split('.')[-1]}.py")
        t.add_row("[5]", "[bold]Pick a different app[/bold]", "")
        t.add_row("[q]", "[bold]Quit[/bold]", "")
        console.print(t)

        choice = Prompt.ask("Choice", choices=["1","2","3","4","5","q"]).strip()

        if choice == "1":
            train_flow(device, package, label)
        elif choice == "2":
            run_flows(device, package, label)
        elif choice == "3":
            auto_explore(device, package, label)
        elif choice == "4":
            _generate_tests(package)
        elif choice == "5":
            return
        elif choice == "q":
            console.print("\n[dim]Goodbye.[/dim]")
            sys.exit(0)


# ── Training mode ─────────────────────────────────────────────────────────────

def train_flow(device: str, package: str, label: str):
    console.print()
    flow_name = Prompt.ask("[bold]Flow name[/bold] (e.g. 'login', 'browse items')")
    if not flow_name.strip():
        console.print("[yellow]Cancelled.[/yellow]")
        return

    console.print(f"\n[cyan]Launching {label}…[/cyan]")
    adb.launch_app(package, device)

    recorder = FlowRecorder()
    step = 0

    while True:
        step += 1
        console.print()
        console.rule(f"[dim]Step {step}[/dim]")

        # Dump + analyse
        console.print("[dim]Inspecting screen…[/dim]")
        xml = adb.dump_ui(device)
        elements = adb.parse_elements(xml)

        # Take screenshot and analyse
        shot_path = SCREENSHOT_DIR / f"train_{step:03d}.png"
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        adb.screencap(shot_path, device)
        analysis = analyze_screen(elements, shot_path, xml)

        # Screen header
        ai_badge = "[green]AI[/green]" if analysis["ai_powered"] else "[dim]heuristic[/dim]"
        console.print(Panel(
            f"[bold]{analysis['screen_type']}[/bold]  {ai_badge}\n"
            f"[dim]{analysis['description']}[/dim]",
            title="[cyan]Current screen[/cyan]",
            border_style="cyan",
        ))

        # Interactive elements
        interactive = [e for e in elements if e["clickable"] or
                       "edittext" in e["class"].lower()]
        if interactive:
            console.print(render_elements(elements))
        else:
            console.print("[yellow]No interactive elements visible — try scrolling.[/yellow]")

        # Suggested actions from AI
        if analysis["suggested_actions"]:
            console.print("[dim]Suggestions:[/dim]", ", ".join(analysis["suggested_actions"][:3]))

        # Action menu
        _print_action_help()
        action_raw = Prompt.ask("Action").strip()

        if not action_raw:
            continue

        # Parse the action
        done = _handle_train_action(action_raw, interactive, elements,
                                    recorder, device, step)
        if done:
            break

    # Save
    recorder.screenshot(flow_name.replace(" ", "_") + "_final")
    recorder.save(package, flow_name)
    console.print(
        f"\n[green]Flow '[bold]{flow_name}[/bold]' saved "
        f"({len(recorder.actions())} steps).[/green]"
    )


def _print_action_help():
    console.print(
        "\n[dim]  <number>         tap element by index[/dim]\n"
        "[dim]  t <number>       tap element (same as number)[/dim]\n"
        "[dim]  type <text>      type text (use after tapping an input)[/dim]\n"
        "[dim]  clear            clear focused input field[/dim]\n"
        "[dim]  scroll [down|up] scroll the screen[/dim]\n"
        "[dim]  back             press Back[/dim]\n"
        "[dim]  home             press Home[/dim]\n"
        "[dim]  wait <secs>      pause N seconds[/dim]\n"
        "[dim]  assert <text>    add assertion that <text> is visible[/dim]\n"
        "[dim]  screenshot <n>   take a labelled screenshot[/dim]\n"
        "[dim]  undo             remove last recorded step[/dim]\n"
        "[dim]  done             finish recording[/dim]\n"
    )


def _handle_train_action(
    raw: str,
    interactive: list[dict],
    all_elements: list[dict],
    recorder: FlowRecorder,
    device: str,
    step: int,
) -> bool:
    """Returns True if recording should stop."""
    parts = raw.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    # Tap by number
    if cmd.isdigit() or (cmd == "t" and arg.isdigit()):
        idx_str = cmd if cmd.isdigit() else arg
        idx = int(idx_str) - 1
        if 0 <= idx < len(interactive):
            el = interactive[idx]
            console.print(f"  → tap [cyan]{el['label']!r}[/cyan]")
            recorder.tap(el)
            adb.tap(el["cx"], el["cy"], device)
            time.sleep(1.5)
        else:
            console.print(f"[red]No element #{idx_str}[/red]")

    elif cmd == "type":
        if not arg:
            arg = Prompt.ask("  Text to type")
        console.print(f"  → type [cyan]{arg!r}[/cyan]")
        recorder.type_text(arg)
        adb.type_text(arg, device)

    elif cmd == "clear":
        console.print("  → clear field")
        recorder.clear()
        adb.clear_field(device)

    elif cmd == "scroll":
        direction = arg.strip() or "down"
        if direction not in ("down", "up", "left", "right"):
            direction = "down"
        console.print(f"  → scroll {direction}")
        recorder.scroll(direction)
        _do_scroll(direction, device)

    elif cmd == "back":
        console.print("  → back")
        recorder.back()
        adb.back(device)

    elif cmd == "home":
        console.print("  → home")
        recorder.home()
        adb.home(device)

    elif cmd == "wait":
        try:
            secs = float(arg)
        except (ValueError, TypeError):
            secs = 2.0
        console.print(f"  → wait {secs}s")
        recorder.wait(secs)
        time.sleep(secs)

    elif cmd == "assert":
        if not arg:
            arg = Prompt.ask("  Assert text visible")
        console.print(f"  → assert '[cyan]{arg}[/cyan]' is present")
        recorder.assert_present(arg, present=True)
        xml = adb.dump_ui(device)
        if arg in xml:
            console.print("[green]  ✓ found[/green]")
        else:
            console.print("[yellow]  ⚠ not found now (assertion still recorded)[/yellow]")

    elif cmd == "screenshot":
        name = arg.strip() or f"step_{step:03d}"
        console.print(f"  → screenshot '{name}'")
        recorder.screenshot(name)
        path = SCREENSHOT_DIR / f"train_manual_{name}.png"
        adb.screencap(path, device)
        console.print(f"[dim]  saved: {path}[/dim]")

    elif cmd == "undo":
        removed = recorder.undo_last()
        if removed:
            console.print(f"[yellow]  ↩ removed: {removed}[/yellow]")
        else:
            console.print("[dim]  nothing to undo[/dim]")

    elif cmd == "done":
        return True

    else:
        console.print(f"[red]Unknown action '{cmd}'[/red]")

    return False


def _do_scroll(direction: str, device: str):
    if direction == "down":
        adb.swipe(720, 2400, 720, 800, 400, device)
    elif direction == "up":
        adb.swipe(720, 800, 720, 2400, 400, device)
    elif direction == "right":
        adb.swipe(200, 1200, 1200, 1200, 400, device)
    elif direction == "left":
        adb.swipe(1200, 1200, 200, 1200, 400, device)
    time.sleep(0.8)


# ── Run saved flows ───────────────────────────────────────────────────────────

def run_flows(device: str, package: str, label: str):
    flows = load_flows(package)
    if not flows:
        console.print("[yellow]No flows recorded yet. Use 'Train' first.[/yellow]")
        return

    console.print("\n[bold]Select flow to run:[/bold]")
    names = list(flows.keys())
    names.insert(0, "— Run ALL flows —")
    idx = pick("Flow number", names)

    targets = list(flows.items()) if idx == 0 else [(names[idx], flows[names[idx]])]

    results = []
    for flow_name, actions in targets:
        console.print(f"\n[cyan]Launching {label} for flow '[bold]{flow_name}[/bold]'…[/cyan]")
        adb.launch_app(package, device)
        player = FlowPlayer(device, SCREENSHOT_DIR)
        ok = player.play(actions)
        results.append((flow_name, ok, player.failures))

        if ok:
            console.print(f"[green]  ✓ {flow_name} PASSED[/green]")
        else:
            console.print(f"[red]  ✗ {flow_name} FAILED[/red]")
            for f in player.failures:
                console.print(f"[red]    {f}[/red]")

    # Summary
    passed = sum(1 for _, ok, _ in results if ok)
    console.print(f"\n[bold]Results: {passed}/{len(results)} passed[/bold]")


# ── Auto-explore ──────────────────────────────────────────────────────────────

def auto_explore(device: str, package: str, label: str):
    """
    Automatically tap each interactive element on the current screen,
    record what screen comes next, then go back. Builds a screen map.
    """
    console.print(f"\n[cyan]Auto-exploring {label}…[/cyan]")
    console.print("[dim]This will tap every element, go back, and build a screen map.[/dim]")
    max_depth = int(Prompt.ask("Max depth", default="2"))

    adb.launch_app(package, device)
    visited: dict[frozenset, str] = {}
    screen_map: list[dict] = []

    _explore_recursive(device, package, depth=0, max_depth=max_depth,
                       visited=visited, screen_map=screen_map, path=[])

    # Show map
    console.print()
    console.rule("[bold]Screen Map[/bold]")
    t = Table("From", "Action", "To screen type", box=box.SIMPLE)
    for entry in screen_map:
        t.add_row(entry["from"], entry["via"], entry["to"])
    console.print(t)

    if Confirm.ask("\nSave this exploration as a flow?"):
        _save_exploration(package, screen_map)


def _explore_recursive(
    device: str,
    package: str,
    depth: int,
    max_depth: int,
    visited: dict,
    screen_map: list[dict],
    path: list[str],
):
    if depth > max_depth:
        return

    xml = adb.dump_ui(device)
    elements = adb.parse_elements(xml)
    fp = adb.screen_fingerprint(elements)
    screen_type = guess_screen_type(elements)

    if fp in visited:
        return
    visited[fp] = screen_type

    parent_type = path[-1] if path else "Launch"
    interactive = [e for e in elements if e["clickable"]][:8]  # limit per screen

    shot_dir = SCREENSHOT_DIR / "explore"
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shot_dir / f"depth{depth}_{screen_type.replace(' ','_')}.png"
    adb.screencap(shot_path, device)

    console.print(f"[dim]{'  ' * depth}[/dim][cyan]{screen_type}[/cyan]  "
                  f"[dim]({len(interactive)} elements)[/dim]")

    for el in interactive:
        console.print(f"[dim]{'  ' * depth}  → tapping '{el['label']}'…[/dim]")
        adb.tap(el["cx"], el["cy"], device)
        time.sleep(1.5)

        new_xml = adb.dump_ui(device)
        new_elements = adb.parse_elements(new_xml)
        new_fp = adb.screen_fingerprint(new_elements)
        new_type = guess_screen_type(new_elements)

        if new_fp != fp:
            screen_map.append({
                "from": screen_type,
                "via": el["label"],
                "to": new_type,
            })
            _explore_recursive(device, package, depth + 1, max_depth,
                                visited, screen_map, path + [screen_type])

        adb.back(device)
        time.sleep(1)


def _save_exploration(package: str, screen_map: list[dict]):
    recorder = FlowRecorder()
    for entry in screen_map:
        recorder.screenshot(f"explore_{entry['from'].replace(' ','_')}")
    recorder.save(package, "auto_explore")
    console.print("[green]Saved as flow 'auto_explore'.[/green]")


# ── Generate tests ────────────────────────────────────────────────────────────

def _generate_tests(package: str):
    try:
        out = gen_pytest(package, TESTS_DIR)
        console.print(f"[green]Generated: [bold]{out}[/bold][/green]")
        console.print(f"Run it with:  [cyan]python -m pytest {out} -v[/cyan]")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    banner()
    device = select_device()

    args = sys.argv[1:]
    if args and args[0] in ("train", "run", "list", "generate") and len(args) >= 2:
        cmd, package = args[0], args[1]
        label = adb.get_app_label(device, package)
        if cmd == "train":
            train_flow(device, package, label)
        elif cmd == "run":
            run_flows(device, package, label)
        elif cmd == "list":
            flows = list_flows(package)
            if flows:
                for f in flows:
                    console.print(f"  • {f}")
            else:
                console.print("[yellow]No flows recorded.[/yellow]")
        elif cmd == "generate":
            _generate_tests(package)
        return

    while True:
        package, label = select_app(device)
        app_menu(device, package, label)


if __name__ == "__main__":
    main()
