"""Textual dashboard for replaying LeanSilicon FPGA evidence."""
from __future__ import annotations
import argparse
from pathlib import Path

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, RichLog, Static

from .model import EventKind, Replay, load_evidence

CSS = """
$bg: #101217; $surface: #181b22; $raised: #222731; $border: #3b4352;
$text: #eee9df; $muted: #9aa3b2; $host: #f2ae72; $fpga: #64d2c8;
$ok: #80d98b; $warn: #f0c36a; $error: #f07b7b; $pc: #d5a6e6;
Screen { background: $bg; color: $text; }
Header { height: 3; background: $surface; color: $text; }
#status { height: 4; padding: 1 2; background: $surface; color: $muted; }
#status .host { color: $host; } #status .fpga { color: $fpga; }
#workspace { height: 1fr; padding: 0 1; }
.column { width: 1fr; }
.panel { background: $surface; border: round $border; margin: 0 1 1 0; padding: 0 1; }
.panel:focus-within { border: round $pc; }
.title { height: 2; color: $muted; text-style: bold; padding-top: 1; }
#source { height: 9; } #instructions { height: 1fr; min-height: 11; }
#transaction { height: 14; border: round $pc; background: $raised; }
#transaction .title { color: $pc; }
#memory { height: 1fr; min-height: 11; }
#events { width: 30%; min-width: 32; }
RichLog { scrollbar-color: $border; scrollbar-background: $surface; }
#searchbar { display: none; height: 3; margin: 0 1 1 0; border: round $pc; background: $raised; }
#searchbar.visible { display: block; }
#terminal { height: 3; padding: 1 2; background: $raised; color: $muted; }
#terminal.complete { height: 6; padding: 1 2; color: $ok; background: #183020; border: round $ok; text-style: bold; }
#terminal.error { color: $error; text-style: bold; }
Footer { height: 1; background: $surface; color: $muted; }
Screen.narrow #workspace { layout: vertical; overflow-y: auto; }
Screen.narrow .column, Screen.narrow #events { width: 100%; min-width: 0; height: auto; }
Screen.narrow Header { height: 2; }
Screen.narrow #status { height: 6; padding: 1; }
Screen.narrow #source { height: 8; } Screen.narrow #instructions { height: 9; }
Screen.narrow #transaction { height: 12; } Screen.narrow #memory { height: 14; }
Screen.narrow #events { height: 12; }
Screen.narrow #terminal { height: 4; padding: 1; }
Screen.narrow #terminal.complete { height: 7; }
Screen.narrow Footer { display: none; }
"""


class SiliconLive(App):
    TITLE = "SILICON LIVE"
    SUB_TITLE = "evidence replay · no board"
    CSS = CSS
    BINDINGS = [
        Binding("space", "toggle", "Run/Pause", priority=True),
        Binding("s", "step", "Step"), Binding("r", "restart", "Restart"),
        Binding("+", "faster", "Faster"), Binding("-", "slower", "Slower"),
        Binding("/", "search", "Search"), Binding("i", "inspect", "Inspect"),
        Binding("tab", "focus_next", "Next panel"),
        Binding("question_mark", "help", "Help"), Binding("ctrl+p", "command_palette", "Commands"),
        Binding("q", "quit", "Quit"),
    ]
    playing = reactive(False)
    speed = reactive(1.0)

    def __init__(self, evidence_path: Path | None = None, auto_run: bool = True) -> None:
        super().__init__()
        self.replay = Replay(load_evidence(evidence_path) if evidence_path else load_evidence())
        self.auto_run = auto_run
        self._timer = None

    def compose(self) -> ComposeResult:
        yield Header(icon="")
        yield Static(id="status")
        with Horizontal(id="workspace"):
            with Vertical(classes="column"):
                with Container(classes="panel", id="source"):
                    yield Label("SOURCE · zkDSL · mapping ≈ approximate", classes="title")
                    yield Static(id="source_text")
                with Container(classes="panel", id="instructions"):
                    yield Label("DISASSEMBLY · PC CONTEXT", classes="title")
                    yield RichLog(id="instruction_log", highlight=True, markup=True)
            with Vertical(classes="column"):
                with Container(classes="panel", id="transaction"):
                    yield Label("TRANSACTION · HOST → FPGA → HOST", classes="title")
                    yield Static(id="transaction_text")
                with Container(classes="panel", id="memory"):
                    yield Label("VM MEMORY · exact u128 hex", classes="title")
                    yield RichLog(id="memory_log", highlight=True, markup=True)
            with Container(classes="panel", id="events"):
                yield Label("EVENT STREAM · execution only", classes="title")
                yield RichLog(id="event_log", highlight=True, markup=True)
        yield Input(placeholder="Search instruction, cell, op, or event…", id="searchbar")
        yield Static("READY · SPACE run · S step · ? help", id="terminal")
        yield Footer()

    def on_mount(self) -> None:
        self._timer = self.set_interval(.45, self._tick, pause=True)
        self._render_all()
        if self.auto_run:
            self.playing = True
            self._timer.resume()

    def on_resize(self, event) -> None:
        self.screen.set_class(event.size.width < 92, "narrow")

    def _tick(self) -> None:
        if not self.playing:
            return
        if not self.replay.advance():
            self.playing = False
            self._timer.pause()
        self._render_all()

    def _render_all(self) -> None:
        ev, cursor = self.replay.evidence, self.replay.cursor
        pc = ev.steps[cursor].pc if cursor < len(ev.steps) else cursor
        state = "PAUSED" if not self.playing and self.replay.state == "RUNNING" else self.replay.state
        if self.size.width < 92:
            status = (
                f"[#9aa3b2]PROGRAM ·[/]  [#eee9df b]assert_set_xor_mul[/]\n"
                f"[#9aa3b2]BACKEND ·[/]  [#64d2c8 b]FPGA EVIDENCE[/]   [#9aa3b2]LINK ·[/]  replay · offline\n"
                f"[#9aa3b2]STATE ·[/]  [#f0c36a b]{state}[/]   [#9aa3b2]STEP ·[/]  [#eee9df b]{cursor} / 12[/]   "
                f"[#9aa3b2]PC ·[/]  [#d5a6e6 b]{pc:02d}[/]   [#9aa3b2]FP ·[/]  {ev.fp}"
            )
        else:
            status = (
                f"[#9aa3b2]PROGRAM[/]  [#eee9df b]assert_set_xor_mul[/]    "
                f"[#9aa3b2]BACKEND[/]  [#64d2c8 b]FPGA EVIDENCE[/]    "
                f"[#9aa3b2]LINK[/]  [#f2ae72]offline · replay[/]\n"
                f"[#9aa3b2]STATE[/]  [#f0c36a b]{state}[/]    "
                f"[#9aa3b2]STEP[/]  [#eee9df b]{cursor} / 12[/]    "
                f"[#9aa3b2]PC[/]  [#d5a6e6 b]{pc:02d}[/]    [#9aa3b2]FP[/]  {ev.fp}"
            )
        self.query_one("#status", Static).update(status)
        source_lines = ev.source.splitlines()
        approx = min(len(source_lines) - 1, 1 + (cursor * max(1, len(source_lines)-2) // 12))
        source = "\n".join(
            f"[#d5a6e6]▸[/] [reverse]{escape(line)}[/reverse]" if i == approx
            else f"  [#9aa3b2]{i+1:02d} │[/] {escape(line)}"
            for i, line in enumerate(source_lines)
        )
        self.query_one("#source_text", Static).update(source)
        ilog = self.query_one("#instruction_log", RichLog); ilog.clear()
        for ins in ev.instructions[max(0, pc-3):min(len(ev.instructions), pc+5)]:
            marker = "[#d5a6e6 b]▶[/]" if ins.pc == pc else " "
            instruction = ins.text.split(maxsplit=1)[1]
            ilog.write(
                f"{marker} [on #44334f #fff4ff b] PC {ins.pc:02d} │ {escape(instruction)} [/]"
                if ins.pc == pc else f"{marker} [#9aa3b2]PC {ins.pc:02d} │[/] {escape(instruction)}"
            )
        mlog = self.query_one("#memory_log", RichLog); mlog.clear()
        active = ev.steps[cursor-1] if cursor else None
        for address in range(12):
            value = self.replay.memory.get(address, 0)
            tag = "[on #5a451e #ffe2a1 b] READ [/]" if active and address in active.reads else (
                "[on #214b2c #aaf5b4 b] WRITE[/]" if active and address in active.writes else "      ")
            exact = f"{value:032x}"
            grouped = f"{exact[:8]} · {exact[8:16]} · {exact[-8:]}"
            mlog.write(f"{tag} [#9aa3b2]m{address:02d}[/]  {grouped}")
        t = self.query_one("#transaction_text", Static)
        if active:
            def compact(wire: bytes) -> str:
                value = wire.hex()
                return f"{value[:8]} … {value[-8:]}" if len(value) > 20 else " ".join(
                    value[i:i+8] for i in range(0, len(value), 8))
            exact_result = f"{active.result:032x}"
            result = f"{exact_result[:12]} … {exact_result[-12:]}"
            t.update(
                f"[on #573721 #ffd1a8 b] HOST [/][#eee9df b]  PREPARE[/]  {active.kind}\n"
                f"       [#9aa3b2]TX · {len(active.request):02d} bytes[/]  {compact(active.request)}\n"
                f"                    [#9aa3b2]exact value: press I[/]\n"
                f"[on #174b4a #a7fff6 b] FPGA [/][#eee9df b]  COMPUTE[/]  PC {active.pc:02d}\n"
                f"       [#9aa3b2]RX · {len(active.response):02d} bytes[/]  {compact(active.response)}\n"
                f"[on #573721 #ffd1a8 b] HOST [/][#eee9df b]  VALIDATE[/]  →  [on #214b2c #aaf5b4 b] WRITE m{active.writes[0]:02d} [/]\n"
                f"       [#80d98b]0x{result}[/]"
            )
        else:
            t.update("[on #573721 #ffd1a8 b] HOST [/][#9aa3b2]  waiting[/]\n\n"
                     "[on #174b4a #a7fff6 b] FPGA [/][#9aa3b2]  ready for replay[/]\n\n"
                     "[#9aa3b2]Step once to inspect the exact PC → FPGA → PC exchange.[/]")
        elog = self.query_one("#event_log", RichLog); elog.clear()
        actor_colors = {"HOST": "#d9a36c", "FPGA": "#70b8b0"}
        labels = {
            EventKind.PREPARE: "PREP", EventKind.UART_SEND: "TX",
            EventKind.FPGA_COMPUTE: "COMPUTE", EventKind.RESPONSE: "RX",
            EventKind.VALIDATE: "CHECK", EventKind.MEMORY_WRITE: "WRITE",
            EventKind.HALT: "HALT", EventKind.ERROR: "FAULT",
        }
        for event in self.replay.events[-18:]:
            color = "#f07b7b" if event.kind == EventKind.ERROR else actor_colors[event.actor]
            message = event.message.replace("response ", "").replace("memory ", "")
            message = message.replace(" bytes", " B").replace("write mem", "m")
            message = message.removeprefix("prepare ").removeprefix("compute ")
            if message.startswith("m["):
                message = f"m{int(message[2:-1]):02d}"
            if event.kind == EventKind.HALT:
                message = "prefix matched"
            actor_bg = "#573721" if event.actor == "HOST" else "#174b4a"
            elog.write(f"[#9aa3b2]{event.pc:02d}[/] [on {actor_bg} {color} b] {event.actor:<4} [/]"
                       f" [#9aa3b2]{labels[event.kind]:<7} │[/] {escape(message)}")
        term = self.query_one("#terminal", Static)
        term.remove_class("complete", "error")
        if self.replay.terminal:
            term.update(f"[#80d98b b]PREFIX MATCH ✓[/]   [#d7f4dc]expected execution prefix reproduced exactly[/]\n"
                        f"[#9aa3b2]evidence replay · no board[/]   [#f0c36a]LIMITATION —[/] {ev.reason}")
            term.add_class("complete" if self.replay.terminal.startswith("PREFIX") else "error")
        else:
            compact_nav = "SPACE run · S step · R restart · / search · ? help"
            term.update(
                f"[#f0c36a b]{state}[/]  ·  {compact_nav}" if self.size.width < 92 else
                f"[#f0c36a b]{state}[/]  ·  SPACE run/pause · S step · R restart · +/- {self.speed:.1f}× · / search · I exact data · ? help"
            )

    def action_toggle(self) -> None:
        if self.replay.terminal:
            return
        self.playing = not self.playing
        self._timer.resume() if self.playing else self._timer.pause()
        self._render_all()

    def action_step(self) -> None:
        self.playing = False; self._timer.pause()
        self.replay.advance(); self._render_all()

    def action_restart(self) -> None:
        self.playing = False; self._timer.pause()
        self.replay.restart(); self._render_all()

    def action_faster(self) -> None:
        self.speed = min(8.0, self.speed * 2); self._timer.interval = .45 / self.speed
    def action_slower(self) -> None:
        self.speed = max(.25, self.speed / 2); self._timer.interval = .45 / self.speed
    def action_search(self) -> None:
        box = self.query_one("#searchbar", Input); box.add_class("visible"); box.focus()
    def action_help(self) -> None:
        self.notify("SPACE run/pause · S step · R restart · +/- speed · / search · I inspect · TAB panels · Ctrl+P commands · Q quit",
                    title="Keyboard help", timeout=8)
    def action_inspect(self) -> None:
        if not self.replay.cursor:
            self.notify("No transaction has executed yet.", title="Inspector")
            return
        step = self.replay.evidence.steps[self.replay.cursor - 1]
        self.notify(
            f"PC {step.pc} {step.kind}\nTX {step.request.hex()}\nRX {step.response.hex()}\n"
            f"m[{step.writes[0]}] = 0x{step.result:032x}",
            title="Exact transaction", timeout=10,
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.lower().strip()
        event_matches = [e for e in self.replay.events if query in e.message.lower() or query in e.kind.value]
        instruction_matches = [i for i in self.replay.evidence.instructions
                               if query in i.text.lower() or query == str(i.pc)]
        memory_matches = [address for address, value in self.replay.memory.items()
                          if query in {str(address), f"m{address}", f"m[{address}]"} or query in f"{value:032x}"]
        self.notify(f"{len(instruction_matches)} instructions · {len(memory_matches)} cells · "
                    f"{len(event_matches)} events",
                    title=f"Search: {query or 'all'}")
        event.input.remove_class("visible"); self.set_focus(None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Silicon Live FPGA execution dashboard")
    parser.add_argument("--demo", action="store_true", help="animate the committed 12-step FPGA evidence")
    parser.add_argument("--evidence", type=Path, help="compatible program-run.json")
    args = parser.parse_args(argv)
    if not args.demo and not args.evidence:
        parser.error("choose --demo or --evidence PATH")
    SiliconLive(args.evidence, auto_run=True).run()
    return 0
