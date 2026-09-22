# WalkingPad A1 Pro → MQTT мост: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the specified execution mode skill (from brainstorming). Steps use checkbox (`- [ ]`) syntax for tracking.

**Execution Mode:** subagent-driven

**Goal:** Постоянный BLE-мост WalkingPad A1 Pro (WiLink) → MQTT с мониторингом и управлением из Home Assistant.

**Architecture:** Python-сервис (systemd user-unit) на хосте-ноутбуке с BLE: PadClient держит BLE-подключение к дорожке (библиотека ph4-walkingpad) и опрашивает статус ~1 Гц; SessionDetector выделяет сессии; MqttLayer публикует состояние и HA discovery-конфиги, принимает команды start/stop/speed.

**Tech Stack:** Python 3.12, asyncio, bleak 3.x, ph4-walkingpad 1.x (WiLink), aiomqtt 2.x, pytest + pytest-asyncio.

**Спека:** `docs/superpowers/specs/2026-09-21-walkingpad-mqtt-design.md`

**Особенности окружения (важно для исполнителей):**

- PyPI (pypi.org) на этом хосте недоступен (DNS-фильтр). Использовать зеркало Tsinghua: `https://pypi.tuna.tsinghua.edu.cn/simple`. В Task 1 конфигурируется `~/.config/pip/pip.conf`.
- Рабочая директория проекта: путь к клону репозитория (это git-репозиторий, main-ветка).
- venv проекта: `.venv` в корне. Все python/pip команды — через `.venv/bin/...`.
- BlueZ на хосте: hci0, Bluetooth работает (`bluetoothctl` доступен).

**Соглашения:**

- Коммиты после каждой задачи (или под-шага "Commit"), сообщения вида `feat: ...`, `test: ...`, `chore: ...`.
- Каждый тест перед реализацией запускается и обязан упасть (TDD).
- Скорость дорожки: команды в км/ч (float); в WiLink-фрейм превращает `change_speed(int(kmh*10))` — делает PadClient.
- Тесты не трогают реальный BLE и реальный MQTT-брокер.

---

### Task 1: Скелет проекта

**Files:**
- Create: `pyproject.toml`
- Create: `src/walkingpad_mqtt/__init__.py`
- Create: `tests/__init__.py` (пустой, чтобы pytest не путал импорты)
- Create: `~/.config/pip/pip.conf` (вне репозитория)

- [ ] **Step 1: Настроить pip-зеркало**

Создать `~/.config/pip/pip.conf` (mkdir -p при необходимости):

```ini
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
```

Проверка: `.venv` ниже должен ставиться без сетевых ошибок. (Запасное зеркало: `https://mirrors.aliyun.com/pypi/simple/`.)

- [ ] **Step 2: pyproject.toml**

```toml
[project]
name = "walkingpad-mqtt"
version = "0.1.0"
description = "WalkingPad A1 Pro (WPA1F-Pro) BLE to MQTT bridge for Home Assistant"
requires-python = ">=3.11"
dependencies = [
    "ph4-walkingpad>=1.0,<2",
    "bleak>=2.4,<4",
    "aiomqtt>=2.3,<3",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24"]

[project.scripts]
walkingpad-mqtt = "walkingpad_mqtt.main:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

`src/walkingpad_mqtt/__init__.py`:

```python
"""WalkingPad A1 Pro (WiLink) to MQTT bridge."""
```

`tests/__init__.py` — пустой файл.

- [ ] **Step 3: venv и установка**

```bash
cd <путь-клона>
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e '.[dev]'
```

Expected: успешная установка. Проверка версий:

```bash
.venv/bin/pip show ph4-walkingpad bleak aiomqtt | grep -E '^(Name|Version)'
```

Expected: ph4-walkingpad 1.x, bleak 3.x (или 2.x), aiomqtt 2.x.

- [ ] **Step 4: Smoke-тест окружения**

```bash
.venv/bin/pytest
```

Expected: `no tests ran` (exit code 5 — это нормально, тестов ещё нет). Если ошибка сбора/импорта конфигурации — починить до продолжения.

- [ ] **Step 5: .gitignore и коммит**

`.gitignore`:

```
.venv/
__pycache__/
*.pyc
*.egg-info/
.pytest_cache/
```

```bash
git add pyproject.toml src tests .gitignore && git commit -m "chore: project scaffold"
```

---

### Task 2: Конфигурация (config.py)

**Files:**
- Create: `src/walkingpad_mqtt/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Пишем падающий тест**

`tests/test_config.py`:

```python
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
mac = "57:4C:4E:AA:BB:CC"
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
    assert cfg.ble.mac == "57:4C:4E:AA:BB:CC"
    assert cfg.ble.adapter == "hci1"
    assert cfg.mqtt.host == "broker.local"
    assert cfg.mqtt.port == 1884
    assert cfg.mqtt.prefix == "pad"
    assert cfg.mqtt.discovery_prefix == "ha"
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
    cfg = load_config(f)
    assert cfg.mqtt.host == "from-env"
    assert cfg.mqtt.port == 2883
    assert cfg.ble.mac == "AA:BB:CC:DD:EE:FF"
    assert cfg.mqtt.password == "secret"


def test_invalid_section_raises_config_error(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text("[mqtt]\nbogus_key = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mqtt"):
        load_config(f)
```

- [ ] **Step 2: Запуск — проверить, что падает**

```bash
.venv/bin/pytest tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'walkingpad_mqtt.config'`.

- [ ] **Step 3: Реализация**

`src/walkingpad_mqtt/config.py`:

```python
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
        with open(path, "rb") as f:
            data = tomllib.load(f)

    ble = _section(BleConfig, data, "ble")
    pad = _section(PadConfig, data, "pad")
    calories = _section(CaloriesConfig, data, "calories")
    mqtt = _section(MqttConfig, data, "mqtt")
    polling = _section(PollingConfig, data, "polling")

    if v := os.environ.get("WALKINGPAD_BLE_MAC"):
        ble.mac = v
    if v := os.environ.get("WALKINGPAD_BLE_ADAPTER"):
        ble.adapter = v
    if v := os.environ.get("WALKINGPAD_MQTT_HOST"):
        mqtt.host = v
    if v := os.environ.get("WALKINGPAD_MQTT_PORT"):
        mqtt.port = int(v)
    if v := os.environ.get("WALKINGPAD_MQTT_USERNAME"):
        mqtt.username = v
    if v := os.environ.get("WALKINGPAD_MQTT_PASSWORD"):
        mqtt.password = v

    return AppConfig(ble=ble, pad=pad, calories=calories, mqtt=mqtt, polling=polling)
```

- [ ] **Step 4: Запуск — проходят**

```bash
.venv/bin/pytest tests/test_config.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Коммит**

```bash
git add src/walkingpad_mqtt/config.py tests/test_config.py && git commit -m "feat: config loading with TOML and env overrides"
```

---

### Task 3: Калории (calories.py)

**Files:**
- Create: `src/walkingpad_mqtt/calories.py`
- Test: `tests/test_calories.py`

- [ ] **Step 1: Пишем падающий тест**

`tests/test_calories.py`:

```python
import pytest

from walkingpad_mqtt.calories import estimate_kcal


def test_typical_walk():
    # 80 кг * 5 км * 1.03 = 412.0
    assert estimate_kcal(80.0, 5.0) == 412.0


def test_zero_distance():
    assert estimate_kcal(80.0, 0.0) == 0.0


def test_custom_coefficient():
    assert estimate_kcal(70.0, 2.0, coefficient=1.05) == 147.0


def test_negative_raises():
    with pytest.raises(ValueError):
        estimate_kcal(80.0, -1.0)
    with pytest.raises(ValueError):
        estimate_kcal(-5.0, 1.0)
```

- [ ] **Step 2: Запуск — падает**

```bash
.venv/bin/pytest tests/test_calories.py -v
```

Expected: FAIL — `No module named 'walkingpad_mqtt.calories'`.

- [ ] **Step 3: Реализация**

`src/walkingpad_mqtt/calories.py`:

```python
from __future__ import annotations


def estimate_kcal(weight_kg: float, distance_km: float, coefficient: float = 1.03) -> float:
    """Оценка калорий ходьбы: ккал ≈ вес(кг) × дистанция(км) × коэффициент."""
    if weight_kg < 0 or distance_km < 0:
        raise ValueError("weight_kg and distance_km must be non-negative")
    return round(weight_kg * distance_km * coefficient, 1)
```

- [ ] **Step 4: Запуск — проходят**

```bash
.venv/bin/pytest tests/test_calories.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Коммит**

```bash
git add src/walkingpad_mqtt/calories.py tests/test_calories.py && git commit -m "feat: calorie estimation"
```

---

### Task 4: Команды (commands.py)

**Files:**
- Create: `src/walkingpad_mqtt/commands.py`
- Test: `tests/test_commands.py`

- [ ] **Step 1: Пишем падающий тест**

`tests/test_commands.py`:

```python
from walkingpad_mqtt.commands import Command, clip_speed, parse_command, parse_speed_set


def test_start_stop():
    assert parse_command(b'{"cmd":"start"}') == Command("start")
    assert parse_command('{"cmd":"stop"}') == Command("stop")


def test_speed_json():
    cmd = parse_command(b'{"cmd":"speed","value":4.0}')
    assert cmd == Command("speed", 4.0)


def test_speed_clipped_to_range():
    assert parse_command(b'{"cmd":"speed","value":20.0}') == Command("speed", 6.0)
    assert parse_command(b'{"cmd":"speed","value":0.1}') == Command("speed", 0.5)


def test_speed_set_topic_plain_number():
    assert parse_speed_set(b"4.5") == Command("speed", 4.5)
    assert parse_speed_set(b"99") == Command("speed", 6.0)


def test_invalid_payloads_return_none():
    assert parse_command(b"not json") is None
    assert parse_command(b"[1,2]") is None
    assert parse_command(b'{"cmd":"unknown"}') is None
    assert parse_command(b'{"cmd":"speed"}') is None
    assert parse_command(b'{"cmd":"speed","value":"fast"}') is None
    assert parse_command(b'{"cmd":"speed","value":true}') is None
    assert parse_speed_set(b"abc") is None
    assert parse_speed_set(b"") is None


def test_clip_speed_rounding():
    assert clip_speed(4.26, 0.5, 6.0) == 4.3
    assert clip_speed(4.24, 0.5, 6.0) == 4.2
```

- [ ] **Step 2: Запуск — падает**

```bash
.venv/bin/pytest tests/test_commands.py -v
```

Expected: FAIL — `No module named 'walkingpad_mqtt.commands'`.

- [ ] **Step 3: Реализация**

`src/walkingpad_mqtt/commands.py`:

```python
from __future__ import annotations

import json
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
        return Command("speed", clip_speed(float(value), min_speed, max_speed))
    return None


def parse_speed_set(
    payload: bytes | str,
    min_speed: float = DEFAULT_MIN_SPEED,
    max_speed: float = DEFAULT_MAX_SPEED,
) -> Command | None:
    """Парсит числовой payload топика .../speed/set (number-энтити HA)."""
    try:
        value = float(payload)
    except (TypeError, ValueError):
        return None
    return Command("speed", clip_speed(value, min_speed, max_speed))
```

- [ ] **Step 4: Запуск — проходят**

```bash
.venv/bin/pytest tests/test_commands.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Коммит**

```bash
git add src/walkingpad_mqtt/commands.py tests/test_commands.py && git commit -m "feat: MQTT command parsing and validation"
```

---

### Task 5: Детектор сессий (sessions.py)

**Files:**
- Create: `src/walkingpad_mqtt/sessions.py`
- Test: `tests/test_sessions.py`

Контракт: сессия открывается, когда скорость ремня > 0.05 км/ч; закрывается, когда скорость держится 0 ≥ 3 с (гистерезис); резкий сброс счётчиков (дистанция/шаги уменьшились) при активной сессии = закрытие старой и открытие новой. Внутри сессии хранится максимум дистанции/шагов/времени.

- [ ] **Step 1: Пишем падающие тесты**

`tests/test_sessions.py`:

```python
from walkingpad_mqtt.sessions import SessionDetector, StatusSample


def mk(ts, speed=0.0, dist=0.0, steps=0, t=0):
    return StatusSample(speed_kmh=speed, distance_km=dist, steps=steps, time_s=t, ts=ts)


def test_idle_samples_no_session():
    d = SessionDetector()
    assert d.feed(mk(0)) is None
    assert d.feed(mk(1)) is None
    assert d.session is None


def test_session_opens_on_movement():
    d = SessionDetector()
    assert d.feed(mk(0, speed=3.0, dist=0.0, steps=0, t=0)) is None  # открытие — не закрытие
    assert d.session is not None
    assert d.feed(mk(1, speed=3.0, dist=0.001, steps=1, t=1)) is None
    assert d.session.distance_km == 0.001


def test_session_closes_after_hysteresis():
    d = SessionDetector(hysteresis_s=3.0)
    d.feed(mk(0, speed=3.0, dist=0.0, steps=0, t=0))
    d.feed(mk(1, speed=3.0, dist=0.01, steps=10, t=5))
    assert d.feed(mk(2, speed=0.0, dist=0.01, steps=10, t=6)) is None  # первый ноль
    assert d.feed(mk(3, speed=0.0, dist=0.01, steps=10, t=7)) is None  # 1 с нуля
    closed = d.feed(mk(10, speed=0.0, dist=0.01, steps=10, t=7))      # 8 с нуля
    assert closed is not None
    assert closed.distance_km == 0.01
    assert closed.steps == 10
    assert closed.duration_s == 7
    assert closed.ended_at == 10
    assert d.session is None


def test_blip_does_not_close():
    d = SessionDetector(hysteresis_s=3.0)
    d.feed(mk(0, speed=3.0))
    assert d.feed(mk(1, speed=0.0)) is None
    assert d.feed(mk(2, speed=3.0)) is None  # снова движение — таймер нуля сброшен
    assert d.feed(mk(3, speed=0.0)) is None
    assert d.feed(mk(4, speed=0.0)) is None  # всего 2 с нуля
    assert d.session is not None


def test_counter_reset_closes_and_reopens():
    d = SessionDetector(hysteresis_s=3.0)
    d.feed(mk(0, speed=3.0, dist=0.5, steps=100, t=300))
    d.feed(mk(1, speed=0.0, dist=0.5, steps=100, t=300))
    # сессия ещё не закрыта (гистерезис), но дорожка сбросила счётчики и снова идёт
    closed = d.feed(mk(2, speed=3.0, dist=0.0, steps=0, t=0))
    assert closed is not None
    assert closed.distance_km == 0.5
    assert closed.steps == 100
    assert d.session is not None  # новая сессия уже открыта


def test_max_values_tracked():
    d = SessionDetector()
    d.feed(mk(0, speed=3.0, dist=0.1, steps=10, t=60))
    d.feed(mk(1, speed=3.0, dist=0.2, steps=25, t=120))
    d.feed(mk(2, speed=0.0, dist=0.2, steps=25, t=120))
    closed = d.feed(mk(10, speed=0.0, dist=0.2, steps=25, t=120))
    assert closed.distance_km == 0.2
    assert closed.steps == 25
    assert closed.duration_s == 120


def test_force_close():
    d = SessionDetector()
    d.feed(mk(0, speed=3.0, dist=1.0, steps=500, t=600))
    closed = d.force_close(ts=42.0)
    assert closed is not None
    assert closed.ended_at == 42.0
    assert d.force_close(ts=43.0) is None  # второй вызов — нечего закрывать
```

- [ ] **Step 2: Запуск — падает**

```bash
.venv/bin/pytest tests/test_sessions.py -v
```

Expected: FAIL — `No module named 'walkingpad_mqtt.sessions'`.

- [ ] **Step 3: Реализация**

`src/walkingpad_mqtt/sessions.py`:

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field

RUNNING_SPEED_THRESHOLD_KMH = 0.05
HYSTERESIS_S = 3.0

# Наилучшее известное отображение belt_state WiLink; уточняется при ручной
# проверке (Task 12). Детектор сессий от него НЕ зависит (только скорость).
BELT_STATE_LABELS = {
    1: "running",
    2: "slowing",
    3: "running",
    4: "starting",
    5: "stopped",
    6: "standby",
    7: "standby",
}


@dataclass
class StatusSample:
    speed_kmh: float
    distance_km: float
    steps: int
    time_s: int
    belt_state: int = 0
    belt_state_label: str = ""
    ts: float = field(default_factory=time.monotonic)


@dataclass
class Session:
    started_at: float
    ended_at: float | None = None
    distance_km: float = 0.0
    steps: int = 0
    duration_s: int = 0


@dataclass
class SessionDetector:
    hysteresis_s: float = HYSTERESIS_S
    session: Session | None = None
    _zero_since: float | None = field(default=None, repr=False)
    _last_dist: float = field(default=0.0, repr=False)
    _last_steps: int = field(default=0, repr=False)

    def feed(self, s: StatusSample) -> Session | None:
        """Принимает сэмпл статуса. Возвращает закрытую Session в момент закрытия, иначе None."""
        moving = s.speed_kmh > RUNNING_SPEED_THRESHOLD_KMH

        if self.session is None:
            if moving:
                self.session = Session(
                    started_at=s.ts,
                    distance_km=s.distance_km,
                    steps=s.steps,
                    duration_s=s.time_s,
                )
                self._zero_since = None
            self._last_dist = s.distance_km
            self._last_steps = s.steps
            return None

        # Активная сессия: сброс счётчиков = дорожка начала новую сессию без паузы
        if s.distance_km < self._last_dist - 1e-9 or s.steps < self._last_steps:
            closed = self._close(s.ts)
            self.session = Session(
                started_at=s.ts,
                distance_km=s.distance_km,
                steps=s.steps,
                duration_s=s.time_s,
            )
            self._zero_since = None
            self._last_dist = s.distance_km
            self._last_steps = s.steps
            return closed

        self.session.distance_km = max(self.session.distance_km, s.distance_km)
        self.session.steps = max(self.session.steps, s.steps)
        self.session.duration_s = max(self.session.duration_s, s.time_s)
        self._last_dist = s.distance_km
        self._last_steps = s.steps

        if moving:
            self._zero_since = None
            return None
        if self._zero_since is None:
            self._zero_since = s.ts
            return None
        if s.ts - self._zero_since >= self.hysteresis_s:
            return self._close(s.ts)
        return None

    def force_close(self, ts: float | None = None) -> Session | None:
        if self.session is None:
            return None
        return self._close(ts if ts is not None else time.monotonic())

    def _close(self, ts: float) -> Session:
        s = self.session
        assert s is not None
        s.ended_at = ts
        self.session = None
        self._zero_since = None
        return s
```

- [ ] **Step 4: Запуск — проходят**

```bash
.venv/bin/pytest tests/test_sessions.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Коммит**

```bash
git add src/walkingpad_mqtt/sessions.py tests/test_sessions.py && git commit -m "feat: session detector with hysteresis and counter-reset handling"
```

---

### Task 6: Пин-тест WiLink-протокола (библиотека)

**Files:**
- Test: `tests/test_pad_protocol.py`

Тест фиксирует ожидаемое поведение парсера ph4-walkingpad на реальном дампе трафика дорожки (из реверс-инжиниринга сообщества). Если упадёт после обновления зависимости — значит, библиотека изменила семантику полей.

- [ ] **Step 1: Пишем тест**

`tests/test_pad_protocol.py`:

```python
from ph4_walkingpad.pad import WalkingPadCurStatus, WalkingPadLastStatus

# Реальный фрейм статуса A1 Pro (из реверс-инжиниринга ph4-walkingpad):
# скорость 1.5 км/ч, время 4049 с, дистанция 1.71 км, 4782 шага, ручной режим
REAL_CUR_STATUS = bytes(
    [248, 162, 1, 15, 1, 0, 15, 209, 0, 0, 171, 0, 18, 174, 60, 0, 0, 58, 253]
)


def test_cur_status_fields():
    st = WalkingPadCurStatus.from_data(REAL_CUR_STATUS)
    assert st.speed == 15          # ×10 → 1.5 км/ч
    assert st.dist == 171          # ×10 м → 1.71 км
    assert st.steps == 4782
    assert st.time == 4049
    assert st.belt_state == 1
    assert st.manual_mode == 1
    assert st.app_speed == 60


def test_message_type_detection():
    assert WalkingPadCurStatus.check_type(REAL_CUR_STATUS)
    assert not WalkingPadLastStatus.check_type(REAL_CUR_STATUS)


def test_speed_units_are_tenths_of_kmh():
    st = WalkingPadCurStatus.from_data(REAL_CUR_STATUS)
    assert st.speed / 10.0 == 1.5
    assert st.dist / 100.0 == 1.71
```

- [ ] **Step 2: Запуск — проходят сразу**

```bash
.venv/bin/pytest tests/test_pad_protocol.py -v
```

Expected: 3 passed (это пин-тест существующей библиотеки — падать не должен; если падает, ОСТАНОВИТЬСЯ и разобраться с версией ph4-walkingpad, дальше задачи зависят от этой семантики).

- [ ] **Step 3: Коммит**

```bash
git add tests/test_pad_protocol.py && git commit -m "test: pin ph4-walkingpad WiLink parser semantics on real frame dump"
```

---

### Task 7: MQTT-пейлоады (mqtt_payloads.py)

**Files:**
- Create: `src/walkingpad_mqtt/mqtt_payloads.py`
- Test: `tests/test_mqtt_payloads.py`

Чистые функции-билдеры (без сети): state-JSON, финальный пейлоад сессии, HA discovery-конфиги.

- [ ] **Step 1: Пишем падающие тесты**

`tests/test_mqtt_payloads.py`:

```python
import json

from walkingpad_mqtt.mqtt_payloads import build_session_payload, build_state, discovery_configs
from walkingpad_mqtt.sessions import Session, StatusSample


def sample(**kw):
    base = dict(speed_kmh=3.2, distance_km=1.5, steps=1700, time_s=900,
                belt_state=1, belt_state_label="running", ts=0.0)
    base.update(kw)
    return StatusSample(**base)


def test_build_state_full():
    st = build_state(sample(), calories=123.5, connected=True)
    assert st == {
        "speed": 3.2,
        "distance": 1.5,
        "steps": 1700,
        "session_time_s": 900,
        "calories": 123.5,
        "belt_state": "running",
        "connected": True,
    }


def test_build_state_rounding():
    st = build_state(sample(speed_kmh=3.26, distance_km=1.234), calories=0.0, connected=True)
    assert st["speed"] == 3.3
    assert st["distance"] == 1.23


def test_build_state_without_sample():
    st = build_state(None, calories=0.0, connected=False)
    assert st == {"connected": False}


def test_build_session_payload():
    s = Session(started_at=100.0, ended_at=200.0, distance_km=2.5, steps=2800, duration_s=1500)
    obj = json.loads(build_session_payload(s))
    assert obj == {
        "started_at": 100.0,
        "ended_at": 200.0,
        "distance_km": 2.5,
        "steps": 2800,
        "duration_s": 1500,
    }


def test_discovery_configs_structure():
    cfgs = discovery_configs("walkingpad", "homeassistant", 0.5, 6.0)
    topics = [t for t, _ in cfgs]
    assert len(topics) == len(set(topics)), "топики уникальны"
    # 6 сенсоров + 1 бинарный + 2 кнопки + 1 number
    assert len(cfgs) == 10
    for topic, payload in cfgs:
        obj = json.loads(payload)
        assert obj["availability_topic"] == "walkingpad/availability"
        assert obj["device"]["identifiers"] == ["walkingpad_a1pro"]
        assert obj["unique_id"]
    assert f"homeassistant/sensor/walkingpad/speed/config" in topics
    assert "homeassistant/binary_sensor/walkingpad/connected/config" in topics
    assert "homeassistant/button/walkingpad/start/config" in topics
    assert "homeassistant/button/walkingpad/stop/config" in topics
    assert "homeassistant/number/walkingpad/speed_set/config" in topics


def test_discovery_button_payload_press():
    cfgs = dict(discovery_configs("walkingpad", "homeassistant", 0.5, 6.0))
    start = json.loads(cfgs["homeassistant/button/walkingpad/start/config"])
    assert start["command_topic"] == "walkingpad/command"
    assert json.loads(start["payload_press"]) == {"cmd": "start"}


def test_discovery_number_bounds():
    cfgs = dict(discovery_configs("walkingpad", "homeassistant", 0.5, 6.0))
    n = json.loads(cfgs["homeassistant/number/walkingpad/speed_set/config"])
    assert n["command_topic"] == "walkingpad/speed/set"
    assert n["min"] == 0.5
    assert n["max"] == 6.0
    assert n["step"] == 0.5
    assert n["value_template"] == "{{ value_json.speed }}"


def test_discovery_binary_sensor_true_false():
    cfgs = dict(discovery_configs("walkingpad", "homeassistant", 0.5, 6.0))
    b = json.loads(cfgs["homeassistant/binary_sensor/walkingpad/connected/config"])
    # state публикуется как JSON: value_json.connected рендерится в "True"/"False"
    assert b["payload_on"] == "True"
    assert b["payload_off"] == "False"


def test_discovery_sensors_use_json_path():
    cfgs = dict(discovery_configs("walkingpad", "homeassistant", 0.5, 6.0))
    dist = json.loads(cfgs["homeassistant/sensor/walkingpad/distance/config"])
    assert dist["value_template"] == "{{ value_json.distance }}"
    assert dist["unit_of_measurement"] == "km"
```

Внимание по `payload_on`: `build_state` возвращает Python-bool; слой публикации делает `json.dumps` → в топике `"connected": true` (JSON). HA-шаблон `{{ value_json.connected }}` вернёт строку `"True"`/`"False"` (Python-строкификация шаблонизатором), поэтому payload_on/off именно `"True"`/`"False"`. Это проверяется ручным тестом в Task 12; при несоответствии поправить в одном месте — тесте и билдере.

- [ ] **Step 2: Запуск — падает**

```bash
.venv/bin/pytest tests/test_mqtt_payloads.py -v
```

Expected: FAIL — `No module named 'walkingpad_mqtt.mqtt_payloads'`.

- [ ] **Step 3: Реализация**

`src/walkingpad_mqtt/mqtt_payloads.py`:

```python
from __future__ import annotations

import json

from .sessions import Session, StatusSample

DEVICE = {
    "identifiers": ["walkingpad_a1pro"],
    "name": "WalkingPad A1 Pro",
    "manufacturer": "KingSmith",
    "model": "WPA1F-Pro",
}


def build_state(sample: StatusSample | None, calories: float, connected: bool) -> dict:
    if sample is None:
        return {"connected": connected}
    return {
        "speed": round(sample.speed_kmh, 1),
        "distance": round(sample.distance_km, 2),
        "steps": sample.steps,
        "session_time_s": sample.time_s,
        "calories": calories,
        "belt_state": sample.belt_state_label,
        "connected": connected,
    }


def build_session_payload(s: Session) -> str:
    return json.dumps(
        {
            "started_at": s.started_at,
            "ended_at": s.ended_at,
            "distance_km": round(s.distance_km, 2),
            "steps": s.steps,
            "duration_s": s.duration_s,
        },
        ensure_ascii=False,
    )


def discovery_configs(
    prefix: str,
    discovery_prefix: str,
    min_speed: float,
    max_speed: float,
) -> list[tuple[str, str]]:
    """10 discovery-конфигов HA: 6 sensor, 1 binary_sensor, 2 button, 1 number."""
    state_t = f"{prefix}/state"
    avail_t = f"{prefix}/availability"
    cmd_t = f"{prefix}/command"

    def sensor(key: str, name: str, icon: str, unit: str | None = None, device_class: str | None = None):
        cfg: dict = {
            "name": name,
            "unique_id": f"walkingpad_{key}",
            "state_topic": state_t,
            "value_template": "{{ value_json.%s }}" % key,
            "availability_topic": avail_t,
            "icon": icon,
            "device": DEVICE,
        }
        if unit is not None:
            cfg["unit_of_measurement"] = unit
        if device_class is not None:
            cfg["device_class"] = device_class
        return f"{discovery_prefix}/sensor/walkingpad/{key}/config", json.dumps(cfg, ensure_ascii=False)

    configs = [
        sensor("speed", "WalkingPad скорость", "mdi:speed", unit="km/h"),
        sensor("distance", "WalkingPad дистанция", "mdi:map-marker-distance", unit="km", device_class="distance"),
        sensor("steps", "WalkingPad шаги", "mdi:foot-print", unit="steps"),
        sensor("session_time_s", "WalkingPad время сессии", "mdi:timer", unit="s", device_class="duration"),
        sensor("calories", "WalkingPad калории", "mdi:fire", unit="kcal", device_class="energy"),
        sensor("belt_state", "WalkingPad состояние", "mdi:treadmill"),
    ]

    binary = {
        "name": "WalkingPad BLE связь",
        "unique_id": "walkingpad_connected",
        "state_topic": state_t,
        "value_template": "{{ value_json.connected }}",
        "payload_on": "True",
        "payload_off": "False",
        "availability_topic": avail_t,
        "device_class": "connectivity",
        "device": DEVICE,
    }
    configs.append((f"{discovery_prefix}/binary_sensor/walkingpad/connected/config", json.dumps(binary, ensure_ascii=False)))

    for action, label in (("start", "старт"), ("stop", "стоп")):
        button = {
            "name": f"WalkingPad {label}",
            "unique_id": f"walkingpad_{action}",
            "command_topic": cmd_t,
            "payload_press": json.dumps({"cmd": action}),
            "availability_topic": avail_t,
            "device": DEVICE,
        }
        configs.append((f"{discovery_prefix}/button/walkingpad/{action}/config", json.dumps(button, ensure_ascii=False)))

    number = {
        "name": "WalkingPad скорость цель",
        "unique_id": "walkingpad_speed_set",
        "command_topic": f"{prefix}/speed/set",
        "state_topic": state_t,
        "value_template": "{{ value_json.speed }}",
        "min": min_speed,
        "max": max_speed,
        "step": 0.5,
        "mode": "box",
        "icon": "mdi:speedometer",
        "availability_topic": avail_t,
        "device": DEVICE,
    }
    configs.append((f"{discovery_prefix}/number/walkingpad/speed_set/config", json.dumps(number, ensure_ascii=False)))
    return configs
```

- [ ] **Step 4: Запуск — проходят**

```bash
.venv/bin/pytest tests/test_mqtt_payloads.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Коммит**

```bash
git add src/walkingpad_mqtt/mqtt_payloads.py tests/test_mqtt_payloads.py && git commit -m "feat: MQTT state/session payloads and HA discovery configs"
```

---

### Task 8: MQTT-слой (mqtt_layer.py)

**Files:**
- Create: `src/walkingpad_mqtt/mqtt_layer.py`
- Test: `tests/test_mqtt_layer.py`

aiomqtt-клиент с reconnect-циклом, LWT, публикацией discovery при подключении и диспетчером входящих команд. Сетевые части (run/_connect) покрываются ручной проверкой; автотесты — на диспетчер `_dispatch`.

- [ ] **Step 1: Пишем падающие тесты**

`tests/test_mqtt_layer.py`:

```python
from types import SimpleNamespace

from walkingpad_mqtt.commands import Command
from walkingpad_mqtt.config import AppConfig, BleConfig, CaloriesConfig, MqttConfig, PadConfig, PollingConfig
from walkingpad_mqtt.mqtt_layer import MqttLayer
from walkingpad_mqtt.sessions import Session


def make_cfg():
    return AppConfig(
        ble=BleConfig(mac="AA:BB:CC:DD:EE:FF"),
        pad=PadConfig(min_speed_kmh=0.5, max_speed_kmh=6.0),
        calories=CaloriesConfig(),
        mqtt=MqttConfig(host="localhost"),
        polling=PollingConfig(interval_s=1.0),
    )


def msg(topic, payload):
    return SimpleNamespace(topic=topic, payload=payload)


def test_dispatch_start_command():
    received = []
    layer = MqttLayer(make_cfg(), on_command=received.append)
    layer._dispatch(msg("walkingpad/command", b'{"cmd":"start"}'))
    assert received == [Command("start")]


def test_dispatch_speed_set_topic():
    received = []
    layer = MqttLayer(make_cfg(), on_command=received.append)
    layer._dispatch(msg("walkingpad/speed/set", b"4.5"))
    assert received == [Command("speed", 4.5)]


def test_dispatch_invalid_payload_ignored():
    received = []
    layer = MqttLayer(make_cfg(), on_command=received.append)
    layer._dispatch(msg("walkingpad/command", b"garbage"))
    layer._dispatch(msg("walkingpad/command", b'{"cmd":"nope"}'))
    layer._dispatch(msg("walkingpad/speed/set", b"xx"))
    layer._dispatch(msg("walkingpad/unknown", b'{"cmd":"start"}'))
    assert received == []


def test_publish_without_connection_is_noop():
    layer = MqttLayer(make_cfg())
    assert layer.connected is False
    layer.publish_state_nowait(None, 0.0, False)
    layer.publish_session_nowait(Session(started_at=0, ended_at=1, distance_km=1.0, steps=10, duration_s=60))
```

- [ ] **Step 2: Запуск — падает**

```bash
.venv/bin/pytest tests/test_mqtt_layer.py -v
```

Expected: FAIL — `No module named 'walkingpad_mqtt.mqtt_layer'`.

- [ ] **Step 3: Реализация**

`src/walkingpad_mqtt/mqtt_layer.py`:

```python
from __future__ import annotations

import asyncio
import contextlib
import json
import logging

import aiomqtt

from .commands import Command, parse_command, parse_speed_set
from .config import AppConfig
from .mqtt_payloads import Session, build_session_payload, build_state, discovery_configs

log = logging.getLogger(__name__)

RECONNECT_MIN_S = 1.0
RECONNECT_MAX_S = 30.0


class MqttLayer:
    def __init__(
        self,
        cfg: AppConfig,
        on_command=None,
        reconnect_min_s: float = RECONNECT_MIN_S,
        reconnect_max_s: float = RECONNECT_MAX_S,
    ):
        self.cfg = cfg
        self.on_command = on_command
        self.reconnect_min_s = reconnect_min_s
        self.reconnect_max_s = reconnect_max_s
        self._client: aiomqtt.Client | None = None
        self._bg: list[asyncio.Task] = []

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def run(self) -> None:
        backoff = self.reconnect_min_s
        while True:
            try:
                async with self._connect() as client:
                    self._client = client
                    log.info("MQTT connected to %s:%s", self.cfg.mqtt.host, self.cfg.mqtt.port)
                    await self._on_connect(client)
                    async for message in client.messages:
                        self._dispatch(message)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("MQTT connection ended: %r", e)
            finally:
                self._client = None
            log.info("MQTT reconnect in %.0f s", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.reconnect_max_s)

    def _connect(self) -> aiomqtt.Client:
        m = self.cfg.mqtt
        return aiomqtt.Client(
            hostname=m.host,
            port=m.port,
            username=m.username,
            password=m.password,
            will=aiomqtt.Will(topic=f"{m.prefix}/availability", payload=b"offline", retain=True),
        )

    async def _on_connect(self, client: aiomqtt.Client) -> None:
        m = self.cfg.mqtt
        await client.publish(f"{m.prefix}/availability", b"online", retain=True)
        configs = discovery_configs(m.prefix, m.discovery_prefix, self.cfg.pad.min_speed_kmh, self.cfg.pad.max_speed_kmh)
        for topic, payload in configs:
            await client.publish(topic, payload.encode(), retain=True)
        await client.subscribe(f"{m.prefix}/command")
        await client.subscribe(f"{m.prefix}/speed/set")
        log.info("Discovery published (%d entities), subscribed to commands", len(configs))

    def _dispatch(self, message) -> None:
        topic = str(message.topic)
        payload = bytes(message.payload)
        m = self.cfg.mqtt
        cmd: Command | None = None
        if topic == f"{m.prefix}/command":
            cmd = parse_command(payload, self.cfg.pad.min_speed_kmh, self.cfg.pad.max_speed_kmh)
        elif topic == f"{m.prefix}/speed/set":
            cmd = parse_speed_set(payload, self.cfg.pad.min_speed_kmh, self.cfg.pad.max_speed_kmh)
        if cmd is None:
            log.warning("Ignoring invalid MQTT payload on %s: %r", topic, payload)
            return
        if self.on_command is not None:
            self.on_command(cmd)

    def publish_state_nowait(self, sample, calories: float, connected: bool) -> None:
        payload = json.dumps(build_state(sample, calories, connected), ensure_ascii=False).encode()
        self._publish_nowait(f"{self.cfg.mqtt.prefix}/state", payload, retain=True)

    def publish_session_nowait(self, session: Session) -> None:
        self._publish_nowait(f"{self.cfg.mqtt.prefix}/session", build_session_payload(session).encode(), retain=True)

    def _publish_nowait(self, topic: str, payload: bytes, retain: bool = False) -> None:
        client = self._client
        if client is None:
            return

        async def _pub() -> None:
            with contextlib.suppress(Exception):
                await client.publish(topic, payload, retain=retain)

        try:
            self._bg.append(asyncio.get_running_loop().create_task(_pub()))
            self._bg = [t for t in self._bg if not t.done()]
        except RuntimeError:
            pass  # нет запущенного event loop — publishing невозможен, молча пропускаем
```

(Импорт `Session` из `.mqtt_payloads` невозможен — он в `.sessions`. Исправить строку импорта: `from .sessions import Session` и `from .mqtt_payloads import build_session_payload, build_state, discovery_configs`.)

- [ ] **Step 4: Запуск — проходят**

```bash
.venv/bin/pytest tests/test_mqtt_layer.py -v
```

Expected: 4 passed. Если `RuntimeError: no running event loop` в `test_publish_without_connection_is_noop` — проверь, что `_publish_nowait` выходит по `client is None` до попытки создать задачу (тест синхронный, event loop не запущен).

- [ ] **Step 5: Коммит**

```bash
git add src/walkingpad_mqtt/mqtt_layer.py tests/test_mqtt_layer.py && git commit -m "feat: MQTT layer with discovery publish, LWT and command dispatch"
```

---

### Task 9: BLE-клиент дорожки (pad_client.py)

**Files:**
- Create: `src/walkingpad_mqtt/pad_client.py`
- Test: `tests/test_pad_client.py`

Обёртка над `ph4_walkingpad.pad.Controller`: reconnect-цикл (бэкофф 5→60 с), poll-loop, командный loop с debounce скорости (последняя скорость выигрывает), конвертация статусов библиотеки в `StatusSample`. Встроенный pacing библиотеки (`minimal_cmd_space=0.69` с) гарантирует интервалы между write.

- [ ] **Step 1: Пишем падающие тесты**

`tests/test_pad_client.py`:

```python
import asyncio

import pytest

from walkingpad_mqtt.commands import Command
from walkingpad_mqtt.config import AppConfig, BleConfig, CaloriesConfig, MqttConfig, PadConfig, PollingConfig
from walkingpad_mqtt.pad_client import PadClient
from walkingpad_mqtt.sessions import StatusSample


def make_cfg(interval_s=0.05):
    return AppConfig(
        ble=BleConfig(mac="AA:BB:CC:DD:EE:FF"),
        pad=PadConfig(),
        calories=CaloriesConfig(),
        mqtt=MqttConfig(),
        polling=PollingConfig(interval_s=interval_s),
    )


class FakeController:
    def __init__(self, fail_on_run=False):
        self.fail_on_run = fail_on_run
        self.run_calls = 0
        self.disconnect_calls = 0
        self.stats_requests = 0
        self.written: list = []
        self.handler_cur_status = None
        self.handler_last_status = None

    async def run(self):
        self.run_calls += 1
        if self.fail_on_run:
            raise ConnectionError("ble gone")

    async def disconnect(self):
        self.disconnect_calls += 1

    async def ask_stats(self):
        self.stats_requests += 1

    async def start_belt(self):
        self.written.append("start")

    async def stop_belt(self):
        self.written.append("stop")

    async def change_speed(self, v):
        self.written.append(("speed", v))


async def run_briefly(coro, seconds=0.3):
    task = asyncio.create_task(coro)
    await asyncio.sleep(seconds)
    task.cancel()
    with contextlib_suppress():
        await task


class contextlib_suppress:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return True


def test_send_maps_actions():
    fake = FakeController()
    client = PadClient(make_cfg(), on_status=lambda s: None, on_last_status=lambda *a: None,
                       on_connected=lambda: None, on_disconnected=lambda: None)
    asyncio.run(client._send(fake, Command("start")))
    asyncio.run(client._send(fake, Command("stop")))
    asyncio.run(client._send(fake, Command("speed", 4.0)))
    assert fake.written == ["start", "stop", ("speed", 40)]


def test_handle_cur_status_converts_units():
    from ph4_walkingpad.pad import WalkingPadCurStatus

    st = WalkingPadCurStatus.from_data(
        bytes([248, 162, 1, 15, 1, 0, 15, 209, 0, 0, 171, 0, 18, 174, 60, 0, 0, 58, 253])
    )
    got: list[StatusSample] = []
    client = PadClient(make_cfg(), on_status=got.append, on_last_status=lambda *a: None,
                       on_connected=lambda: None, on_disconnected=lambda: None)
    client._handle_cur_status("sender", st)
    assert len(got) == 1
    s = got[0]
    assert s.speed_kmh == 1.5
    assert s.distance_km == 1.71
    assert s.steps == 4782
    assert s.time_s == 4049
    assert s.belt_state == 1
    assert s.belt_state_label == "running"


async def test_speed_debounce_latest_wins():
    fake = FakeController()
    client = PadClient(make_cfg(), on_status=lambda s: None, on_last_status=lambda *a: None,
                       on_connected=lambda: None, on_disconnected=lambda: None)
    for v in (2.0, 3.0, 4.5):
        client.submit(Command("speed", v))
    task = asyncio.create_task(client._cmd_loop(fake))
    await asyncio.sleep(0.5)  # > SPEED_DEBOUNCE_S
    task.cancel()
    with contextlib_suppress():
        await task
    assert fake.written == [("speed", 45)]  # только последняя (4.5 км/ч → 45)


async def test_session_polls_and_recovers():
    made = [FakeController(), FakeController(fail_on_run=True), FakeController()]

    def factory(addr):
        return made.pop(0) if made else FakeController()

    events: list[str] = []

    client = PadClient(
        make_cfg(),
        on_status=lambda s: events.append("status"),
        on_last_status=lambda *a: events.append("last"),
        on_connected=lambda: events.append("connected"),
        on_disconnected=lambda: events.append("disconnected"),
        controller_factory=factory,
        reconnect_min_s=0.05,
        reconnect_max_s=0.05,
    )
    task = asyncio.create_task(client.run())
    await asyncio.sleep(0.5)
    task.cancel()
    with contextlib_suppress():
        await task
    assert "connected" in events
    assert made[0].stats_requests > 0 or made[1].run_calls == 1
    assert events.count("disconnected") >= 1
    assert made[-1].run_calls == 1  # третья попытка подключилась снова
```

- [ ] **Step 2: Запуск — падает**

```bash
.venv/bin/pytest tests/test_pad_client.py -v
```

Expected: FAIL — `No module named 'walkingpad_mqtt.pad_client'`.

- [ ] **Step 3: Реализация**

`src/walkingpad_mqtt/pad_client.py`:

```python
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Callable

from .commands import Command
from .config import AppConfig
from .sessions import BELT_STATE_LABELS, StatusSample

log = logging.getLogger(__name__)

RECONNECT_MIN_S = 5.0
RECONNECT_MAX_S = 60.0
SPEED_DEBOUNCE_S = 0.3


def default_controller_factory(address: str):
    from ph4_walkingpad.pad import Controller

    return Controller(address, do_read_chars=False)


class PadClient:
    def __init__(
        self,
        cfg: AppConfig,
        on_status: Callable[[StatusSample], None],
        on_last_status: Callable[[float, int, int], None],
        on_connected: Callable[[], None],
        on_disconnected: Callable[[], None],
        controller_factory=None,
        reconnect_min_s: float = RECONNECT_MIN_S,
        reconnect_max_s: float = RECONNECT_MAX_S,
    ):
        self.cfg = cfg
        self.on_status = on_status
        self.on_last_status = on_last_status
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected
        self.controller_factory = controller_factory or default_controller_factory
        self.reconnect_min_s = reconnect_min_s
        self.reconnect_max_s = reconnect_max_s
        self._queue: asyncio.Queue[Command] = asyncio.Queue()
        self._controller = None

    def submit(self, cmd: Command) -> None:
        self._queue.put_nowait(cmd)

    async def run(self) -> None:
        backoff = self.reconnect_min_s
        while True:
            try:
                await self._session()
                backoff = self.reconnect_min_s
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("BLE session ended: %r", e)
            self._safe(self.on_disconnected)
            log.info("BLE reconnect in %.0f s", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.reconnect_max_s)

    async def _session(self) -> None:
        controller = self.controller_factory(self.cfg.ble.mac)
        controller.handler_cur_status = self._handle_cur_status
        controller.handler_last_status = self._handle_last_status
        await controller.run()
        self._controller = controller
        self._safe(self.on_connected)
        try:
            poll = asyncio.create_task(self._poll_loop(controller))
            cmd = asyncio.create_task(self._cmd_loop(controller))
            done, pending = await asyncio.wait({poll, cmd}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
            for t in done:
                t.result()
        finally:
            self._controller = None
            with contextlib.suppress(Exception):
                await controller.disconnect()

    async def _poll_loop(self, controller) -> None:
        while True:
            await controller.ask_stats()
            await asyncio.sleep(self.cfg.polling.interval_s)

    async def _cmd_loop(self, controller) -> None:
        while True:
            cmd = await self._queue.get()
            if cmd.action == "speed":
                await asyncio.sleep(SPEED_DEBOUNCE_S)
                cmd = self._collapse_speeds(cmd)
            await self._send(controller, cmd)

    def _collapse_speeds(self, cmd: Command) -> Command:
        stash: list[Command] = []
        while True:
            try:
                nxt = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if nxt.action == "speed":
                cmd = nxt
            else:
                stash.append(nxt)
        for item in stash:
            self._queue.put_nowait(item)
        return cmd

    async def _send(self, controller, cmd: Command) -> None:
        if cmd.action == "start":
            await controller.start_belt()
        elif cmd.action == "stop":
            await controller.stop_belt()
        elif cmd.action == "speed":
            await controller.change_speed(int(round(cmd.speed_kmh * 10)))
        else:
            log.warning("Unknown command action: %r", cmd.action)

    def _handle_cur_status(self, sender, st) -> None:
        sample = StatusSample(
            speed_kmh=st.speed / 10.0,
            distance_km=st.dist / 100.0,
            steps=st.steps,
            time_s=st.time,
            belt_state=st.belt_state,
            belt_state_label=BELT_STATE_LABELS.get(st.belt_state, f"unknown_{st.belt_state}"),
        )
        self._safe_callback_status(sample)

    def _safe_callback_status(self, sample: StatusSample) -> None:
        with contextlib.suppress(Exception):
            self.on_status(sample)

    def _handle_last_status(self, sender, st) -> None:
        with contextlib.suppress(Exception):
            self.on_last_status(st.dist / 100.0, st.time, st.steps)

    @staticmethod
    def _safe(cb: Callable[[], None]) -> None:
        with contextlib.suppress(Exception):
            cb()
```

- [ ] **Step 4: Запуск — проходят**

```bash
.venv/bin/pytest tests/test_pad_client.py -v
```

Expected: 5 passed. Затем весь набор:

```bash
.venv/bin/pytest
```

Expected: все тесты зелёные.

- [ ] **Step 5: Коммит**

```bash
git add src/walkingpad_mqtt/pad_client.py tests/test_pad_client.py && git commit -m "feat: BLE pad client with reconnect, polling and debounced commands"
```

---

### Task 10: Точка входа и склейка (main.py)

**Files:**
- Create: `src/walkingpad_mqtt/main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Пишем падающий тест**

`tests/test_main.py`:

```python
import json

from walkingpad_mqtt.config import AppConfig, BleConfig, CaloriesConfig, MqttConfig, PadConfig, PollingConfig
from walkingpad_mqtt.main import App
from walkingpad_mqtt.sessions import StatusSample


def make_cfg():
    return AppConfig(
        ble=BleConfig(mac="AA:BB:CC:DD:EE:FF"),
        pad=PadConfig(),
        calories=CaloriesConfig(weight_kg=80.0),
        mqtt=MqttConfig(),
        polling=PollingConfig(interval_s=1.0),
    )


def sample(**kw):
    base = dict(speed_kmh=3.0, distance_km=2.0, steps=2000, time_s=1200,
                belt_state=1, belt_state_label="running", ts=0.0)
    base.update(kw)
    return StatusSample(**base)


def test_status_publishes_state():
    app = App(make_cfg())
    published = []
    app.mqtt.publish_state_nowait = lambda s, kcal, conn: published.append((s, kcal, conn))
    app._on_status(sample())
    assert len(published) == 1
    s, kcal, conn = published[0]
    assert s.speed_kmh == 3.0
    assert kcal == 164.8  # 80 кг × 2.0 км × 1.03
    assert conn is False


def test_session_close_publishes_final():
    app = App(make_cfg())
    sessions = []
    app.mqtt.publish_session_nowait = sessions.append
    # движемся — открыли сессию
    app._on_status(sample(speed_kmh=3.0, distance_km=0.5, steps=500, time_s=300))
    # остановились 4 раза с шагом 1 с (гистерезис 3 с) — на 4-м закроется
    app._on_status(sample(speed_kmh=0.0, distance_km=1.0, steps=1000, time_s=600, ts=10.0))
    app._on_status(sample(speed_kmh=0.0, distance_km=1.0, steps=1000, time_s=600, ts=11.0))
    app._on_status(sample(speed_kmh=0.0, distance_km=1.0, steps=1000, time_s=600, ts=12.0))
    app._on_status(sample(speed_kmh=0.0, distance_km=1.0, steps=1000, time_s=600, ts=13.0))
    assert len(sessions) == 1
    assert sessions[0].distance_km == 1.0
    assert sessions[0].steps == 1000
    assert sessions[0].duration_s == 600


def test_command_routed_to_pad():
    app = App(make_cfg())
    submitted = []
    app.pad.submit = submitted.append
    from walkingpad_mqtt.commands import Command

    app._on_command(Command("stop"))
    assert submitted == [Command("stop")]


def test_last_status_recovers_session():
    app = App(make_cfg())
    sessions = []
    app.mqtt.publish_session_nowait = sessions.append
    app._on_last_status(3.3, 1800, 3500)
    assert len(sessions) == 1
    assert sessions[0].distance_km == 3.3
    assert sessions[0].steps == 3500
    assert sessions[0].duration_s == 1800
```

- [ ] **Step 2: Запуск — падает**

```bash
.venv/bin/pytest tests/test_main.py -v
```

Expected: FAIL — `No module named 'walkingpad_mqtt.main'`.

- [ ] **Step 3: Реализация**

`src/walkingpad_mqtt/main.py`:

```python
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
from pathlib import Path

from .calories import estimate_kcal
from .commands import Command
from .config import DEFAULT_CONFIG_PATH, AppConfig, load_config
from .mqtt_layer import MqttLayer
from .pad_client import PadClient
from .sessions import Session, SessionDetector, StatusSample

log = logging.getLogger("walkingpad")


class App:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.detector = SessionDetector()
        self.latest: StatusSample | None = None
        self.session_kcal = 0.0
        self.ble_connected = False
        self.mqtt = MqttLayer(cfg, on_command=self._on_command)
        self.pad = PadClient(
            cfg,
            on_status=self._on_status,
            on_last_status=self._on_last_status,
            on_connected=self._on_ble_connected,
            on_disconnected=self._on_ble_disconnected,
        )

    def _on_command(self, cmd: Command) -> None:
        log.info("Command from MQTT: %r", cmd)
        self.pad.submit(cmd)

    def _on_status(self, sample: StatusSample) -> None:
        self.latest = sample
        self.session_kcal = estimate_kcal(
            self.cfg.calories.weight_kg, sample.distance_km, self.cfg.calories.coefficient
        )
        closed = self.detector.feed(sample)
        if closed is not None:
            log.info("Session closed: dist=%.2f km, steps=%d, %d s", closed.distance_km, closed.steps, closed.duration_s)
            self.mqtt.publish_session_nowait(closed)
        self.mqtt.publish_state_nowait(sample, self.session_kcal, self.ble_connected)

    def _on_last_status(self, dist_km: float, time_s: int, steps: int) -> None:
        # Дорожка отдала финальную статистику последней сессии (обычно после переподключения)
        recovered = Session(started_at=0.0, ended_at=0.0, distance_km=dist_km, steps=steps, duration_s=time_s)
        log.info("Recovered last session stats: dist=%.2f km, steps=%d, %d s", dist_km, steps, time_s)
        self.mqtt.publish_session_nowait(recovered)

    def _on_ble_connected(self) -> None:
        self.ble_connected = True
        self.mqtt.publish_state_nowait(self.latest, self.session_kcal, True)

    def _on_ble_disconnected(self) -> None:
        self.ble_connected = False
        self.mqtt.publish_state_nowait(self.latest, self.session_kcal, False)

    async def run(self) -> None:
        tasks = [asyncio.create_task(self.mqtt.run()), asyncio.create_task(self.pad.run())]
        try:
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t


async def discover() -> None:
    from bleak import BleakScanner

    print("Сканирую BLE 5 с (ищу WalkingPad)...")
    devices = await BleakScanner.discover(timeout=5.0, return_adv=True)
    found = False
    for dev, adv in devices.values():
        name = dev.name or ""
        has_wilink = any(u.lower().startswith("0000fe00") for u in adv.service_uuids)
        if "walking" in name.lower() or has_wilink:
            found = True
            print(f"Кандидат: {dev.address}  имя={name!r}  сервисы={adv.service_uuids}")
    if not found:
        print("WalkingPad не найден. Включите дорожку кнопкой и повторите.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="walkingpad-mqtt", description="WalkingPad A1 Pro -> MQTT мост")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="путь к config.toml")
    parser.add_argument("--discover", action="store_true", help="найти MAC дорожки по BLE")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config(Path(args.config))
    if args.discover:
        asyncio.run(discover())
        return 0
    if not cfg.ble.mac:
        log.error("MAC дорожки не задан: запустите с --discover и впишите [ble] mac в %s", args.config)
        return 2
    try:
        asyncio.run(App(cfg).run())
    except KeyboardInterrupt:
        log.info("Stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Запуск — проходят**

```bash
.venv/bin/pytest tests/test_main.py -v && .venv/bin/pytest
```

Expected: 4 passed; весь набор зелёный. Smoke: `.venv/bin/walkingpad-mqtt --help` печатает usage (entry point из pyproject).

- [ ] **Step 5: Коммит**

```bash
git add src/walkingpad_mqtt/main.py tests/test_main.py && git commit -m "feat: application wiring, discover utility and entry point"
```

---

### Task 11: Конфиг-пример, systemd, README

**Files:**
- Create: `config/config.example.toml`
- Create: `systemd/walkingpad-mqtt.service`
- Create: `README.md`

- [ ] **Step 1: config/config.example.toml**

```toml
# Скопировать в ~/.config/walkingpad/config.toml и заполнить.
# MAC смотрите: walkingpad-mqtt --discover

[ble]
mac = "57:4C:4E:AA:BB:CC"
adapter = "hci0"

[pad]
min_speed_kmh = 0.5
max_speed_kmh = 6.0

[calories]
weight_kg = 80.0
coefficient = 1.03

[mqtt]
host = "home-assistant.local"
port = 1883
username = ""
password = ""
prefix = "walkingpad"
discovery_prefix = "homeassistant"

[polling]
interval_s = 1.0
```

- [ ] **Step 2: systemd/walkingpad-mqtt.service**

```ini
[Unit]
Description=WalkingPad A1 Pro -> MQTT bridge
After=bluetooth.target network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/CONFIGURATION/FITNESS
ExecStart=%h/CONFIGURATION/FITNESS/.venv/bin/walkingpad-mqtt
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
```

- [ ] **Step 3: README.md**

```markdown
# walkingpad-mqtt

WalkingPad A1 Pro (WPA1F-Pro) → MQTT мост для Home Assistant. Держит постоянное
BLE-подключение к дорожке (проприетарный WiLink-протокол KingSmith, сервис
0xFE00), публикует телеметрию и discovery-энтити, принимает команды.

Важно: дорожка допускает одно BLE-подключение — пока работает сервис,
приложение WalkingPad на телефоне не подключится.

## Установка

    python3 -m venv .venv
    .venv/bin/pip install -e '.[dev]'

(pypi.org на этом хосте закрыт DNS-фильтром; ~/.config/pip/pip.conf указывает
на зеркало Tsinghua.)

## Настройка

1. Включите дорожку (кнопка на корпусе / удержание MODE).
2. `.venv/bin/walkingpad-mqtt --discover` — покажет MAC.
3. `mkdir -p ~/.config/walkingpad && cp config/config.example.toml ~/.config/walkingpad/config.toml`
4. Впишите MAC и адрес MQTT-брокера.

## Запуск вручную

    .venv/bin/walkingpad-mqtt          # foreground
    .venv/bin/walkingpad-mqtt -v       # debug-логи

## Автозапуск (systemd user)

    mkdir -p ~/.config/systemd/user
    cp systemd/walkingpad-mqtt.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now walkingpad-mqtt
    loginctl enable-linger $USER   # работа без логина

Логи: `journalctl --user -u walkingpad-mqtt -f`

## Home Assistant

Энтити (MQTT discovery, устройство "WalkingPad A1 Pro"):

- sensor: скорость, дистанция, шаги, время сессии, калории (расчётные), состояние
- binary_sensor: BLE связь
- button: старт, стоп
- number: целевая скорость (0.5–6 км/ч)

## Тесты

    .venv/bin/pytest
```

- [ ] **Step 4: Коммит**

```bash
git add config systemd README.md && git commit -m "docs: example config, systemd unit and README"
```

---

### Task 12: Ручная верификация на дорожке (обязательная)

Только с физической дорожкой; пользователь — участник. BLE-хост: ноутбук рядом с дорожкой.

- [ ] **Step 1: Обнаружение и конфиг**

```bash
.venv/bin/walkingpad-mqtt --discover
```

Ожидание: MAC вида `57:4C:...`, имя `WalkingPad...` или сервис 0xFE00. Вписать в `~/.config/walkingpad/config.toml` вместе с адресом брокера (у пользователя брокер уже есть — уточнить хост/креды).

- [ ] **Step 2: Прогон foreground с debug**

```bash
.venv/bin/walkingpad-mqtt -v
```

Ожидание: `BLE ... connected` в логах; в HA появились энтити устройства WalkingPad A1 Pro; `mosquitto_sub -t 'walkingpad/#' -v` показывает state-JSON ~1/с при движении ремня. Зафиксировать реальные значения `belt_state` при: standby, idle, разгон, ходьба, торможение. Если маппинг `BELT_STATE_LABELS` не совпал — поправить словарь в `sessions.py`, обновить тест, закоммитить (`fix: correct belt state labels for observed firmware`).

- [ ] **Step 3: Управление**

Через HA (кнопки/слайдер) или напрямую:

```bash
mosquitto_pub -t walkingpad/command -m '{"cmd":"start"}'
mosquitto_pub -t walkingpad/command -m '{"cmd":"stop"}'
mosquitto_pub -t walkingpad/speed/set -m '4.0'
```

Ожидание: ремень реагирует; скорость меняется; slider в HA отражает текущую скорость; быстрые последовательные смены скорости не «зависают» (debounce).

- [ ] **Step 4: Разрыв и восстановление**

1. При ходьбе выключить дорожку из розетки → сервис ушёл в reconnect (лог), сенсоры `unavailable`.
2. Включить дорожку → сервис переподключился; если ходьба была активна — в `walkingpad/session` появилась восстановленная статистика (или минимум — телеметрия возобновилась).
3. Проверить `walkingpad/availability` = online, LWT работает (restat сервиса → offline → online).

- [ ] **Step 5: Сосуществование с A2DP**

Включить Bluetooth-музыку на ноутбуке, повторить Step 3. Заиканий аудио быть не должно (при артефактах — задокументировать, вариант лечения: USB-донгл + `ble.adapter`).

- [ ] **Step 6: Финал**

```bash
.venv/bin/pytest
```

Все тесты зелёные. Установить systemd-юнит (Task 11 README), убедиться в автозапуске. Итоговый коммит при правках.

---

## Самопроверка плана (выполнено автором)

1. **Покрытие спеки:** BLE-клиент (Task 9), детектор сессий (Task 5), MQTT/discovery/LWT (Task 7–8), калории (Task 3), команды (Task 4), конфиг (Task 2), main/systemd/README (Task 10–11), last-status восстановление (Task 9 + 10), ручные проверки (Task 12). Единственное отклонение от спеки: границы слайдера берутся из конфига `[pad]`, а не читаются с дорожки (библиотека не даёт чистого API чтения преференций; спека допускала fallback 0.5–6.0).
2. **Плейсхолдеры:** нет; в Task 8 есть примечание об исправлении импорта `Session` — код в финальном файле должен использовать `from .sessions import Session`.
3. **Консистентность типов:** `Command(action, speed_kmh)`, `StatusSample(...)`, `Session(started_at, ended_at, distance_km, steps, duration_s)`, `PadClient(cfg, on_status, on_last_status, on_connected, on_disconnected, ...)`, `MqttLayer(cfg, on_command)` — сигнатуры в тестах и реализации совпадают.
