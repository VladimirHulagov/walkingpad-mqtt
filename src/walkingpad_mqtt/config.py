from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("~/.config/walkingpad/config.toml").expanduser()


class ConfigError(Exception):
    """Некорректный файл конфигурации."""


@dataclass
class BleConfig:
    mac: str = ""
    adapter: str = "hci0"


@dataclass
class PadConfig:
    min_speed_kmh: float = 0.5
    max_speed_kmh: float = 6.0


@dataclass
class CaloriesConfig:
    weight_kg: float = 80.0
    coefficient: float = 1.03


@dataclass
class MqttConfig:
    host: str = "localhost"
    port: int = 1883
    tls: bool = False
    username: str | None = None
    password: str | None = None
    prefix: str = "walkingpad"
    discovery_prefix: str = "homeassistant"


@dataclass
class PollingConfig:
    interval_s: float = 1.0


@dataclass
class AppConfig:
    ble: BleConfig
    pad: PadConfig
    calories: CaloriesConfig
    mqtt: MqttConfig
    polling: PollingConfig


def _section(cls, data: dict, name: str):
    try:
        return cls(**data.get(name, {}))
    except TypeError as e:
        raise ConfigError(f"Invalid [{name}] section: {e}") from e


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    data: dict = {}
    if path.exists():
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
            raise ConfigError(f"Cannot parse config {path}: {e}") from e
        except OSError as e:
            raise ConfigError(f"Cannot read config {path}: {e}") from e

    ble = _section(BleConfig, data, "ble")
    pad = _section(PadConfig, data, "pad")
    calories = _section(CaloriesConfig, data, "calories")
    mqtt = _section(MqttConfig, data, "mqtt")
    if mqtt.username == "":
        mqtt.username = None
    if mqtt.password == "":
        mqtt.password = None
    polling = _section(PollingConfig, data, "polling")

    if v := os.environ.get("WALKINGPAD_BLE_MAC"):
        ble.mac = v
    if v := os.environ.get("WALKINGPAD_BLE_ADAPTER"):
        ble.adapter = v
    if v := os.environ.get("WALKINGPAD_MQTT_HOST"):
        mqtt.host = v
    if v := os.environ.get("WALKINGPAD_MQTT_PORT"):
        try:
            mqtt.port = int(v)
        except ValueError as e:
            raise ConfigError(f"WALKINGPAD_MQTT_PORT must be an integer, got {v!r}") from e
    if v := os.environ.get("WALKINGPAD_MQTT_USERNAME"):
        mqtt.username = v
    if v := os.environ.get("WALKINGPAD_MQTT_PASSWORD"):
        mqtt.password = v

    return AppConfig(ble=ble, pad=pad, calories=calories, mqtt=mqtt, polling=polling)
