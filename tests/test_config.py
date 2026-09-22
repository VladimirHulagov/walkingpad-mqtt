import os
from pathlib import Path

import pytest

from walkingpad_mqtt.config import (
    AppConfig,
    BleConfig,
    CaloriesConfig,
    ConfigError,
    MqttConfig,
    PadConfig,
    PollingConfig,
    load_config,
)


@pytest.fixture(autouse=True)
def _clean_walkingpad_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("WALKINGPAD_"):
            monkeypatch.delenv(key)


def test_defaults_when_file_missing(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert isinstance(cfg, AppConfig)
    assert cfg.ble.mac == ""
    assert cfg.ble.adapter == "hci0"
    assert cfg.mqtt.host == "localhost"
    assert cfg.mqtt.port == 1883
    assert cfg.mqtt.prefix == "walkingpad"
    assert cfg.mqtt.discovery_prefix == "homeassistant"
    assert cfg.pad.min_speed_kmh == 0.5
    assert cfg.pad.max_speed_kmh == 6.0
    assert cfg.calories.weight_kg == 80.0
    assert cfg.calories.coefficient == 1.03
    assert cfg.polling.interval_s == 1.0


def test_toml_sections_parsed(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text(
        """
[ble]
mac = "57:4C:4E:29:07:F1"
adapter = "hci1"

[pad]
min_speed_kmh = 0.5
max_speed_kmh = 6.0

[calories]
weight_kg = 75.5
coefficient = 1.05

[mqtt]
host = "broker.local"
port = 1884
username = "u"
password = "p"
prefix = "pad"
discovery_prefix = "ha"

[polling]
interval_s = 0.75
""",
        encoding="utf-8",
    )
    cfg = load_config(f)
    assert cfg.ble.mac == "57:4C:4E:29:07:F1"
    assert cfg.ble.adapter == "hci1"
    assert cfg.mqtt.host == "broker.local"
    assert cfg.mqtt.port == 1884
    assert cfg.mqtt.prefix == "pad"
    assert cfg.mqtt.discovery_prefix == "ha"
    assert cfg.mqtt.username == "u"
    assert cfg.mqtt.password == "p"
    assert cfg.calories.weight_kg == 75.5
    assert cfg.calories.coefficient == 1.05
    assert cfg.polling.interval_s == 0.75


def test_env_overrides(tmp_path, monkeypatch):
    f = tmp_path / "config.toml"
    f.write_text('[mqtt]\nhost = "from-file"\n', encoding="utf-8")
    monkeypatch.setenv("WALKINGPAD_MQTT_HOST", "from-env")
    monkeypatch.setenv("WALKINGPAD_MQTT_PORT", "2883")
    monkeypatch.setenv("WALKINGPAD_BLE_MAC", "AA:BB:CC:DD:EE:FF")
    monkeypatch.setenv("WALKINGPAD_MQTT_PASSWORD", "secret")
    monkeypatch.setenv("WALKINGPAD_MQTT_USERNAME", "env-user")
    cfg = load_config(f)
    assert cfg.mqtt.host == "from-env"
    assert cfg.mqtt.port == 2883
    assert cfg.ble.mac == "AA:BB:CC:DD:EE:FF"
    assert cfg.mqtt.password == "secret"
    assert cfg.mqtt.username == "env-user"


def test_invalid_section_raises_config_error(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text("[mqtt]\nbogus_key = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mqtt"):
        load_config(f)


def test_broken_toml_raises_config_error(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text("[mqtt\nhost = \"x\"\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="parse"):
        load_config(f)


def test_bad_port_env_raises_config_error(tmp_path, monkeypatch):
    monkeypatch.setenv("WALKINGPAD_MQTT_PORT", "abc")
    with pytest.raises(ConfigError, match="PORT"):
        load_config(tmp_path / "nope.toml")


def test_invalid_utf8_raises_config_error(tmp_path):
    f = tmp_path / "config.toml"
    f.write_bytes(b"[mqtt]\nhost = \"\xff\xfe\"\n")
    with pytest.raises(ConfigError):
        load_config(f)


def test_empty_credentials_become_none(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('[mqtt]\nusername = ""\npassword = ""\n', encoding="utf-8")
    cfg = load_config(f)
    assert cfg.mqtt.username is None
    assert cfg.mqtt.password is None
