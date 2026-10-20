"""Jinja2 rendering for the review pages: escaped HTML, integer-only money and timecode formatting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def usd(micro: int | None) -> str:
    """Integer micro-USD as ``US$x.xxxx`` (no floats). ``None`` is shown as unknown."""
    if micro is None:
        return "unknown"
    sign = "-" if micro < 0 else ""
    value = abs(micro)
    return f"{sign}US${value // 1_000_000}.{value % 1_000_000 // 100:04d}"


def timecode(ms: int | None) -> str:
    """Integer milliseconds as ``hh:mm:ss.mmm``."""
    if ms is None:
        return "unknown"
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def short(value: str | None, size: int = 12) -> str:
    return "unknown" if not value else value[:size]


def label(value: Any) -> str:
    """Enum values and identifiers as readable labels."""
    text = getattr(value, "value", value)
    return str(text).replace("_", " ").lower() if text is not None else "unknown"


_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_ENV.filters.update(usd=usd, timecode=timecode, short=short, label=label)


def render(name: str, **context: Any) -> str:
    return _ENV.get_template(name).render(**context)


__all__ = ["TEMPLATE_DIR", "label", "render", "short", "timecode", "usd"]
