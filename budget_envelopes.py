#!/usr/bin/env python3
"""Phone-first envelope budgeting TUI.

Track income, expenses, virtual envelope funding, and envelope transfers.
Data is stored locally as JSON.
"""

from __future__ import annotations

import calendar
import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from textual.app import App, ComposeResult
from textual.containers import Grid, Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Button, Digits, Header, Input, Label, Static


TransactionKind = Literal["income", "fund", "expense", "transfer", "adjust"]

APP_DIR = Path(os.environ.get("BUDGET_HOME", Path.home() / ".local" / "share" / "budget_envelopes"))
DB_PATH = Path(os.environ.get("BUDGET_DB", APP_DIR / "budget_envelopes.json"))
CURRENCY = os.environ.get("BUDGET_CURRENCY", "R")


def _payday_day() -> int:
    try:
        value = int(os.environ.get("BUDGET_PAYDAY_DAY", "25"))
    except ValueError:
        value = 25
    return max(1, min(31, value))


PAYDAY_DAY = _payday_day()


@dataclass(frozen=True)
class Transaction:
    kind: TransactionKind
    cents: int
    note: str
    created_at: int
    source: str | None = None
    target: str | None = None

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "Transaction | None":
        kind = payload.get("kind")
        cents = _int(payload.get("cents"))
        created_at = _int(payload.get("created_at"))
        if kind not in ("income", "fund", "expense", "transfer", "adjust"):
            return None
        if cents is None or cents == 0 or created_at is None:
            return None
        # Only "adjust" may carry a negative delta. Everything else is positive.
        if kind != "adjust" and cents < 0:
            return None
        source = _clean_account(payload.get("source"), allow_pool=True)
        # Adjust targets the pool too, so allow_pool=True for adjust.
        target = _clean_account(payload.get("target"), allow_pool=(kind == "adjust"))
        note = str(payload.get("note") or kind).strip() or kind
        return cls(
            kind=kind,
            cents=cents,
            note=note,
            created_at=created_at,
            source=source,
            target=target,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "cents": self.cents,
            "note": self.note,
            "created_at": self.created_at,
            "source": self.source,
            "target": self.target,
        }


def _int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _money_to_cents(value: str) -> int | None:
    cleaned = value.strip().replace(",", ".").replace("R", "").replace("$", "")
    if CURRENCY:
        cleaned = cleaned.replace(CURRENCY, "")
    if not cleaned:
        return None
    try:
        amount = float(cleaned)
    except ValueError:
        return None
    cents = int(round(amount * 100))
    return cents if cents > 0 else None


def _money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{CURRENCY}{cents // 100}.{cents % 100:02d}"


def _signed_money(cents: int) -> str:
    return f"+{_money(cents)}" if cents >= 0 else _money(cents)


def _money_grouped(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{CURRENCY}{cents // 100:,}.{cents % 100:02d}"


def _build_details(
    *,
    per_day: int,
    per_week: int,
    spent_7d: int,
    spent_30d: int,
    last_income_cents: int | None,
    last_income_date: date | None,
    next_payday: date,
    days_to_payday: int,
) -> str:
    """Format the Home details panel — left-aligned labels, right-aligned amounts."""
    col = 28  # total width per row; tweak per terminal width

    def row(label: str, cents: int, color: str = "") -> str:
        amt = _money_grouped(cents)
        pad = max(1, col - len(label) - len(amt))
        return (
            f"  {label}{' ' * pad}[{color}]{amt}[/]"
            if color
            else f"  {label}{' ' * pad}{amt}"
        )

    if last_income_cents is not None and last_income_date is not None:
        income_block = (
            "[b $accent]Last income[/]\n"
            f"{row(last_income_date.strftime('%a %d %b'), last_income_cents, 'ok')}\n"
            "\n"
        )
    else:
        income_block = ""

    if days_to_payday == 1:
        countdown = "Payday tomorrow"
    else:
        countdown = f"Payday in {days_to_payday} days"

    return (
        f"[b $warning]{countdown}[/]: [dim]{next_payday:%a %d %b %Y}[/]\n"
        "\n"
        "[b $accent]Budget[/]\n"
        f"{row('Per day', per_day)}\n"
        f"{row('Per week', per_week)}\n"
        "\n"
        "[b $accent]Spend[/]\n"
        f"{row('Last 7 days', spent_7d, 'bad' if spent_7d else '')}\n"
        f"{row('Last 30 days', spent_30d, 'bad' if spent_30d else '')}\n"
        "\n"
        f"{income_block.rstrip()}"
    )


def _clean_account(value: Any, *, allow_pool: bool) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if allow_pool and text.casefold() in ("pool", "unallocated", "unallocated pool"):
        return "pool"
    if text.casefold() == "pool":
        return None
    return " ".join(text.split())


def _start_of_today() -> datetime:
    now = datetime.now()
    return datetime(now.year, now.month, now.day)


def _start_of_week() -> datetime:
    today = _start_of_today()
    return today - timedelta(days=today.weekday())


def _clamped_month_day(year: int, month: int, preferred_day: int) -> date:
    return date(year, month, min(preferred_day, calendar.monthrange(year, month)[1]))


def _add_month(anchor: date) -> date:
    year = anchor.year + (1 if anchor.month == 12 else 0)
    month = 1 if anchor.month == 12 else anchor.month + 1
    return _clamped_month_day(year, month, PAYDAY_DAY)


def _previous_month(anchor: date) -> date:
    year = anchor.year - (1 if anchor.month == 1 else 0)
    month = 12 if anchor.month == 1 else anchor.month - 1
    return _clamped_month_day(year, month, PAYDAY_DAY)


def _payday_for_month(day: date) -> date:
    return _clamped_month_day(day.year, day.month, PAYDAY_DAY)


def _next_payday(today: date | None = None, next_payday_str: str | None = None) -> date:
    """Return the upcoming payday.

    Priority:
      1. User-set ``next_payday`` from the DB (auto-rolled forward by a month
         if the stored date is already in the past).
      2. Fallback to PAYDAY_DAY env-var derived calculation.
    """
    today = today or date.today()

    if next_payday_str:
        try:
            pd = date.fromisoformat(next_payday_str)
            while pd <= today:
                pd = _add_month(pd)
            return pd
        except (ValueError, TypeError):
            pass

    payday = _payday_for_month(today)
    if today >= payday:
        payday = _add_month(payday)
    return payday


def _current_pay_cycle_start(today: date | None = None) -> date:
    today = today or date.today()
    payday = _payday_for_month(today)
    if today >= payday:
        return payday
    return _previous_month(payday)


class BudgetDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "version": 1,
                "created_at": int(time.time()),
                "transactions": [],
                "envelopes": [],
            }
        with self.path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError(f"{self.path} is not a JSON object.")
        loaded.setdefault("version", 1)
        loaded.setdefault("created_at", int(time.time()))
        loaded.setdefault("transactions", [])
        loaded.setdefault("last_payday", None)
        loaded.setdefault("next_payday", None)
        loaded.setdefault("envelopes", [])
        if not isinstance(loaded["transactions"], list):
            loaded["transactions"] = []
        if not isinstance(loaded["envelopes"], list):
            loaded["envelopes"] = []

        # Migration: ensure every envelope referenced in transactions is in the list.
        seen: dict[str, None] = {
            n: None for n in loaded["envelopes"] if isinstance(n, str) and n.strip()
        }
        for tx_data in loaded["transactions"]:
            if not isinstance(tx_data, dict):
                continue
            for field in ("source", "target"):
                val = tx_data.get(field)
                if isinstance(val, str) and val.strip() and val.casefold() != "pool":
                    seen.setdefault(val, None)
        loaded["envelopes"] = sorted(seen.keys(), key=str.casefold)
        return loaded

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        tmp_path.replace(self.path)

    @property
    def transactions(self) -> list[Transaction]:
        raw_transactions = self.data.get("transactions", [])
        if not isinstance(raw_transactions, list):
            return []
        transactions = [
            Transaction.from_json(item)
            for item in raw_transactions
            if isinstance(item, dict)
        ]
        return sorted((tx for tx in transactions if tx is not None), key=lambda tx: tx.created_at)

    def add(
        self,
        kind: TransactionKind,
        cents: int,
        note: str,
        source: str | None = None,
        target: str | None = None,
    ) -> Transaction:
        tx = Transaction(
            kind=kind,
            cents=cents,
            note=note.strip() or kind,
            source=source,
            target=target,
            created_at=int(time.time()),
        )
        self.data.setdefault("transactions", []).append(tx.to_json())
        # Auto-register any envelope names referenced in this transaction so
        # they show up in the envelope list even before any further activity.
        for ref in (source, target):
            if isinstance(ref, str) and ref.strip() and ref.casefold() != "pool":
                self._ensure_envelope_in_memory(ref)
        self.save()
        return tx

    # ---- Envelope-list management -------------------------------------------------

    @property
    def envelope_names(self) -> list[str]:
        names = self.data.get("envelopes", [])
        if not isinstance(names, list):
            return []
        return [n for n in names if isinstance(n, str) and n.strip()]

    def _ensure_envelope_in_memory(self, name: str) -> bool:
        """Add an envelope to the in-memory list if missing. Returns True if added."""
        name = " ".join(name.split())
        if not name or name.casefold() == "pool":
            return False
        current = self.data.setdefault("envelopes", [])
        if any(isinstance(n, str) and n.casefold() == name.casefold() for n in current):
            return False
        current.append(name)
        current.sort(key=lambda n: n.casefold() if isinstance(n, str) else "")
        return True

    def add_envelope(self, name: str) -> bool:
        """Register a new envelope name. Returns True if it was newly added."""
        added = self._ensure_envelope_in_memory(name)
        if added:
            self.save()
        return added

    def remove_envelope(self, name: str) -> bool:
        """Remove an envelope from the list. Returns True if removed."""
        current = self.data.setdefault("envelopes", [])
        new_list = [
            n for n in current
            if not (isinstance(n, str) and n.casefold() == name.casefold())
        ]
        if len(new_list) != len(current):
            self.data["envelopes"] = new_list
            self.save()
            return True
        return False

    def delete_last(self) -> Transaction | None:
        raw_transactions = self.data.get("transactions", [])
        if not isinstance(raw_transactions, list) or not raw_transactions:
            return None
        raw = raw_transactions.pop()
        self.save()
        return Transaction.from_json(raw) if isinstance(raw, dict) else None

    def set_last_payday(self, payday_date: date | None) -> None:
        """Update the last payday date."""
        self.data["last_payday"] = payday_date.isoformat() if payday_date else None
        self.save()

    def set_next_payday(self, payday_date: date | None) -> None:
        """User-set next payday; drives the per-day/per-week math."""
        self.data["next_payday"] = payday_date.isoformat() if payday_date else None
        self.save()


def pool_balance(transactions: list[Transaction]) -> int:
    balance = 0
    for tx in transactions:
        if tx.kind == "income":
            balance += tx.cents
        elif tx.kind == "fund":
            balance -= tx.cents
        elif tx.kind == "expense" and tx.source == "pool":
            balance -= tx.cents
        elif tx.kind == "adjust" and tx.target == "pool":
            balance += tx.cents  # delta (may be negative)
    return balance


def account_balances(
    transactions: list[Transaction],
    envelope_names: list[str] | None = None,
) -> dict[str, int]:
    """Compute envelope balances.

    Pass ``envelope_names`` to ensure registered envelopes always appear in the
    result (with R0 balance if no transaction has touched them yet).
    """
    balances: dict[str, int] = {}
    if envelope_names:
        for name in envelope_names:
            if name and name.casefold() != "pool":
                balances.setdefault(name, 0)
    for tx in transactions:
        if tx.kind == "fund" and tx.target:
            balances[tx.target] = balances.get(tx.target, 0) + tx.cents
        elif tx.kind == "expense" and tx.source and tx.source != "pool":
            balances[tx.source] = balances.get(tx.source, 0) - tx.cents
        elif tx.kind == "transfer" and tx.source and tx.target:
            balances[tx.source] = balances.get(tx.source, 0) - tx.cents
            balances[tx.target] = balances.get(tx.target, 0) + tx.cents
        elif tx.kind == "adjust" and tx.target and tx.target != "pool":
            balances[tx.target] = balances.get(tx.target, 0) + tx.cents  # delta
    return dict(sorted(balances.items(), key=lambda item: item[0].casefold()))


def pool_movement(transactions: list[Transaction], start: int) -> int:
    return pool_balance([tx for tx in transactions if tx.created_at >= start])


# ---------------------------------------------------------------------------
# UI: wizard-style screen stack. Each step lives on its own Screen so the
# phone-sized viewport never has to show more than one decision at a time.
# ---------------------------------------------------------------------------


APP_CSS = """
Screen {
    background: $surface;
}

Header { dock: top; }

#wizard_body, #home_body {
    height: 1fr;
    padding: 1;
}

.step_title {
    text-style: bold;
    color: $accent;
    height: 1;
    margin: 0 0 1 0;
}

.step_subtitle {
    color: $text-muted;
    height: 1;
    margin: 0 0 1 0;
}

#amount_display {
    width: 1fr;
    border: round $primary;
    padding: 0 1;
    text-align: center;
    text-style: bold;
    color: $accent;
    height: 3;
    margin: 0 0 1 0;
}

#keypad {
    grid-size: 3 4;
    grid-gutter: 1 1;
    height: 15;
    margin: 0 0 1 0;
}
#keypad Button {
    width: 1fr;
    height: 1fr;
    text-style: bold;
}

#mode_tiles {
    height: 11;
    grid-size: 2 2;
    grid-gutter: 1 1;
    margin: 0 0 1 0;
}
.mode_tile {
    width: 1fr;
    height: 1fr;
    text-style: bold;
}

#envelope_scroll, #notes_scroll {
    height: 1fr;
}

.env_tile {
    width: 1fr;
    height: 3;
    margin: 0 0 1 0;
    text-style: bold;
}

.note_tile {
    width: 1fr;
    height: 3;
    margin: 0 0 1 0;
}

#nav {
    height: 3;
    margin: 0;
}
#nav Button {
    width: 1fr;
    height: 3;
    margin: 0 1 0 0;
}
#nav Button:last-of-type {
    margin: 0;
}

#receipt_body {
    height: 1fr;
    align: center middle;
    padding: 2;
}
.receipt_check {
    text-style: bold;
    color: $success;
    text-align: center;
    height: 1;
    margin: 0 0 1 0;
}
.receipt_headline {
    text-style: bold;
    text-align: center;
    color: $accent;
    height: 2;
    margin: 0 0 1 0;
}
.receipt_detail {
    text-align: center;
    color: $text-muted;
    height: 2;
    margin: 0 0 2 0;
}
#receipt_body Button {
    width: 30;
    height: 3;
    text-style: bold;
}

#summary {
    border: tall $primary;
    padding: 0 1;
    height: auto;
    margin: 0 0 1 0;
}
#accounts, #recent_list {
    padding: 0 1;
    height: auto;
}

#pool_wrap {
    height: auto;
    align: center middle;
    margin: 1 0 1 0;
}
#pool_display {
    width: auto;
    height: auto;
    color: $success;
    text-align: center;
}
#pool_display.neg { color: $error; }

#details_panel {
    height: 1fr;
    border: round $primary;
    padding: 1 2;
    margin: 0;
}
#details {
    width: 1fr;
    height: auto;
    text-align: left;
}

#bottom_nav {
    height: 3;
    background: $boost;
    padding: 0;
}
#bottom_nav Button {
    width: 1fr;
    height: 3;
    margin: 0;
    text-style: bold;
}

Input { margin: 0 0 1 0; }

/* Settings date picker */
#datepicker {
    height: auto;
    margin: 1 0;
}
.dp_row {
    height: 3;
    align: center middle;
    margin: 0 0 1 0;
}
.dp_row Button {
    width: 8;
    height: 3;
    margin: 0 1;
    text-style: bold;
}
.dp_val {
    width: 14;
    height: 3;
    content-align: center middle;
    text-align: center;
    text-style: bold;
    color: $accent;
    border: round $primary;
}
#dp_save {
    width: 1fr;
    height: 3;
    margin: 1 0 0 0;
}
.settings_info {
    color: $text-muted;
    margin: 1 0;
    padding: 0 1;
}

.ok  { color: $success; }
.bad { color: $error; }
"""


class AmountScreen(Screen):
    """Step 1 of every flow: enter the amount with a calculator keypad."""

    BINDINGS = [("escape", "back", "Back")]

    def __init__(self, flow: "TransactionFlow") -> None:
        super().__init__()
        self.flow = flow
        self.cents = int(flow.state.get("amount") or 0)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="wizard_body"):
            yield Label(f"{self.flow.mode.title()} — amount", classes="step_title")
            yield Static(_money(self.cents), id="amount_display")
            with Grid(id="keypad"):
                for key in ("7", "8", "9", "4", "5", "6", "1", "2", "3"):
                    yield Button(key, id=f"key_{key}")
                yield Button("C", id="key_clear", variant="warning")
                yield Button("0", id="key_0")
                yield Button("⌫", id="key_back", variant="warning")
        with Horizontal(id="nav"):
            yield Button("‹ Cancel", id="nav_back")
            yield Button("Next ›", id="nav_next", variant="success")

    def action_back(self) -> None:
        self.flow.prev_step()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "nav_back":
            self.flow.prev_step()
        elif bid == "nav_next":
            if self.cents <= 0:
                self.app.bell()
                return
            self.flow.state["amount"] = self.cents
            self.flow.next_step()
        elif bid == "key_clear":
            self.cents = 0
            self._refresh()
        elif bid == "key_back":
            self.cents //= 10
            self._refresh()
        elif bid and bid.startswith("key_") and bid[4:].isdigit():
            new_value = self.cents * 10 + int(bid[4:])
            if new_value <= 999_999_999:
                self.cents = new_value
                self._refresh()

    def _refresh(self) -> None:
        self.query_one("#amount_display", Static).update(_money(self.cents))


class EnvelopePickerScreen(Screen):
    """Tap an existing envelope (or pool, or create new) from a grid."""

    BINDINGS = [("escape", "back", "Back")]

    def __init__(
        self,
        flow: "TransactionFlow",
        *,
        kind: str,
        prompt: str,
        include_pool: bool,
        exclude: set[str] | None = None,
    ) -> None:
        super().__init__()
        self.flow = flow
        self.kind = kind
        self.prompt = prompt
        self.include_pool = include_pool
        self.exclude = {e.casefold() for e in (exclude or set())}
        self._env_names: list[str] = []

    def compose(self) -> ComposeResult:
        balances = account_balances(
            self.flow.db.transactions, self.flow.db.envelope_names
        )
        pool = pool_balance(self.flow.db.transactions)
        self._env_names = [n for n in balances if n.casefold() not in self.exclude]

        yield Header(show_clock=False)
        with Vertical(id="wizard_body"):
            yield Label(self.prompt, classes="step_title")
            yield Static(self._context_line(), classes="step_subtitle")
            with ScrollableContainer(id="envelope_scroll"):
                if self.include_pool:
                    yield Button(f"Pool   {_money(pool)}", id="env_pool", classes="env_tile")
                for idx, name in enumerate(self._env_names):
                    yield Button(
                        f"{name}   {_money(balances[name])}",
                        id=f"env_existing_{idx}",
                        classes="env_tile",
                    )
                yield Button(
                    "+ New envelope",
                    id="env_new",
                    classes="env_tile",
                    variant="primary",
                )
        with Horizontal(id="nav"):
            yield Button("‹ Back", id="nav_back")

    def action_back(self) -> None:
        self.flow.prev_step()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "nav_back":
            self.flow.prev_step()
        elif bid == "env_pool":
            self._pick("pool")
        elif bid == "env_new":
            self.app.push_screen(NewEnvelopeScreen(), self._on_new_named)
        elif bid and bid.startswith("env_existing_"):
            try:
                idx = int(bid[len("env_existing_"):])
            except ValueError:
                return
            if 0 <= idx < len(self._env_names):
                self._pick(self._env_names[idx])

    def _pick(self, name: str) -> None:
        self.flow.state[self.kind] = name
        self.flow.next_step()

    def _on_new_named(self, name: str | None) -> None:
        if name:
            self._pick(name)

    def _context_line(self) -> str:
        st = self.flow.state
        amount = _money(int(st["amount"]))
        if self.kind == "source":
            return f"Amount: {amount}"
        # target picker — show source if already chosen
        if st.get("source"):
            return f"Amount: {amount}   From: {st['source']}"
        return f"Amount: {amount}"


class NewEnvelopeScreen(Screen):
    """One field to name a brand-new envelope."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="wizard_body"):
            yield Label("Name the new envelope", classes="step_title")
            yield Input(placeholder="e.g. Groceries", id="new_name")
        with Horizontal(id="nav"):
            yield Button("‹ Cancel", id="nav_back")
            yield Button("Create ›", id="nav_save", variant="success")

    def on_mount(self) -> None:
        self.query_one("#new_name", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "nav_back":
            self.dismiss(None)
        elif bid == "nav_save":
            self._save()

    def _save(self) -> None:
        name = _clean_account(self.query_one("#new_name", Input).value, allow_pool=False)
        if not name:
            self.app.bell()
            return
        self.dismiss(name)


class NoteScreen(Screen):
    """Final step: pick or type a note, optional payday flag, then Save."""

    BINDINGS = [("escape", "back", "Back")]

    def __init__(self, flow: "TransactionFlow") -> None:
        super().__init__()
        self.flow = flow
        self._notes: list[str] = []

    def compose(self) -> ComposeResult:
        self._notes = self.flow.previous_notes()[:30]
        yield Header(show_clock=False)
        with Vertical(id="wizard_body"):
            yield Label("Add a note (optional)", classes="step_title")
            yield Static(self._context_line(), classes="step_subtitle")
            yield Input(
                placeholder="Type a new note, or tap one below…",
                id="note_input",
                value=str(self.flow.state.get("note") or ""),
            )
            with ScrollableContainer(id="notes_scroll"):
                for idx, note in enumerate(self._notes):
                    yield Button(note, id=f"note_{idx}", classes="note_tile")
        with Horizontal(id="nav"):
            yield Button("‹ Back", id="nav_back")
            yield Button("Save ✓", id="nav_save", variant="success")

    def action_back(self) -> None:
        self.flow.prev_step()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "nav_back":
            self.flow.prev_step()
        elif bid == "nav_save":
            self._save()
        elif bid and bid.startswith("note_"):
            try:
                idx = int(bid.split("_", 1)[1])
            except ValueError:
                return
            if 0 <= idx < len(self._notes):
                self.query_one("#note_input", Input).value = self._notes[idx]

    def _save(self) -> None:
        note_value = self.query_one("#note_input", Input).value.strip()
        self.flow.state["note"] = note_value
        self.flow.commit()

    def _context_line(self) -> str:
        st = self.flow.state
        amount = _money(int(st["amount"]))
        if self.flow.mode == "income":
            return f"Income {amount}"
        if self.flow.mode == "fund":
            return f"Fund {amount} → {st.get('target') or '?'}"
        if self.flow.mode == "expense":
            return f"Expense {amount} from {st.get('source') or 'pool'}"
        return f"Transfer {amount}  {st.get('source') or '?'} → {st.get('target') or '?'}"


class ReceiptScreen(Screen):
    """Confirmation card after a successful save. Done returns home."""

    BINDINGS = [("escape", "done", "Done"), ("enter", "done", "Done")]

    def __init__(self, headline: str, detail: str) -> None:
        super().__init__()
        self.headline = headline
        self.detail = detail

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="receipt_body"):
            yield Static("✓ Saved", classes="receipt_check")
            yield Static(self.headline, classes="receipt_headline")
            yield Static(self.detail, classes="receipt_detail")
            yield Button("Done", id="done", variant="success")

    def on_mount(self) -> None:
        self.query_one("#done", Button).focus()

    def action_done(self) -> None:
        self._return_home()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "done":
            self._return_home()

    def _return_home(self) -> None:
        app = self.app
        while not isinstance(app.screen, HomeScreen) and len(app.screen_stack) > 1:
            app.pop_screen()
        if isinstance(app.screen, HomeScreen):
            app.screen.refresh_view()


class AdjustAmountScreen(Screen):
    """Manually set the absolute balance of pool or an envelope.

    Stores the signed delta as an 'adjust' transaction so the change is
    auditable in Recent and reversible via Undo.
    """

    BINDINGS = [("escape", "back", "Back")]

    def __init__(self, target: str) -> None:
        super().__init__()
        self.target = target  # "pool" or an envelope name
        self._current = 0     # populated in compose
        self.cents = 0        # new desired balance, built up by keypad

    def compose(self) -> ComposeResult:
        # Snapshot current balance for the target.
        txs = self.app.db.transactions  # type: ignore[attr-defined]
        if self.target == "pool":
            self._current = pool_balance(txs)
            display_name = "Pool"
        else:
            self._current = account_balances(
                txs, self.app.db.envelope_names  # type: ignore[attr-defined]
            ).get(self.target, 0)
            display_name = self.target

        yield Header(show_clock=False)
        with Vertical(id="wizard_body"):
            yield Label(f"Set balance — {display_name}", classes="step_title")
            yield Static(
                f"Current: [b]{_money_grouped(self._current)}[/]",
                classes="step_subtitle",
            )
            yield Static(_money(self.cents), id="amount_display")
            with Grid(id="keypad"):
                for key in ("7", "8", "9", "4", "5", "6", "1", "2", "3"):
                    yield Button(key, id=f"key_{key}")
                yield Button("C", id="key_clear", variant="warning")
                yield Button("0", id="key_0")
                yield Button("⌫", id="key_back", variant="warning")
        with Horizontal(id="nav"):
            yield Button("‹ Cancel", id="nav_back")
            if self.target != "pool":
                yield Button("Delete", id="nav_delete", variant="error")
            yield Button("Save ✓", id="nav_save", variant="success")

    def action_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "nav_back":
            self.app.pop_screen()
        elif bid == "nav_save":
            self._save()
        elif bid == "nav_delete":
            self.app.push_screen(DeleteEnvelopeScreen(self.target))
        elif bid == "key_clear":
            self.cents = 0
            self._refresh()
        elif bid == "key_back":
            self.cents //= 10
            self._refresh()
        elif bid and bid.startswith("key_") and bid[4:].isdigit():
            new_value = self.cents * 10 + int(bid[4:])
            if new_value <= 999_999_999:
                self.cents = new_value
                self._refresh()

    def _refresh(self) -> None:
        self.query_one("#amount_display", Static).update(_money(self.cents))

    def _save(self) -> None:
        delta = self.cents - self._current
        if delta == 0:
            self.notify("Balance unchanged", severity="warning")
            return
        sign = "+" if delta > 0 else ""
        note = f"adjust to {_money_grouped(self.cents)}"
        self.app.db.add(  # type: ignore[attr-defined]
            "adjust", delta, note, target=self.target,
        )
        self.notify(f"{self.target}: {_money_grouped(self.cents)}  ({sign}{_money_grouped(delta)})")
        self.app.pop_screen()


class EnvelopesScreen(Screen):
    """Tappable list of pool + envelopes. Tap to adjust the balance."""

    BINDINGS = [("escape", "back", "Back")]

    def __init__(self) -> None:
        super().__init__()
        self._names: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="wizard_body"):
            yield Label("Envelopes", classes="step_title")
            yield Static("Tap any row to set its balance", classes="step_subtitle")
            with ScrollableContainer(id="envelopes_scroll"):
                pass  # populated dynamically (so we can refresh on resume)
        with Horizontal(id="nav"):
            yield Button("‹ Back", id="nav_back")

    async def on_mount(self) -> None:
        await self._populate()

    async def on_screen_resume(self) -> None:
        await self._populate()

    def action_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "nav_back":
            self.app.pop_screen()
        elif bid == "env_pool":
            self.app.push_screen(AdjustAmountScreen("pool"))
        elif bid == "env_new":
            self.app.push_screen(NewEnvelopeScreen(), self._on_new_named)
        elif bid and bid.startswith("env_idx_"):
            try:
                idx = int(bid[len("env_idx_"):])
            except ValueError:
                return
            if 0 <= idx < len(self._names):
                self.app.push_screen(AdjustAmountScreen(self._names[idx]))

    def _on_new_named(self, name: str | None) -> None:
        if not name:
            return
        added = self.app.db.add_envelope(name)  # type: ignore[attr-defined]
        if added:
            self.notify(f"Added envelope: {name}")
        else:
            self.notify(f"{name} already exists", severity="warning")
        # on_screen_resume already fires after the NewEnvelopeScreen pops, so
        # _populate runs automatically — no explicit refresh needed here.

    async def _populate(self) -> None:
        scroll = self.query_one("#envelopes_scroll", ScrollableContainer)
        # Await removal so the old children are gone before we mount new ones
        # with the same IDs — otherwise Textual raises DuplicateIds.
        await scroll.remove_children()

        txs = self.app.db.transactions  # type: ignore[attr-defined]
        pool = pool_balance(txs)
        await scroll.mount(Button(
            f"Pool        {_money_grouped(pool)}",
            id="env_pool",
            classes="env_tile",
            variant="primary",
        ))

        balances = account_balances(txs, self.app.db.envelope_names)  # type: ignore[attr-defined]
        self._names = list(balances.keys())

        for idx, name in enumerate(self._names):
            cents = balances[name]
            variant = "default" if cents >= 0 else "error"
            await scroll.mount(Button(
                f"{name}        {_money_grouped(cents)}",
                id=f"env_idx_{idx}",
                classes="env_tile",
                variant=variant,
            ))

        # Always show the add-envelope tile at the bottom of the list.
        await scroll.mount(Button(
            "+ Add envelope",
            id="env_new",
            classes="env_tile",
            variant="success",
        ))


class SettingsScreen(Screen):
    """Editable settings — next payday picker + read-only env info."""

    BINDINGS = [("escape", "back", "Back")]

    def __init__(self) -> None:
        super().__init__()
        self._payday: date = date.today()

    def compose(self) -> ComposeResult:
        # Seed picker from stored next_payday, falling back to the env-derived value.
        stored = self.app.db.data.get("next_payday")  # type: ignore[attr-defined]
        if stored:
            try:
                self._payday = date.fromisoformat(stored)
            except (ValueError, TypeError):
                self._payday = _next_payday(date.today())
        else:
            self._payday = _next_payday(date.today())

        yield Header(show_clock=False)
        with Vertical(id="wizard_body"):
            yield Label("Next payday", classes="step_title")
            yield Static(
                "Drives the per-day / per-week budget on Home.",
                classes="step_subtitle",
            )
            with Vertical(id="datepicker"):
                with Horizontal(classes="dp_row"):
                    yield Button("−", id="dp_day_minus")
                    yield Static(f"{self._payday.day:02d}", id="dp_day_val", classes="dp_val")
                    yield Button("+", id="dp_day_plus")
                with Horizontal(classes="dp_row"):
                    yield Button("−", id="dp_month_minus")
                    yield Static(self._payday.strftime("%b"), id="dp_month_val", classes="dp_val")
                    yield Button("+", id="dp_month_plus")
                with Horizontal(classes="dp_row"):
                    yield Button("−", id="dp_year_minus")
                    yield Static(str(self._payday.year), id="dp_year_val", classes="dp_val")
                    yield Button("+", id="dp_year_plus")
                yield Button("Save next payday", id="dp_save", variant="success")
            yield Static(
                f"Currency:   {CURRENCY}\n"
                f"Data file:  {DB_PATH}\n\n"
                "Env overrides: BUDGET_CURRENCY, BUDGET_DB, BUDGET_HOME",
                classes="settings_info",
            )
        with Horizontal(id="nav"):
            yield Button("‹ Back", id="nav_back")

    def action_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "nav_back":
            self.app.pop_screen()
        elif bid == "dp_day_plus":
            self._set_date(self._payday + timedelta(days=1))
        elif bid == "dp_day_minus":
            self._set_date(self._payday - timedelta(days=1))
        elif bid == "dp_month_plus":
            self._shift_month(1)
        elif bid == "dp_month_minus":
            self._shift_month(-1)
        elif bid == "dp_year_plus":
            self._shift_year(1)
        elif bid == "dp_year_minus":
            self._shift_year(-1)
        elif bid == "dp_save":
            self.app.db.set_next_payday(self._payday)  # type: ignore[attr-defined]
            self.notify(f"Next payday set: {self._payday:%a %d %b %Y}")

    def _shift_month(self, delta: int) -> None:
        m = self._payday.month + delta
        y = self._payday.year
        while m > 12:
            m -= 12
            y += 1
        while m < 1:
            m += 12
            y -= 1
        last_day = calendar.monthrange(y, m)[1]
        self._set_date(date(y, m, min(self._payday.day, last_day)))

    def _shift_year(self, delta: int) -> None:
        y = self._payday.year + delta
        last_day = calendar.monthrange(y, self._payday.month)[1]
        self._set_date(date(y, self._payday.month, min(self._payday.day, last_day)))

    def _set_date(self, d: date) -> None:
        self._payday = d
        self.query_one("#dp_day_val", Static).update(f"{d.day:02d}")
        self.query_one("#dp_month_val", Static).update(d.strftime("%b"))
        self.query_one("#dp_year_val", Static).update(str(d.year))


class HomeScreen(Screen):
    """Landing screen: summary, four mode tiles, envelopes, bottom nav."""

    BINDINGS = [
        ("i", "start('income')", "Income"),
        ("e", "start('expense')", "Expense"),
        ("f", "start('fund')", "Fund"),
        ("t", "start('transfer')", "Transfer"),
        ("v", "open_envelopes", "Envelopes"),
        ("s", "open_settings", "Settings"),
        ("q", "quit", "Quit"),
    ]

    def on_screen_resume(self) -> None:
        self.refresh_view()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="home_body"):
            with Grid(id="mode_tiles"):
                yield Button("Income",   id="mode_income",   variant="success", classes="mode_tile")
                yield Button("Expense",  id="mode_expense",  variant="error",   classes="mode_tile")
                yield Button("Fund",     id="mode_fund",     variant="primary", classes="mode_tile")
                yield Button("Transfer", id="mode_transfer", variant="warning", classes="mode_tile")
            with Horizontal(id="pool_wrap"):
                yield Digits("", id="pool_display")
            with Vertical(id="details_panel"):
                yield Static(id="details")
        with Horizontal(id="bottom_nav"):
            yield Button("Envelopes", id="nav_envelopes")
            yield Button("Settings",  id="nav_settings")

    def on_mount(self) -> None:
        self.refresh_view()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid and bid.startswith("mode_"):
            self.action_start(bid[5:])
        elif bid == "nav_envelopes":
            self.action_open_envelopes()
        elif bid == "nav_settings":
            self.action_open_settings()

    def action_start(self, mode: str) -> None:
        if mode not in ("income", "fund", "expense", "transfer"):
            return
        budget_app = self.app
        flow = TransactionFlow(budget_app, mode)  # type: ignore[arg-type]
        budget_app.current_flow = flow  # type: ignore[attr-defined]
        flow.start()

    def action_open_envelopes(self) -> None:
        self.app.push_screen(EnvelopesScreen())

    def action_open_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    def refresh_view(self) -> None:
        transactions = self.app.db.transactions  # type: ignore[attr-defined]
        pool = pool_balance(transactions)

        # Big pool display
        pool_widget = self.query_one("#pool_display", Digits)
        sign = "-" if pool < 0 else ""
        whole = abs(pool) // 100
        cents_part = abs(pool) % 100
        pool_widget.update(f"{sign}{CURRENCY} {whole:,}.{cents_part:02d}")
        pool_widget.set_class(pool < 0, "neg")

        # Payday window — user-set next_payday wins; auto-rolls if past.
        today_date = date.today()
        next_payday_str = self.app.db.data.get("next_payday")  # type: ignore[attr-defined]
        next_payday = _next_payday(today_date, next_payday_str)
        days_to_payday = max(1, (next_payday - today_date).days)
        weeks_to_payday = max(1, days_to_payday / 7)
        per_day = pool // days_to_payday
        per_week = int(pool / weeks_to_payday)

        # Rolling-window spend totals
        now_ts = int(time.time())
        ts_7d = now_ts - 7 * 86400
        ts_30d = now_ts - 30 * 86400
        spent_7d = sum(tx.cents for tx in transactions
                       if tx.kind == "expense" and tx.created_at >= ts_7d)
        spent_30d = sum(tx.cents for tx in transactions
                        if tx.kind == "expense" and tx.created_at >= ts_30d)

        # Last income
        last_income = next(
            (tx for tx in reversed(transactions) if tx.kind == "income"),
            None,
        )
        last_income_cents = last_income.cents if last_income else None
        last_income_date = (
            datetime.fromtimestamp(last_income.created_at).date() if last_income else None
        )

        self.query_one("#details", Static).update(
            _build_details(
                per_day=per_day,
                per_week=per_week,
                spent_7d=spent_7d,
                spent_30d=spent_30d,
                last_income_cents=last_income_cents,
                last_income_date=last_income_date,
                next_payday=next_payday,
                days_to_payday=days_to_payday,
            )
        )


class TransactionFlow:
    """Orchestrates the per-mode wizard: builds, pushes, and pops screens."""

    STEPS: dict[str, list[str]] = {
        "income":   ["amount", "note"],
        "fund":     ["amount", "target", "note"],
        "expense":  ["amount", "source", "note"],
        "transfer": ["amount", "source", "target", "note"],
    }

    def __init__(self, app: "BudgetApp", mode: TransactionKind) -> None:
        self.app = app
        self.mode = mode
        self.db = app.db
        self.step_idx = -1
        self.state: dict[str, Any] = {
            "amount": 0,
            "source": None,
            "target": None,
            "note": "",
        }

    def previous_notes(self) -> list[str]:
        seen: dict[str, None] = {}
        for tx in reversed(self.db.transactions):
            if tx.note and tx.note not in seen:
                seen[tx.note] = None
        return list(seen.keys())

    def start(self) -> None:
        self.next_step()

    def next_step(self) -> None:
        self.step_idx += 1
        steps = self.STEPS[self.mode]
        if self.step_idx >= len(steps):
            self.commit()
            return
        screen = self._screen_for_step(steps[self.step_idx])
        if screen is not None:
            self.app.push_screen(screen)

    def prev_step(self) -> None:
        if self.step_idx <= 0:
            # First wizard step backing out: drop the screen, abandon flow.
            self.app.pop_screen()
            self.app.current_flow = None  # type: ignore[attr-defined]
            return
        self.app.pop_screen()
        self.step_idx -= 1

    def _screen_for_step(self, step: str) -> Screen | None:
        if step == "amount":
            return AmountScreen(self)
        if step == "source":
            prompt = "Take expense from…" if self.mode == "expense" else "Transfer from envelope…"
            return EnvelopePickerScreen(
                self,
                kind="source",
                prompt=prompt,
                include_pool=(self.mode == "expense"),
                exclude=None,
            )
        if step == "target":
            exclude: set[str] = set()
            src = self.state.get("source")
            if self.mode == "transfer" and src and src != "pool":
                exclude.add(src)
            prompt = "Fund which envelope?" if self.mode == "fund" else "Transfer to envelope…"
            return EnvelopePickerScreen(
                self,
                kind="target",
                prompt=prompt,
                include_pool=False,
                exclude=exclude,
            )
        if step == "note":
            return NoteScreen(self)
        return None

    def commit(self) -> None:
        amount = int(self.state.get("amount") or 0)
        if amount <= 0:
            self.app.bell()
            return
        note = (self.state.get("note") or "").strip()
        source = self.state.get("source")
        target = self.state.get("target")

        if self.mode == "income":
            self.db.add("income", amount, note or "income")
            headline = f"+{_money(amount)} income"
            detail = note or "income"
        elif self.mode == "fund":
            self.db.add("fund", amount, note or f"fund {target}", source="pool", target=target)
            headline = f"{_money(amount)}  pool → {target}"
            detail = note or f"funded {target}"
        elif self.mode == "expense":
            src = source or "pool"
            self.db.add("expense", amount, note or f"expense from {src}", source=src)
            headline = f"−{_money(amount)} from {src}"
            detail = note or f"expense from {src}"
        else:  # transfer
            self.db.add(
                "transfer", amount,
                note or f"{source} to {target}",
                source=source, target=target,
            )
            headline = f"{_money(amount)}  {source} → {target}"
            detail = note or f"transfer {source} → {target}"

        self.app.current_flow = None  # type: ignore[attr-defined]
        self.app.push_screen(ReceiptScreen(headline, detail))


class BudgetApp(App[None]):
    CSS = APP_CSS

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.db = BudgetDatabase(DB_PATH)
        self.current_flow: TransactionFlow | None = None

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())


if __name__ == "__main__":
    BudgetApp().run()
