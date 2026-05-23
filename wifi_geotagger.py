#!/usr/bin/env python3
"""Continuous Wi-Fi geotagging TUI for Termux.

Requires:
  pkg install termux-api
  pip install textual

The app stores observations locally as JSON and never sends data anywhere.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Button, Footer, Header, Label, ListItem, ListView, Static


APP_DIR = Path(os.environ.get("WIFITAG_HOME", Path.home() / ".local" / "share" / "wifitag"))
DB_PATH = Path(os.environ.get("WIFITAG_DB", APP_DIR / "wifi_observations.json"))
SCAN_INTERVAL_SECONDS = int(os.environ.get("WIFITAG_INTERVAL", "20"))


@dataclass(frozen=True)
class Location:
    latitude: float | None = None
    longitude: float | None = None
    accuracy: float | None = None
    provider: str | None = None

    @classmethod
    def from_termux(cls, payload: dict[str, Any]) -> "Location":
        return cls(
            latitude=_number(payload.get("latitude")),
            longitude=_number(payload.get("longitude")),
            accuracy=_number(payload.get("accuracy")),
            provider=_text(payload.get("provider")),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "accuracy": self.accuracy,
            "provider": self.provider,
        }


@dataclass(frozen=True)
class AccessPoint:
    bssid: str
    ssid: str
    signal_dbm: int | None
    frequency_mhz: int | None
    capabilities: str | None

    @classmethod
    def from_termux(cls, payload: dict[str, Any]) -> "AccessPoint | None":
        bssid = _text(payload.get("bssid") or payload.get("BSSID"))
        if not bssid:
            return None
        return cls(
            bssid=bssid.lower(),
            ssid=_text(payload.get("ssid") or payload.get("SSID")) or "<hidden>",
            signal_dbm=_int(payload.get("level") or payload.get("signal_level") or payload.get("rssi")),
            frequency_mhz=_int(payload.get("frequency_mhz") or payload.get("frequency") or payload.get("freq")),
            capabilities=_text(payload.get("capabilities")),
        )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _run_json_command(command: list[str], timeout: int) -> Any:
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"{command[0]} failed{suffix}") from exc
    stdout = completed.stdout.strip()
    if not stdout:
        return None
    return json.loads(stdout)


def scan_wifi() -> list[AccessPoint]:
    if not shutil.which("termux-wifi-scaninfo"):
        raise RuntimeError("termux-wifi-scaninfo not found. Install Termux:API and run pkg install termux-api.")
    payload = _run_json_command(["termux-wifi-scaninfo"], timeout=30)
    if not isinstance(payload, list):
        raise RuntimeError("termux-wifi-scaninfo returned unexpected data.")
    aps = [AccessPoint.from_termux(item) for item in payload if isinstance(item, dict)]
    return [ap for ap in aps if ap is not None]


def get_location() -> Location:
    if not shutil.which("termux-location"):
        raise RuntimeError("termux-location not found. Install Termux:API and run pkg install termux-api.")
    payload = _run_json_command(["termux-location", "-p", "network", "-r", "once"], timeout=35)
    if not isinstance(payload, dict):
        raise RuntimeError("termux-location returned unexpected data.")
    return Location.from_termux(payload)


class JsonWifiDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "created_at": int(time.time()), "networks": {}}
        with self.path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError(f"{self.path} is not a JSON object.")
        loaded.setdefault("version", 1)
        loaded.setdefault("created_at", int(time.time()))
        loaded.setdefault("networks", {})
        return loaded

    def record_scan(self, access_points: list[AccessPoint], location: Location) -> int:
        now = int(time.time())
        networks: dict[str, Any] = self.data.setdefault("networks", {})
        for ap in access_points:
            entry = networks.setdefault(
                ap.bssid,
                {
                    "bssid": ap.bssid,
                    "ssid": ap.ssid,
                    "first_seen": now,
                    "last_seen": now,
                    "best_signal_dbm": ap.signal_dbm,
                    "frequency_mhz": ap.frequency_mhz,
                    "capabilities": ap.capabilities,
                    "sightings": [],
                },
            )
            entry["ssid"] = ap.ssid
            entry["last_seen"] = now
            entry["frequency_mhz"] = ap.frequency_mhz
            entry["capabilities"] = ap.capabilities
            if ap.signal_dbm is not None:
                best = entry.get("best_signal_dbm")
                entry["best_signal_dbm"] = ap.signal_dbm if best is None else max(int(best), ap.signal_dbm)
            entry.setdefault("sightings", []).append(
                {
                    "seen_at": now,
                    "signal_dbm": ap.signal_dbm,
                    "frequency_mhz": ap.frequency_mhz,
                    "location": location.to_json(),
                }
            )
        self._save()
        return len(networks)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temp_path.replace(self.path)


class StatBox(Static):
    def set_value(self, title: str, value: str) -> None:
        self.update(f"[dim]{title}[/]\n[bold]{value}[/]")


class NetworkRow(ListItem):
    def __init__(self, ap: AccessPoint) -> None:
        super().__init__()
        self.ap = ap

    def compose(self) -> ComposeResult:
        signal = "?" if self.ap.signal_dbm is None else f"{self.ap.signal_dbm} dBm"
        band = "?" if self.ap.frequency_mhz is None else f"{self.ap.frequency_mhz} MHz"
        yield Label(f"[bold]{self.ap.ssid}[/]\n[dim]{self.ap.bssid}  {signal}  {band}[/]")


class WifiTaggerApp(App[None]):
    CSS = """
    Screen {
        background: #101418;
        color: #edf4f2;
    }

    Header {
        dock: top;
        background: #182127;
        color: #edf4f2;
    }

    Footer {
        dock: bottom;
        background: #182127;
    }

    #body {
        height: 1fr;
        padding: 1;
    }

    #hero {
        height: auto;
        padding: 1;
        background: #14211f;
        border: solid #2dd4bf;
    }

    #status {
        color: #9ee7dc;
    }

    #stats {
        height: auto;
        margin-top: 1;
    }

    StatBox {
        width: 1fr;
        min-height: 4;
        padding: 1;
        margin-right: 1;
        background: #1c262d;
        border: tall #33434d;
    }

    #controls {
        height: auto;
        margin-top: 1;
    }

    Button {
        width: 1fr;
        margin-right: 1;
    }

    #networks {
        height: 1fr;
        margin-top: 1;
        background: #12191e;
        border: solid #31424a;
    }

    ListItem {
        min-height: 3;
        padding: 0 1;
    }

    ListItem.--highlight {
        background: #21363b;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("s", "scan_now", "Scan"),
        ("p", "toggle_pause", "Pause"),
    ]

    scanning = reactive(True)

    def __init__(self) -> None:
        super().__init__()
        self.db = JsonWifiDatabase(DB_PATH)
        self.last_location = Location()
        self.last_scan_started = 0
        self.scan_count = 0
        self.error_count = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="body"):
            with Vertical(id="hero"):
                yield Static("[bold]WiFi Tagger[/]  [dim]continuous wardrive logger for Termux[/]")
                yield Static("Starting scanner...", id="status")
            with Horizontal(id="stats"):
                yield StatBox(id="seen")
                yield StatBox(id="fix")
                yield StatBox(id="db")
            with Horizontal(id="controls"):
                yield Button("Scan now", id="scan", variant="primary")
                yield Button("Pause", id="pause", variant="warning")
            yield ListView(id="networks")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "WiFi Tagger"
        self.sub_title = str(DB_PATH)
        self._set_stats(0, len(self.db.data.get("networks", {})))
        self.set_interval(SCAN_INTERVAL_SECONDS, self._scheduled_scan)
        self.call_later(self.action_scan_now)

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _set_stats(self, visible: int, stored: int) -> None:
        self.query_one("#seen", StatBox).set_value("visible", str(visible))
        if self.last_location.latitude is None or self.last_location.longitude is None:
            fix = "no fix"
        else:
            accuracy = "?" if self.last_location.accuracy is None else f"{self.last_location.accuracy:.0f}m"
            fix = f"{self.last_location.latitude:.5f}, {self.last_location.longitude:.5f}\n[dim]{accuracy}[/]"
        self.query_one("#fix", StatBox).set_value("location", fix)
        self.query_one("#db", StatBox).set_value("stored", str(stored))

    def _scheduled_scan(self) -> None:
        if self.scanning:
            self.run_worker(self._scan_and_store(), exclusive=True, thread=False)

    async def action_scan_now(self) -> None:
        self.run_worker(self._scan_and_store(), exclusive=True, thread=False)

    def action_toggle_pause(self) -> None:
        self.scanning = not self.scanning
        self.query_one("#pause", Button).label = "Pause" if self.scanning else "Resume"
        self._set_status("Scanner running." if self.scanning else "Scanner paused.")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "scan":
            await self.action_scan_now()
        elif event.button.id == "pause":
            self.action_toggle_pause()

    async def _scan_and_store(self) -> None:
        self.last_scan_started = int(time.time())
        self._set_status("Scanning Wi-Fi and asking Android for a network location fix...")
        try:
            wifi_result, location_result = await asyncio.gather(
                asyncio.to_thread(scan_wifi),
                asyncio.to_thread(get_location),
                return_exceptions=True,
            )
            if isinstance(wifi_result, Exception):
                raise wifi_result
            access_points = wifi_result
            location_note = ""
            if isinstance(location_result, Exception):
                location = Location()
                location_note = f" [yellow]Location missing:[/] {location_result}"
            else:
                location = location_result
            self.last_location = location
            stored_count = self.db.record_scan(access_points, location)
            self.scan_count += 1
            await self._replace_networks(access_points)
            self._set_stats(len(access_points), stored_count)
            self._set_status(
                f"Scan {self.scan_count}: saved {len(access_points)} access points to {DB_PATH}{location_note}"
            )
        except Exception as exc:
            self.error_count += 1
            self._set_status(f"[red]Scan failed:[/] {exc}")
            self._set_stats(0, len(self.db.data.get("networks", {})))

    async def _replace_networks(self, access_points: list[AccessPoint]) -> None:
        rows = sorted(access_points, key=lambda ap: ap.signal_dbm if ap.signal_dbm is not None else -999, reverse=True)
        list_view = self.query_one("#networks", ListView)
        await list_view.clear()
        await list_view.extend(NetworkRow(ap) for ap in rows)


if __name__ == "__main__":
    WifiTaggerApp().run()
