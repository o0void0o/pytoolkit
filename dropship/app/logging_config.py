"""Colored console logging + the startup banner."""

from __future__ import annotations

import logging
import sys
from typing import Final

from app.config import Config

try:  # pragma: no cover
    import colorama

    colorama.just_fix_windows_console()
except Exception:  # pragma: no cover
    pass


RESET: Final = "\x1b[0m"
DIM: Final = "\x1b[2m"
BOLD: Final = "\x1b[1m"

GREEN: Final = "\x1b[38;5;46m"
CYAN: Final = "\x1b[38;5;51m"
MAGENTA: Final = "\x1b[38;5;201m"
YELLOW: Final = "\x1b[38;5;226m"
RED: Final = "\x1b[38;5;196m"
GREY: Final = "\x1b[38;5;245m"


LEVEL_COLORS: dict[int, str] = {
    logging.DEBUG: GREY,
    logging.INFO: GREEN,
    logging.WARNING: YELLOW,
    logging.ERROR: RED,
    logging.CRITICAL: MAGENTA,
}


class TerminalFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = LEVEL_COLORS.get(record.levelno, "")
        ts = self.formatTime(record, datefmt="%H:%M:%S")
        level = f"{color}{record.levelname:<7}{RESET}"
        name = f"{CYAN}{record.name}{RESET}"
        msg = record.getMessage()
        line = f"{DIM}{ts}{RESET} {level} {name} {msg}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging(*, debug: bool = False) -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(TerminalFormatter())
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


BANNER = r"""
{g}  ____                       _     _              {r}
{g} |  _ \ _ __ ___  _ __  ___| |__ (_)_ __         {r}
{g} | | | | '__/ _ \| '_ \/ __| '_ \| | '_ \        {r}
{g} | |_| | | | (_) | |_) \__ \ | | | | |_) |       {r}
{g} |____/|_|  \___/| .__/|___/_| |_|_| .__/        {r}
{g}                 |_|               |_|           {r}
{c} ╔══════════════════════════════════════════════════════╗ {r}
{c} ║{r}  {b}Dropship{r}    ::  encrypted-vibes file drop server     {c}║{r}
{c} ║{r}  bind   ::  {m}http://{host}:{port}{r}{pad}{c}║{r}
{c} ║{r}  upload ::  {m}{upload}{r}{pad2}{c}║{r}
{c} ╚══════════════════════════════════════════════════════╝ {r}
"""


def print_banner(config: Config) -> None:
    bind_text = f"http://{config.host}:{config.port}"
    upload_text = str(config.upload_dir)
    pad = max(0, 54 - len("  bind   ::  ") - len(bind_text))
    pad2 = max(0, 54 - len("  upload ::  ") - len(upload_text))
    sys.stderr.write(
        BANNER.format(
            g=GREEN,
            c=CYAN,
            r=RESET,
            b=BOLD + MAGENTA,
            m=YELLOW,
            host=config.host,
            port=config.port,
            upload=upload_text,
            pad=" " * pad,
            pad2=" " * pad2,
        )
    )
    sys.stderr.flush()
