from __future__ import annotations

import json
import math
from dataclasses import dataclass

DEFAULT_MIN_SPEED = 0.5
DEFAULT_MAX_SPEED = 6.0


@dataclass(frozen=True)
class Command:
    action: str  # "start" | "stop" | "speed"
    speed_kmh: float | None = None


def clip_speed(value: float, lo: float, hi: float) -> float:
    return round(min(max(value, lo), hi), 1)


def parse_command(
    payload: bytes | str,
    min_speed: float = DEFAULT_MIN_SPEED,
    max_speed: float = DEFAULT_MAX_SPEED,
) -> Command | None:
    """Парсит JSON-команду из топика .../command. None = невалидная."""
    try:
        obj = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    cmd = obj.get("cmd")
    if cmd == "start":
        return Command("start")
    if cmd == "stop":
        return Command("stop")
    if cmd == "speed":
        value = obj.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            value = float(value)
        except OverflowError:
            return None
        if not math.isfinite(value):
            return None
        return Command("speed", clip_speed(value, min_speed, max_speed))
    return None


def parse_speed_set(
    payload: bytes | str,
    min_speed: float = DEFAULT_MIN_SPEED,
    max_speed: float = DEFAULT_MAX_SPEED,
) -> Command | None:
    """Парсит числовой payload топика .../speed/set (number-энтити HA)."""
    try:
        value = float(payload)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value):
        return None
    return Command("speed", clip_speed(value, min_speed, max_speed))
