import hashlib
import os
import re
import time
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, RichLog, Static, TextArea

GAMES_DIR = Path("games")


# ── helpers ─────────────────────────────────────────────────────────────


def get_sessions() -> list[str]:
    if not GAMES_DIR.exists():
        return []
    return sorted(
        f
        for f in os.listdir(str(GAMES_DIR))
        if f.endswith(".md") and not f.startswith("default_")
    )


def get_defaults() -> list[str]:
    if not GAMES_DIR.exists():
        return []
    return sorted(
        f for f in os.listdir(str(GAMES_DIR)) if f.startswith("default_") and f.endswith(".md")
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


def create_session(name: str, default_file: str) -> str:
    raw = f"{name}{time.time()}".encode("utf-8")
    h = hashlib.md5(raw).hexdigest()[:8]
    filename = f"session_{h}.md"
    filepath = GAMES_DIR / filename
    template = (GAMES_DIR / default_file).read_text()
    content = template.replace("Name = ", f"Name = {name}", 1)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = content.replace(
        "[/history]",
        f"[{now}] Session started for {name}.\n[/history]",
    )
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
        lines    = ["0. Create a new game", "d. Delete a game", "q. Exit", ""]
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
                defaults = get_defaults()
                lines = ["Choose a template:"]
                for i, d in enumerate(defaults, 1):
                    label = d.replace("default_", "").replace(".md", "").upper()
                    lines.append(f"{i}. {label}")
                self.mode = "create_pick_default"
                self.query_one("#session-output", Static).update("\n".join(lines))
                inp.value = ""
                inp.placeholder = f"1–{len(defaults)}..."
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
            elif val.lower() == "q":
                self.app.exit()
            else:
                sessions = get_sessions()
                try:
                    idx = int(val) - 1
                    if 0 <= idx < len(sessions):
                        self.dismiss(("load", sessions[idx]))
                    else:
                        self.show_menu("Invalid selection.")
                except ValueError:
                    self.show_menu("Invalid input.")

        elif self.mode == "create_pick_default":
            defaults = get_defaults()
            try:
                idx = int(val) - 1
                if 0 <= idx < len(defaults):
                    self.chosen_default = defaults[idx]
                    self.mode = "create_name"
                    self.query_one("#session-output", Static).update(
                        "Enter character name:"
                    )
                    inp.value = ""
                    inp.placeholder = "Character name..."
                else:
                    self.show_menu("Invalid selection.")
            except ValueError:
                self.show_menu("Invalid input.")

        elif self.mode == "create_name":
            if not val:
                self.show_menu("Name cannot be empty.")
                return
            filename = create_session(val, self.chosen_default)
            self.dismiss(("new", filename))

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


# ── fill character screen ──────────────────────────────────────────────


class FillCharacterScreen(Screen):
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.fields: list[tuple[str, str]] = []
        self.current = 0
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="fill-output")
        yield Input(id="fill-input")
        yield Footer()

    def on_mount(self) -> None:
        content = (GAMES_DIR / self.filename).read_text()
        char_body = parse_section(content, "character")
        for line in char_body.split("\n"):
            if "=" in line:
                key, _, val = line.partition("=")
                if not val.strip():
                    self.fields.append((key.strip(), ""))
        self.show_next()

    def show_next(self) -> None:
        if self.current >= len(self.fields):
            self.save_all()
            self.dismiss(self.filename)
            return
        key, _ = self.fields[self.current]
        self.query_one("#fill-output", Static).update(
            f"Character field ({self.current+1}/{len(self.fields)}):\n{key} = ?"
        )
        inp = self.query_one("#fill-input", Input)
        inp.value = ""
        inp.placeholder = f"Enter {key}..."
        inp.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        key, _ = self.fields[self.current]
        self.fields[self.current] = (key, val)
        self.current += 1
        self.show_next()

    def save_all(self) -> None:
        filepath = GAMES_DIR / self.filename
        content = filepath.read_text()
        char_body = parse_section(content, "character")
        for key, val in self.fields:
            char_body = re.sub(
                rf"^{re.escape(key)}\s*=.*$",
                f"{key} = {val}",
                char_body,
                flags=re.MULTILINE,
            )
        content = replace_section(content, "character", char_body)
        filepath.write_text(content)


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
                with Vertical(id="character-area"):
                    yield Static(r"CHARACTER \[click here to edit\]", id="character-title")
                    yield TextArea(id="character-content", read_only=True)
                with Vertical(id="inventory-area"):
                    yield Static(r"INVENTORY \[click here to edit\]", id="inventory-title")
                    yield TextArea(id="inventory-content", read_only=True)
            with Vertical(id="history-panel"):
                yield Static("HISTORY", id="history-title")
                yield RichLog(id="history-content", highlight=True, markup=True)
        yield Input(placeholder="Write a message to history...", id="message-input")
        yield Footer()

    def on_mount(self) -> None:
        self.load_file()

    def load_file(self) -> None:
        filepath = GAMES_DIR / self.filename
        if not filepath.exists():
            return
        content = filepath.read_text()

        char_body = parse_section(content, "character")
        inv_body = parse_section(content, "inventory")
        hist_body = parse_section(content, "history")

        ta = self.query_one("#character-content", TextArea)
        if char_body:
            ta.text = char_body

        inv = self.query_one("#inventory-content", TextArea)
        if inv_body:
            inv.text = inv_body

        if hist_body:
            log = self.query_one("#history-content", RichLog)
            log.clear()
            for line in hist_body.split("\n"):
                log.write(line.strip())

    def on_click(self, event: Click) -> None:
        if not event.widget:
            return
        if event.widget.id == "character-title":
            self._toggle_edit("character")
        elif event.widget.id == "inventory-title":
            self._toggle_edit("inventory")

    def _toggle_edit(self, section: str) -> None:
        content_id = f"{section}-content"
        title_id = f"{section}-title"
        ta = self.query_one(f"#{content_id}", TextArea)
        title = self.query_one(f"#{title_id}", Static)
        label = section.upper()

        if ta.read_only:
            setattr(self, f"_old_{section}_text", ta.text)
            ta.read_only = False
            ta.focus()
            title.update(f"{label} \\[click here to save\\]")
        else:
            old = getattr(self, f"_old_{section}_text", ta.text)
            ta.read_only = True
            title.update(f"{label} \\[click here to edit\\]")
            self._save_section(section, old, ta.text)

    def _save_section(self, section: str, old_text: str, new_text: str) -> None:
        if new_text == old_text:
            return

        filepath = GAMES_DIR / self.filename
        if not filepath.exists():
            return

        content = filepath.read_text()
        content = replace_section(content, section, new_text)

        old_lines = old_text.split("\n")
        new_lines = new_text.split("\n")
        changes = []

        for i, old_line in enumerate(old_lines):
            if i < len(new_lines):
                if old_line != new_lines[i]:
                    old_val = old_line.partition("=")[2].strip() if "=" in old_line else old_line
                    new_val = new_lines[i].partition("=")[2].strip() if "=" in new_lines[i] else new_lines[i]
                    key = old_line.partition("=")[0].strip() if "=" in old_line else new_lines[i].partition("=")[0].strip()
                    changes.append(f"{key}: {old_val} → {new_val}")
            else:
                key = old_line.partition("=")[0].strip()
                changes.append(f"removed {key}")

        for i in range(len(old_lines), len(new_lines)):
            key = new_lines[i].partition("=")[0].strip()
            val = new_lines[i].partition("=")[2].strip()
            changes.append(f"added {key} = {val}")

        hist_body = parse_section(content, "history")
        log = self.query_one("#history-content", RichLog)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        for c in changes:
            entry = f"[{ts}] {section}: {c}"
            hist_body = (hist_body + "\n" + entry).strip()
            log.write(entry)
        content = replace_section(content, "history", hist_body)
        filepath.write_text(content)

    def action_back_to_menu(self) -> None:
        self.app.pop_screen()
        self.app.push_screen(SessionScreen(), callback=self.app.on_session_chosen)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not event.value.strip():
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"[{ts}] {event.value}"
        log = self.query_one("#history-content", RichLog)
        log.write(entry)
        event.input.clear()

        filepath = GAMES_DIR / self.filename
        if not filepath.exists():
            return
        content = filepath.read_text()
        hist_body = parse_section(content, "history")
        new_body = (hist_body + "\n" + entry).strip()
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
        padding: 0;
    }

    #character-area {
        height: 1fr;
        padding: 1;
    }

    #inventory-area {
        height: 1fr;
        padding: 1;
        border-top: solid $primary;
    }

    #history-panel {
        width: 67%;
        border: solid $secondary;
        padding: 1;
    }

    #character-title {
        text-style: bold;
        background: $primary 20%;
        padding: 0 1;
        width: 100%;
    }

    #inventory-title {
        text-style: bold;
        background: $accent 20%;
        padding: 0 1;
        width: 100%;
    }

    #history-title {
        text-style: bold;
        background: $secondary 20%;
        padding: 0 1;
        width: 100%;
    }

    #character-content {
        height: 1fr;
    }

    #inventory-content {
        height: 1fr;
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

    #fill-output {
        height: 1fr;
        margin: 1 2;
    }

    #fill-input {
        dock: bottom;
        height: 3;
        margin: 0 1;
    }
    """

    def on_mount(self) -> None:
        self.push_screen(SessionScreen(), callback=self.on_session_chosen)

    def on_session_chosen(self, result: tuple[str, str]) -> None:
        action, filename = result
        if action == "new":
            self.push_screen(FillCharacterScreen(filename), callback=self.on_character_filled)
        else:
            self.push_screen(GameScreen(filename))

    def on_character_filled(self, filename: str) -> None:
        self.push_screen(GameScreen(filename))


if __name__ == "__main__":
    app = GameManager()
    app.run()
