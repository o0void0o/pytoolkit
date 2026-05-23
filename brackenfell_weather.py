#!/usr/bin/env python3
"""Brackenfell weather TUI for Termux.

This app uses Open-Meteo's free geocoding and forecast APIs. No API key is
required. It resolves Brackenfell, Cape Town, then shows the current weather
and an hourly forecast in a polished Textual console UI.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Label, ListItem, ListView, Static


LOCATION_QUERY = os.environ.get(
    "WEATHER_QUERY",
    "Brackenfell, Cape Town, South Africa",
)
FORECAST_HOURS = max(6, int(os.environ.get("WEATHER_HOURS", "12")))
AUTO_REFRESH_SECONDS = max(60.0, float(os.environ.get("WEATHER_REFRESH", "900")))
HTTP_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class GeoLocation:
    name: str
    admin1: str | None
    country: str | None
    country_code: str | None
    latitude: float
    longitude: float
    timezone: str | None

    @property
    def display_name(self) -> str:
        parts: list[str] = [self.name]
        if self.admin1 and self.admin1.lower() not in self.name.lower():
            parts.append(self.admin1)
        if self.country and self.country.lower() not in " ".join(parts).lower():
            parts.append(self.country)
        return ", ".join(parts)


@dataclass(frozen=True)
class HourlyForecast:
    time: str
    temperature: float | None
    feels_like: float | None
    precipitation_probability: int | None
    wind_speed: float | None
    wind_direction: int | None
    weather_code: int | None


@dataclass(frozen=True)
class WeatherSnapshot:
    location: GeoLocation
    fetched_at: int
    current_time: str
    current_temperature: float | None
    current_feels_like: float | None
    current_humidity: int | None
    current_wind_speed: float | None
    current_wind_direction: int | None
    current_precipitation: float | None
    current_weather_code: int | None
    today_high: float | None
    today_low: float | None
    sunrise: str | None
    sunset: str | None
    hourly: list[HourlyForecast]

    @property
    def summary(self) -> str:
        return weather_description(self.current_weather_code)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _first_series_text(payload: dict[str, Any], key: str) -> str | None:
    series = payload.get(key)
    if isinstance(series, list) and series:
        return _text(series[0])
    return None


def _first_series_number(payload: dict[str, Any], key: str) -> float | None:
    series = payload.get(key)
    if isinstance(series, list) and series:
        return _number(series[0])
    return None


def _http_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "User-Agent": "brackenfell-weather/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read().decode(response.headers.get_content_charset() or "utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        if body:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and payload.get("reason"):
                raise RuntimeError(str(payload["reason"])) from exc
        raise RuntimeError(f"HTTP {exc.code} from weather service") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Weather service returned malformed JSON") from exc


def _build_url(base: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    return f"{base}?{urlencode(clean_params, doseq=True)}"


def _geocoding_search_name(query: str) -> str:
    # Open-Meteo's geocoder expects a settlement name, not a full address string.
    for part in query.split(","):
        text = part.strip()
        if text:
            return text
    return query.strip()


def _pick_best_location(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        raise RuntimeError(f"No weather location found for {LOCATION_QUERY!r}")

    normalized_query = LOCATION_QUERY.casefold()
    best_score = -1
    best_result = results[0]
    for result in results:
        name = _text(result.get("name")) or ""
        admin1 = _text(result.get("admin1")) or ""
        country = _text(result.get("country")) or ""
        country_code = _text(result.get("country_code")) or ""
        haystack = " ".join([name, admin1, country, country_code]).casefold()

        score = 0
        if normalized_query in haystack:
            score += 50
        if "brackenfell" in haystack:
            score += 40
        if "south africa" in haystack or country_code == "ZA":
            score += 10
        if "western cape" in haystack:
            score += 5

        if score > best_score:
            best_score = score
            best_result = result

    return best_result


def resolve_location() -> GeoLocation:
    url = _build_url(
        "https://geocoding-api.open-meteo.com/v1/search",
        {
            "name": _geocoding_search_name(LOCATION_QUERY),
            "count": 5,
            "language": "en",
            "format": "json",
            "countryCode": "ZA",
        },
    )
    payload = _http_json(url)
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected geocoding response")
    results = payload.get("results")
    if not isinstance(results, list):
        raise RuntimeError(f"No weather location found for {LOCATION_QUERY!r}")
    best = _pick_best_location([item for item in results if isinstance(item, dict)])
    return GeoLocation(
        name=_text(best.get("name")) or LOCATION_QUERY,
        admin1=_text(best.get("admin1")),
        country=_text(best.get("country")),
        country_code=_text(best.get("country_code")),
        latitude=float(best["latitude"]),
        longitude=float(best["longitude"]),
        timezone=_text(best.get("timezone")) or "Africa/Johannesburg",
    )


def fetch_weather_snapshot() -> WeatherSnapshot:
    location = resolve_location()
    url = _build_url(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "timezone": location.timezone or "Africa/Johannesburg",
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
            "forecast_days": 2,
            "current": ",".join(
                [
                    "temperature_2m",
                    "apparent_temperature",
                    "relative_humidity_2m",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "precipitation",
                    "weather_code",
                ]
            ),
            "hourly": ",".join(
                [
                    "temperature_2m",
                    "apparent_temperature",
                    "relative_humidity_2m",
                    "precipitation_probability",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "weather_code",
                ]
            ),
            "daily": ",".join(
                [
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "sunrise",
                    "sunset",
                ]
            ),
        },
    )
    payload = _http_json(url)
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected weather response")

    current = payload.get("current")
    hourly = payload.get("hourly")
    daily = payload.get("daily")
    if not isinstance(current, dict) or not isinstance(hourly, dict) or not isinstance(daily, dict):
        raise RuntimeError("Weather response is missing current, hourly, or daily data")

    hourly_times = hourly.get("time")
    hourly_temperatures = hourly.get("temperature_2m")
    hourly_feels = hourly.get("apparent_temperature")
    hourly_rain = hourly.get("precipitation_probability")
    hourly_wind = hourly.get("wind_speed_10m")
    hourly_wind_dir = hourly.get("wind_direction_10m")
    hourly_codes = hourly.get("weather_code")
    if not all(
        isinstance(series, list)
        for series in (
            hourly_times,
            hourly_temperatures,
            hourly_feels,
            hourly_rain,
            hourly_wind,
            hourly_wind_dir,
            hourly_codes,
        )
    ):
        raise RuntimeError("Hourly forecast is incomplete")

    start_index = 0
    current_time = _text(current.get("time")) or _text(hourly_times[0]) or ""
    current_dt = _parse_iso(current_time)
    if current_dt is not None:
        for index, time_value in enumerate(hourly_times):
            hour_dt = _parse_iso(_text(time_value))
            if hour_dt is not None and hour_dt >= current_dt:
                start_index = index
                break

    forecast_rows: list[HourlyForecast] = []
    for index in range(start_index, min(len(hourly_times), start_index + FORECAST_HOURS)):
        forecast_rows.append(
            HourlyForecast(
                time=_text(hourly_times[index]) or "",
                temperature=_number(hourly_temperatures[index]),
                feels_like=_number(hourly_feels[index]),
                precipitation_probability=_int(hourly_rain[index]),
                wind_speed=_number(hourly_wind[index]),
                wind_direction=_int(hourly_wind_dir[index]),
                weather_code=_int(hourly_codes[index]),
            )
        )

    return WeatherSnapshot(
        location=location,
        fetched_at=int(datetime.now().timestamp()),
        current_time=current_time,
        current_temperature=_number(current.get("temperature_2m")),
        current_feels_like=_number(current.get("apparent_temperature")),
        current_humidity=_int(current.get("relative_humidity_2m")),
        current_wind_speed=_number(current.get("wind_speed_10m")),
        current_wind_direction=_int(current.get("wind_direction_10m")),
        current_precipitation=_number(current.get("precipitation")),
        current_weather_code=_int(current.get("weather_code")),
        today_high=_first_series_number(daily, "temperature_2m_max"),
        today_low=_first_series_number(daily, "temperature_2m_min"),
        sunrise=_first_series_text(daily, "sunrise"),
        sunset=_first_series_text(daily, "sunset"),
        hourly=forecast_rows,
    )


def weather_description(code: int | None) -> str:
    descriptions = {
        0: "Clear sky",
        1: "Mostly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Rime fog",
        51: "Light drizzle",
        53: "Drizzle",
        55: "Dense drizzle",
        56: "Freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Light rain",
        63: "Rain",
        65: "Heavy rain",
        66: "Freezing rain",
        67: "Heavy freezing rain",
        71: "Light snow",
        73: "Snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Rain showers",
        81: "Heavy showers",
        82: "Violent showers",
        85: "Snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with hail",
        99: "Severe thunderstorm",
    }
    if code is None:
        return "Unknown"
    return descriptions.get(code, f"Weather code {code}")


def _format_time(value: str | None) -> str:
    if not value:
        return "n/a"
    try:
        return datetime.fromisoformat(value).strftime("%a %H:%M")
    except ValueError:
        return value


def _format_clock(value: str | None) -> str:
    if not value:
        return "n/a"
    try:
        return datetime.fromisoformat(value).strftime("%H:%M")
    except ValueError:
        return value


def _format_timestamp(value: int) -> str:
    return datetime.fromtimestamp(value).strftime("%a %H:%M")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _format_number(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and abs(value - round(value)) < 0.05:
        text = str(int(round(value)))
    elif isinstance(value, float):
        text = f"{value:.1f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    return f"{text}{suffix}"


def _format_temp(value: float | None) -> str:
    return _format_number(value, " C")


def _format_speed(value: float | None) -> str:
    return _format_number(value, " km/h")


def _format_percent(value: int | None) -> str:
    return _format_number(value, "%")


def _format_wind(value: float | None, direction: int | None) -> str:
    speed = _format_speed(value)
    if direction is None or value is None:
        return speed
    return f"{speed} {bearing_to_cardinal(direction)}"


def bearing_to_cardinal(direction: int) -> str:
    directions = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    index = int((direction + 11.25) / 22.5) % 16
    return directions[index]


class StatBox(Static):
    def set_value(self, title: str, value: str) -> None:
        self.update(f"[dim]{title}[/]\n[bold]{value}[/]")


class ForecastRow(ListItem):
    def __init__(self, hour: HourlyForecast) -> None:
        super().__init__()
        self.hour = hour

    def compose(self) -> ComposeResult:
        time_label = _format_time(self.hour.time)
        temp = _format_temp(self.hour.temperature)
        condition = weather_description(self.hour.weather_code)
        feels = _format_temp(self.hour.feels_like)
        rain = _format_percent(self.hour.precipitation_probability)
        wind = _format_wind(self.hour.wind_speed, self.hour.wind_direction)
        yield Label(
            f"[bold]{time_label}[/]  [#8be8d6]{temp}[/]  [dim]{condition}[/]\n"
            f"[dim]Feels {feels}  Rain {rain}  Wind {wind}[/]"
        )


class BrackenfellWeatherApp(App[None]):
    CSS = """
    Screen {
        background: #07111a;
        color: #edf7f4;
    }

    Header {
        dock: top;
        background: #101b25;
        color: #edf7f4;
    }

    Footer {
        dock: bottom;
        background: #101b25;
    }

    #body {
        height: 1fr;
        padding: 1;
    }

    #hero {
        height: auto;
        padding: 1;
        background: #102133;
        border: solid #2dd4bf;
    }

    #title {
        color: #ffffff;
    }

    #location {
        color: #8fdad0;
        margin-top: 1;
    }

    #status {
        color: #cfe9e5;
        margin-top: 1;
    }

    #summary {
        height: auto;
        margin-top: 1;
        padding: 1;
        background: #0f1720;
        border: solid #213545;
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
        background: #10171f;
        border: tall #223543;
    }

    #controls {
        height: auto;
        margin-top: 1;
    }

    Button {
        width: 1fr;
        margin-right: 1;
    }

    #forecast_label {
        margin-top: 1;
        color: #8fdad0;
        padding-left: 1;
    }

    #forecast {
        height: 1fr;
        margin-top: 1;
        background: #0d141b;
        border: solid #223545;
    }

    ListItem {
        min-height: 3;
        padding: 0 1;
    }

    ListItem.--highlight {
        background: #183245;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh_now", "Refresh"),
        ("a", "toggle_auto_refresh", "Auto"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.snapshot: WeatherSnapshot | None = None
        self.refreshing = False
        self.weather_auto_refresh = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="body"):
            with Vertical(id="hero"):
                yield Static("[bold]Brackenfell Weather[/]", id="title")
                yield Static("[dim]Cape Town, South Africa[/]", id="location")
                yield Static("Starting up...", id="status")
                yield Static("", id="summary")
            with Horizontal(id="stats"):
                yield StatBox(id="temp")
                yield StatBox(id="feels")
                yield StatBox(id="wind")
                yield StatBox(id="rain")
            with Horizontal(id="controls"):
                yield Button("Refresh now", id="refresh", variant="primary")
                yield Button("Pause auto", id="auto", variant="warning")
            yield Static("[bold]Hourly forecast[/] [dim](next 12 hours)[/]", id="forecast_label")
            yield ListView(id="forecast")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Brackenfell Weather"
        self.sub_title = LOCATION_QUERY
        self._set_status("Loading live weather from Open-Meteo...")
        self._set_empty_state()
        self.set_interval(AUTO_REFRESH_SECONDS, self._scheduled_refresh)
        self.call_later(self.action_refresh_now)

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _set_empty_state(self) -> None:
        self.query_one("#summary", Static).update("[dim]Waiting for live weather data.[/]")
        self.query_one("#temp", StatBox).set_value("now", "n/a")
        self.query_one("#feels", StatBox).set_value("feels", "n/a")
        self.query_one("#wind", StatBox).set_value("wind", "n/a")
        self.query_one("#rain", StatBox).set_value("rain", "n/a")

    def _scheduled_refresh(self) -> None:
        if self.weather_auto_refresh and not self.refreshing:
            self.run_worker(self._refresh_weather(), exclusive=True, thread=False)

    async def action_refresh_now(self) -> None:
        if self.refreshing:
            self._set_status("Refresh already running.")
            return
        self.run_worker(self._refresh_weather(), exclusive=True, thread=False)

    def action_toggle_auto_refresh(self) -> None:
        self.weather_auto_refresh = not self.weather_auto_refresh
        self.query_one("#auto", Button).label = (
            "Pause auto" if self.weather_auto_refresh else "Resume auto"
        )
        self._set_status(
            "Auto refresh enabled." if self.weather_auto_refresh else "Auto refresh paused."
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh":
            await self.action_refresh_now()
        elif event.button.id == "auto":
            self.action_toggle_auto_refresh()

    async def _refresh_weather(self) -> None:
        self.refreshing = True
        self._set_status("Fetching Brackenfell weather and hourly forecast...")
        try:
            snapshot = await asyncio.to_thread(fetch_weather_snapshot)
            self.snapshot = snapshot
            await self._render_snapshot(snapshot)
            self._set_status(f"Updated {snapshot.location.display_name} at {_format_timestamp(snapshot.fetched_at)}.")
        except Exception as exc:
            if self.snapshot is None:
                self._set_empty_state()
            self._set_status(f"[red]Refresh failed:[/] {exc}")
        finally:
            self.refreshing = False

    async def _render_snapshot(self, snapshot: WeatherSnapshot) -> None:
        self.query_one("#summary", Static).update(
            "\n".join(
                [
                    f"[bold]{snapshot.summary}[/]",
                    f"High {_format_temp(snapshot.today_high)} / Low {_format_temp(snapshot.today_low)}",
                    f"Humidity {_format_percent(snapshot.current_humidity)}  Precip {_format_number(snapshot.current_precipitation, ' mm')}",
                    f"Sunrise {_format_clock(snapshot.sunrise)}  Sunset {_format_clock(snapshot.sunset)}",
                    f"[dim]{snapshot.location.display_name}[/]",
                ]
            )
        )
        self.query_one("#temp", StatBox).set_value("now", _format_temp(snapshot.current_temperature))
        self.query_one("#feels", StatBox).set_value("feels", _format_temp(snapshot.current_feels_like))
        self.query_one("#wind", StatBox).set_value(
            "wind",
            _format_wind(snapshot.current_wind_speed, snapshot.current_wind_direction),
        )
        rain_now = _format_number(snapshot.current_precipitation, " mm")
        self.query_one("#rain", StatBox).set_value("rain", rain_now)
        await self._replace_forecast(snapshot.hourly)

    async def _replace_forecast(self, hourly: list[HourlyForecast]) -> None:
        list_view = self.query_one("#forecast", ListView)
        await list_view.clear()
        await list_view.extend(ForecastRow(hour) for hour in hourly)


if __name__ == "__main__":
    BrackenfellWeatherApp().run()
