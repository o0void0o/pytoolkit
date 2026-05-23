#!/usr/bin/env python3
"""Continuous Bluetooth device scanner TUI for Termux.

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


APP_DIR = Path(os.environ.get("BTTAG_HOME", Path.home() / ".local" / "share" / "bttag"))
DB_PATH = Path(os.environ.get("BTTAG_DB", APP_DIR / "bluetooth_observations.json"))
SCAN_INTERVAL_SECONDS = float(os.environ.get("BTTAG_INTERVAL", "2"))


@dataclass(frozen=True)
class BluetoothDevice:
    device_id: str
    address: str | None
    name: str
    alias: str | None
    device_class: str | None
    device_type: str | None
    bond_state: str | None
    rssi: int | None
    raw: dict[str, Any]

    @classmethod
    def from_termux(cls, payload: dict[str, Any]) -> "BluetoothDevice | None":
        address = _first_text(
            payload,
            "address",
            "mac_address",
            "macAddress",
            "device_address",
            "deviceAddress",
            "id",
        )
        name = _first_text(payload, "name", "device_name", "deviceName", "label") or "<unknown>"
        device_id = (address or name).strip().lower()
        if not device_id:
            return None
        return cls(
            device_id=device_id,
            address=address.lower() if address else None,
            name=name,
            alias=_first_text(payload, "alias"),
            device_class=_first_text(payload, "class", "device_class", "deviceClass", "major_class", "majorClass"),
            device_type=_first_text(payload, "type", "device_type", "deviceType"),
            bond_state=_first_text(payload, "bond_state", "bondState", "bonded", "paired"),
            rssi=_first_int(payload, "rssi", "RSSI", "signal", "signal_level", "signalLevel"),
            raw=_json_safe(payload),
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


def _first_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _text(payload.get(key))
        if value is not None:
            return value
    return None


def _first_int(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = _int(payload.get(key))
        if value is not None:
            return value
    return None


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_safe(item) for item in value]
        return str(value)


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


def scan_bluetooth() -> list[BluetoothDevice]:
    if not shutil.which("termux-bluetooth-scaninfo"):
        raise RuntimeError(
            "termux-bluetooth-scaninfo not found. Install Termux:API and run pkg install termux-api."
        )
    payload = _run_json_command(["termux-bluetooth-scaninfo"], timeout=30)
    if isinstance(payload, dict):
        for key in ("devices", "scan_results", "results"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise RuntimeError("termux-bluetooth-scaninfo returned unexpected data.")
    devices = [BluetoothDevice.from_termux(item) for item in payload if isinstance(item, dict)]
    return [device for device in devices if device is not None]


class JsonBluetoothDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "created_at": int(time.time()), "devices": {}}
        with self.path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError(f"{self.path} is not a JSON object.")
        loaded.setdefault("version", 1)
        loaded.setdefault("created_at", int(time.time()))
        loaded.setdefault("devices", {})
        return loaded

    def record_scan(self, devices: list[BluetoothDevice]) -> int:
        now = int(time.time())
        stored_devices: dict[str, Any] = self.data.setdefault("devices", {})
        for device in devices:
            entry = stored_devices.setdefault(
                device.device_id,
                {
                    "device_id": device.device_id,
                    "address": device.address,
                    "name": device.name,
                    "first_seen": now,
                    "last_seen": now,
                    "best_rssi": device.rssi,
                    "alias": device.alias,
                    "class": device.device_class,
                    "type": device.device_type,
                    "bond_state": device.bond_state,
                    "latest_raw": device.raw,
                    "sightings": [],
                },
            )
            entry["address"] = device.address
            entry["name"] = device.name
            entry["last_seen"] = now
            entry["alias"] = device.alias
            entry["class"] = device.device_class
            entry["type"] = device.device_type
            entry["bond_state"] = device.bond_state
            entry["latest_raw"] = device.raw
            if device.rssi is not None:
                best = entry.get("best_rssi")
                entry["best_rssi"] = device.rssi if best is None else max(int(best), device.rssi)
            entry.setdefault("sightings", []).append(
                {
                    "seen_at": now,
                    "rssi": device.rssi,
                    "raw": device.raw,
                }
            )
        self._save()
        return len(stored_devices)

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


class DeviceRow(ListItem):
    def __init__(self, device: BluetoothDevice) -> None:
        super().__init__()
        self.device = device

    def compose(self) -> ComposeResult:
        rssi = "?" if self.device.rssi is None else f"{self.device.rssi} dBm"
        address = self.device.address or self.device.device_id
        detail_parts = [address, rssi]
        if self.device.device_type:
            detail_parts.append(self.device.device_type)
        if self.device.bond_state:
            detail_parts.append(self.device.bond_state)
        yield Label(f"[bold]{self.device.name}[/]\n[dim]{'  '.join(detail_parts)}[/]")


class BluetoothScannerApp(App[None]):
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
        background: #141d24;
        border: solid #38bdf8;
    }

    #status {
        color: #a6e3ff;
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

    #devices {
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
        self.db = JsonBluetoothDatabase(DB_PATH)
        self.scan_count = 0
        self.error_count = 0
        self.scan_in_progress = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="body"):
            with Vertical(id="hero"):
                yield Static("[bold]Bluetooth Scanner[/]  [dim]continuous device logger for Termux[/]")
                yield Static("Starting scanner...", id="status")
            with Horizontal(id="stats"):
                yield StatBox(id="seen")
                yield StatBox(id="interval")
                yield StatBox(id="db")
            with Horizontal(id="controls"):
                yield Button("Scan now", id="scan", variant="primary")
                yield Button("Pause", id="pause", variant="warning")
            yield ListView(id="devices")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Bluetooth Scanner"
        self.sub_title = str(DB_PATH)
        self._set_stats(0, len(self.db.data.get("devices", {})))
        self.set_interval(SCAN_INTERVAL_SECONDS, self._scheduled_scan)
        self.call_later(self.action_scan_now)

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _set_stats(self, visible: int, stored: int) -> None:
        self.query_one("#seen", StatBox).set_value("visible", str(visible))
        self.query_one("#interval", StatBox).set_value("interval", f"{SCAN_INTERVAL_SECONDS:g}s")
        self.query_one("#db", StatBox).set_value("stored", str(stored))

    def _scheduled_scan(self) -> None:
        if self.scanning and not self.scan_in_progress:
            self.run_worker(self._scan_and_store(), exclusive=True, thread=False)

    async def action_scan_now(self) -> None:
        if self.scan_in_progress:
            self._set_status("Scan already running.")
            return
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
        self.scan_in_progress = True
        self._set_status("Scanning Bluetooth devices...")
        try:
            devices = await asyncio.to_thread(scan_bluetooth)
            stored_count = self.db.record_scan(devices)
            self.scan_count += 1
            await self._replace_devices(devices)
            self._set_stats(len(devices), stored_count)
            self._set_status(f"Scan {self.scan_count}: saved {len(devices)} devices to {DB_PATH}")
        except Exception as exc:
            self.error_count += 1
            self._set_status(f"[red]Scan failed:[/] {exc}")
            self._set_stats(0, len(self.db.data.get("devices", {})))
        finally:
            self.scan_in_progress = False

    async def _replace_devices(self, devices: list[BluetoothDevice]) -> None:
        rows = sorted(devices, key=lambda device: device.rssi if device.rssi is not None else -999, reverse=True)
        list_view = self.query_one("#devices", ListView)
        await list_view.clear()
        await list_view.extend(DeviceRow(device) for device in rows)


if __name__ == "__main__":
    BluetoothScannerApp().run()
