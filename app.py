import hashlib
import os
import re
import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, RichLog, Static

GAMES_DIR = Path("games")
DEFAULT_TEMPLATE = """[character]
Name = 
Class = 
Level = 1
HP = 
AC = 
[/character]

[history]
[/history]
"""


# ── helpers ─────────────────────────────────────────────────────────────


def get_sessions() -> list[str]:
    if not GAMES_DIR.exists():
        return []
    return sorted(
        f
        for f in os.listdir(str(GAMES_DIR))
        if f.endswith(".md") and f != "default.md"
    )


def parse_section(content: str, section: str) -> str:
    m = re.search(rf"\[{section}\](.*?)\[/{section}\]", content, re.DOTALL)
    return m.group(1).strip() if m else ""


def replace_section(content: str, section: str, body: str) -> str:
    return re.sub(
        rf"\[{section}\].*?\[/{section}\]",
        f"[{section}]\n{body}\n[/{section}]",
        content,
        flags=re.DOTALL,
    )


def create_session(name: str, char_class: str) -> str:
    raw = f"{name}{time.time()}".encode("utf-8")
    h = hashlib.md5(raw).hexdigest()[:8]
    filename = f"session_{h}.md"
    filepath = GAMES_DIR / filename
    content = f"""[character]
Name = {name}
Class = {char_class}
Level = 1
HP =
AC =
[/character]

[history]
Session started for {name} the {char_class}.
[/history]
"""
    filepath.write_text(content)
    return filename


# ── session screen ─────────────────────────────────────────────────────


class SessionScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="session-output")
        yield Input(id="session-input")
        yield Footer()

    def on_mount(self) -> None:
        self.mode = "menu"
        self.show_menu()

    def show_menu(self, msg: str = "") -> None:
        self.mode = "menu"
        sessions = get_sessions()
        lines = ["0. Create a new game", "d. Delete a game", ""]
        if not sessions:
            lines.append("No saved games found.")
        else:
            for i, s in enumerate(sessions, 1):
                content = (GAMES_DIR / s).read_text()
                name = parse_section(content, "character")
                name = name.split("\n")[0] if name else "???"
                name = re.sub(r"^Name\s*[=:]\s*", "", name).strip()
                lines.append(f"{i}. {s.replace('.md','')}  —  {name}")
        if msg:
            lines.extend(["", msg])
        self.query_one("#session-output", Static).update("\n".join(lines))
        inp = self.query_one("#session-input", Input)
        inp.value = ""
        inp.placeholder = "Enter choice (0=new, #=load, d=delete)..."
        inp.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        inp = self.query_one("#session-input", Input)

        if self.mode == "menu":
            if val == "0":
                self.mode = "create_name"
                self.query_one("#session-output", Static).update(
                    "Enter character name:"
                )
                inp.value = ""
                inp.placeholder = "Character name..."
            elif val.lower() == "d":
                sessions = get_sessions()
                if not sessions:
                    self.show_menu("No sessions to delete.")
                    return
                self.mode = "delete_select"
                lines = ["Enter number to DELETE (or 'c' to cancel):"]
                for i, s in enumerate(sessions, 1):
                    lines.append(f"{i}. {s}")
                self.query_one("#session-output", Static).update("\n".join(lines))
                inp.value = ""
                inp.placeholder = "Number or 'c'..."
            else:
                sessions = get_sessions()
                try:
                    idx = int(val) - 1
                    if 0 <= idx < len(sessions):
                        self.dismiss(sessions[idx])
                    else:
                        self.show_menu("Invalid selection.")
                except ValueError:
                    self.show_menu("Invalid input.")

        elif self.mode == "create_name":
            if not val:
                self.show_menu("Name cannot be empty.")
                return
            self.new_name = val
            self.mode = "create_class"
            self.query_one("#session-output", Static).update(
                "Choose class:\n1. Warrior\n2. Rogue\n3. Wizard"
            )
            inp.value = ""
            inp.placeholder = "1, 2, or 3..."

        elif self.mode == "create_class":
            class_map = {"1": "Warrior", "2": "Rogue", "3": "Wizard"}
            char_class = class_map.get(val, "Warrior")
            filename = create_session(self.new_name, char_class)
            self.dismiss(filename)

        elif self.mode == "delete_select":
            if val.lower() == "c":
                self.show_menu()
                return
            sessions = get_sessions()
            try:
                idx = int(val) - 1
                if 0 <= idx < len(sessions):
                    self.delete_target = sessions[idx]
                    content = (GAMES_DIR / sessions[idx]).read_text()
                    name = parse_section(content, "character")
                    name = name.replace("Name = ", "").strip() if name else "???"
                    self.mode = "delete_confirm"
                    self.query_one("#session-output", Static).update(
                        f"Delete '{name}' ({sessions[idx]})?\nEnter 'y' to confirm."
                    )
                    inp.value = ""
                    inp.placeholder = "y/N..."
                else:
                    self.show_menu("Invalid selection.")
            except ValueError:
                self.show_menu("Invalid input.")

        elif self.mode == "delete_confirm":
            if val.lower() == "y":
                (GAMES_DIR / self.delete_target).unlink()
            self.show_menu()

        inp.focus()


# ── game screen ────────────────────────────────────────────────────────


class GameScreen(Screen):
    BINDINGS = [
        ("escape", "back_to_menu", "Menu"),
    ]

    def __init__(self, filename: str) -> None:
        self.filename = filename
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-area"):
            with Vertical(id="character-panel"):
                yield Static("[character]", id="panel-title")
                yield Static(id="character-content")
            with Vertical(id="history-panel"):
                yield Static("[history]", id="panel-title")
                yield RichLog(id="history-content", highlight=True, markup=True)
        yield Input(placeholder="Write a message to history...", id="message-input")
        yield Footer()

    def on_mount(self) -> None:
        self.load_file()

    def load_file(self) -> None:
        filepath = GAMES_DIR / self.filename
        if not filepath.exists():
            self.query_one("#character-content", Static).update("File not found.")
            return
        content = filepath.read_text()

        char_body = parse_section(content, "character")
        hist_body = parse_section(content, "history")

        if char_body:
            self.query_one("#character-content", Static).update(char_body)

        if hist_body:
            log = self.query_one("#history-content", RichLog)
            log.clear()
            for line in hist_body.split("\n"):
                log.write(line.strip())

    def action_back_to_menu(self) -> None:
        self.app.pop_screen()
        self.app.push_screen(SessionScreen(), callback=self.app.on_session_chosen)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not event.value.strip():
            return
        log = self.query_one("#history-content", RichLog)
        log.write(event.value)
        event.input.clear()

        filepath = GAMES_DIR / self.filename
        if not filepath.exists():
            return
        content = filepath.read_text()
        hist_body = parse_section(content, "history")
        new_body = (hist_body + "\n" + event.value).strip()
        content = replace_section(content, "history", new_body)
        filepath.write_text(content)


# ── app ────────────────────────────────────────────────────────────────


class GameManager(App):
    CSS = """
    Screen {
        layout: vertical;
    }

    #main-area {
        height: 1fr;
    }

    #character-panel {
        width: 33%;
        border: solid $primary;
        padding: 1;
    }

    #history-panel {
        width: 67%;
        border: solid $secondary;
        padding: 1;
    }

    #panel-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #history-content {
        height: 1fr;
    }

    #message-input {
        dock: bottom;
        height: 3;
        margin: 0 1;
    }

    #session-output {
        height: 1fr;
        margin: 1 2;
    }

    #session-input {
        dock: bottom;
        height: 3;
        margin: 0 1;
    }
    """

    def on_mount(self) -> None:
        self.push_screen(SessionScreen(), callback=self.on_session_chosen)

    def on_session_chosen(self, filename: str) -> None:
        self.push_screen(GameScreen(filename))


if __name__ == "__main__":
    app = GameManager()
    app.run()
