#!/usr/bin/env python3
"""Phone-first calorie logger TUI.

Log food and exercise, then see daily deficit plus exercise calories banked
for the day, week, and month. Data is stored locally as JSON.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Footer, Header, Input, Label, Static


EntryKind = Literal["food", "exercise"]

APP_DIR = Path(os.environ.get("CALLOG_HOME", Path.home() / ".local" / "share" / "calorie_logger"))
DB_PATH = Path(os.environ.get("CALLOG_DB", APP_DIR / "calorie_log.json"))
DEFAULT_BUDGET = int(os.environ.get("CALLOG_BUDGET", "2000"))


@dataclass(frozen=True)
class Entry:
    kind: EntryKind
    calories: int
    label: str
    created_at: int

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "Entry | None":
        kind = payload.get("kind")
        calories = _int(payload.get("calories"))
        created_at = _int(payload.get("created_at"))
        if kind not in ("food", "exercise") or calories is None or calories <= 0 or created_at is None:
            return None
        label = str(payload.get("label") or kind).strip() or kind
        return cls(kind=kind, calories=calories, label=label, created_at=created_at)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "calories": self.calories,
            "label": self.label,
            "created_at": self.created_at,
        }

    @property
    def day_key(self) -> str:
        return datetime.fromtimestamp(self.created_at).date().isoformat()


def _int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _start_of_today() -> datetime:
    now = datetime.now()
    return datetime(now.year, now.month, now.day)


def _start_of_week() -> datetime:
    today = _start_of_today()
    return today - timedelta(days=today.weekday())


def _start_of_month() -> datetime:
    today = _start_of_today()
    return datetime(today.year, today.month, 1)


def _fmt_signed(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)


class CalorieDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "created_at": int(time.time()), "daily_budget": DEFAULT_BUDGET, "entries": []}
        with self.path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError(f"{self.path} is not a JSON object.")
        loaded.setdefault("version", 1)
        loaded.setdefault("created_at", int(time.time()))
        loaded.setdefault("daily_budget", DEFAULT_BUDGET)
        loaded.setdefault("entries", [])
        if not isinstance(loaded["entries"], list):
            loaded["entries"] = []
        return loaded

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        tmp_path.replace(self.path)

    @property
    def daily_budget(self) -> int:
        return max(0, _int(self.data.get("daily_budget")) or DEFAULT_BUDGET)

    @daily_budget.setter
    def daily_budget(self, value: int) -> None:
        self.data["daily_budget"] = max(0, value)
        self.save()

    @property
    def entries(self) -> list[Entry]:
        raw_entries = self.data.get("entries", [])
        if not isinstance(raw_entries, list):
            return []
        entries = [Entry.from_json(item) for item in raw_entries if isinstance(item, dict)]
        return sorted((entry for entry in entries if entry is not None), key=lambda entry: entry.created_at)

    def add(self, kind: EntryKind, calories: int, label: str) -> Entry:
        entry = Entry(kind=kind, calories=calories, label=label.strip() or kind, created_at=int(time.time()))
        self.data.setdefault("entries", []).append(entry.to_json())
        self.save()
        return entry

    def delete_last(self) -> Entry | None:
        raw_entries = self.data.get("entries", [])
        if not isinstance(raw_entries, list) or not raw_entries:
            return None
        raw = raw_entries.pop()
        self.save()
        return Entry.from_json(raw) if isinstance(raw, dict) else None


class CalorieLoggerApp(App[None]):
    CSS = """
    Screen {
        background: $surface;
    }

    Header {
        dock: top;
    }

    Footer {
        dock: bottom;
    }

    #app {
        height: 100%;
        padding: 0 1;
    }

    #headline {
        padding: 1 0 0 0;
        text-style: bold;
        color: $accent;
    }

    .hint {
        color: $text-muted;
        height: 1;
    }

    Input {
        margin: 0 0 1 0;
    }

    Button {
        width: 1fr;
        margin: 0 0 1 0;
    }

    #actions {
        height: auto;
    }

    #actions Button {
        margin: 0 1 1 0;
    }

    #summary {
        border: tall $primary;
        padding: 0 1;
        margin: 0 0 1 0;
        height: auto;
    }

    .metric {
        height: auto;
        padding: 0;
    }

    #days_title,
    #recent_title {
        text-style: bold;
    }

    #days,
    #recent {
        height: 1fr;
        padding: 0 1;
    }

    #days {
        max-height: 9;
    }

    .ok {
        color: $success;
    }

    .bad {
        color: $error;
    }
    """

    BINDINGS = [
        ("e", "quick_food", "Eat"),
        ("x", "quick_exercise", "Exercise"),
        ("d", "delete_last", "Delete last"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.db = CalorieDatabase(DB_PATH)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="app"):
            yield Label("Calorie Logger", id="headline")
            yield Label("Food adds calories. Exercise banks them.", classes="hint")
            yield Input(placeholder="Calories", id="calories", type="integer")
            yield Input(placeholder="Label, e.g. lunch or walk", id="label")
            yield Input(value=str(self.db.daily_budget), placeholder="Daily budget", id="budget", type="integer")
            with Horizontal(id="actions"):
                yield Button("Eat", id="food", variant="error")
                yield Button("Exercise", id="exercise", variant="success")
            yield Static(id="summary")
            yield Label("Daily +/-", id="days_title")
            yield Static(id="days")
            yield Label("Recent", id="recent_title")
            yield Static(id="recent")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_view()
        self.query_one("#calories", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "food":
            self.log_entry("food")
        elif event.button.id == "exercise":
            self.log_entry("exercise")

    def action_quick_food(self) -> None:
        self.log_entry("food")

    def action_quick_exercise(self) -> None:
        self.log_entry("exercise")

    def action_delete_last(self) -> None:
        entry = self.db.delete_last()
        if entry is None:
            self.notify("No entries to delete", severity="warning")
        else:
            self.notify(f"Deleted {entry.kind}: {entry.calories} kcal")
        self.refresh_view()

    def log_entry(self, kind: EntryKind) -> None:
        budget_input = self.query_one("#budget", Input)
        budget = _int(budget_input.value)
        if budget is not None:
            self.db.daily_budget = budget

        calories_input = self.query_one("#calories", Input)
        label_input = self.query_one("#label", Input)
        calories = _int(calories_input.value)
        if calories is None or calories <= 0:
            self.notify("Enter calories greater than 0", severity="error")
            calories_input.focus()
            return

        self.db.add(kind, calories, label_input.value)
        calories_input.value = ""
        label_input.value = ""
        calories_input.focus()
        self.refresh_view()

    def refresh_view(self) -> None:
        entries = self.db.entries
        self.query_one("#summary", Static).update(self.summary_text(entries))
        self.query_one("#days", Static).update(self.daily_tally_text(entries))
        recent_lines = [self.entry_line(entry) for entry in reversed(entries[-12:])]
        self.query_one("#recent", Static).update("\n".join(recent_lines) or "No entries yet")

    def summary_text(self, entries: list[Entry]) -> str:
        today_start = int(_start_of_today().timestamp())
        week_start = int(_start_of_week().timestamp())
        month_start = int(_start_of_month().timestamp())
        today = [entry for entry in entries if entry.created_at >= today_start]

        food_today = sum(entry.calories for entry in today if entry.kind == "food")
        exercise_today = sum(entry.calories for entry in today if entry.kind == "exercise")
        daily_balance = self.db.daily_budget + exercise_today - food_today
        css_class = "ok" if daily_balance >= 0 else "bad"

        exercise_week = sum(
            entry.calories for entry in entries if entry.kind == "exercise" and entry.created_at >= week_start
        )
        exercise_month = sum(
            entry.calories for entry in entries if entry.kind == "exercise" and entry.created_at >= month_start
        )
        day_count = len({entry.day_key for entry in entries if entry.created_at >= month_start})
        month_food = sum(entry.calories for entry in entries if entry.kind == "food" and entry.created_at >= month_start)
        month_exercise = exercise_month
        month_balance = (self.db.daily_budget * day_count) + month_exercise - month_food

        return (
            f"Today: food {food_today} | ex {exercise_today}\n"
            f"Daily +/-: [{css_class}]{_fmt_signed(daily_balance)} kcal[/]\n"
            f"Exercise banked: day {exercise_today}\n"
            f"Week {exercise_week} | Month {exercise_month}\n"
            f"Month tally: {_fmt_signed(month_balance)} kcal"
        )

    def daily_tally_text(self, entries: list[Entry]) -> str:
        today = _start_of_today()
        lines: list[str] = []
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            next_day = day + timedelta(days=1)
            day_start = int(day.timestamp())
            day_end = int(next_day.timestamp())
            day_entries = [entry for entry in entries if day_start <= entry.created_at < day_end]
            food = sum(entry.calories for entry in day_entries if entry.kind == "food")
            exercise = sum(entry.calories for entry in day_entries if entry.kind == "exercise")
            balance = self.db.daily_budget + exercise - food
            marker = "today" if offset == 0 else day.strftime("%a")
            lines.append(f"{marker:5} {day:%m-%d} {_fmt_signed(balance)}")
        return "\n".join(lines)

    def entry_line(self, entry: Entry) -> str:
        dt = datetime.fromtimestamp(entry.created_at)
        sign = "-" if entry.kind == "food" else "+"
        name = "eat" if entry.kind == "food" else "ex"
        return f"{dt:%m-%d %H:%M} {name:3} {sign}{entry.calories:4} {entry.label}"


if __name__ == "__main__":
    CalorieLoggerApp().run()
