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
    def __init__(self, fail_on_run=False, fail_stats_after=None, fail_switch_mode=False):
        self.fail_on_run = fail_on_run
        self.fail_stats_after = fail_stats_after
        self.fail_switch_mode = fail_switch_mode
        self.run_calls = 0
        self.disconnect_calls = 0
        self.stats_requests = 0
        self.hist_requests = 0
        self.written: list = []
        self.mode_switches: list = []
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
        if self.fail_stats_after is not None and self.stats_requests >= self.fail_stats_after:
            raise ConnectionError("ble dropped")

    async def ask_hist(self):
        self.hist_requests += 1

    async def start_belt(self):
        self.written.append("start")

    async def stop_belt(self):
        self.written.append("stop")

    async def change_speed(self, v):
        self.written.append(("speed", v))

    async def switch_mode(self, mode):
        self.mode_switches.append(mode)
        if self.fail_switch_mode:
            raise ConnectionError("switch rejected")


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


def test_handle_last_status_converts_units():
    from ph4_walkingpad.pad import WalkingPadLastStatus

    st = WalkingPadLastStatus.from_data(
        bytes([248, 167, 0, 0, 0, 0, 0, 0, 0, 0, 60, 0, 0, 125, 0, 1, 44, 0, 253])
    )
    got: list[tuple] = []
    client = PadClient(make_cfg(), on_status=lambda s: None,
                       on_last_status=lambda dist, time_s, steps: got.append((dist, time_s, steps)),
                       on_connected=lambda: None, on_disconnected=lambda: None)
    client._handle_last_status("sender", st)
    assert got == [(1.25, 60, 300)]


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
    # ok (обрыв BLE на 3-м опросе) → fail_on_run → ok
    made = [FakeController(fail_stats_after=3), FakeController(fail_on_run=True), FakeController()]
    n = 0

    def factory(addr):
        nonlocal n
        controller = made[n] if n < len(made) else FakeController()
        n += 1
        return controller

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
    assert made[-1].hist_requests >= 1  # ask_hist отправлен при подключении
    assert made[-1].mode_switches == [1]  # ручной режим активирован при подключении


async def test_switch_mode_failure_tolerated():
    # дорожка не переключила режим — сессия обязана жить (poll продолжается)
    fake = FakeController(fail_switch_mode=True)
    client = PadClient(
        make_cfg(),
        on_status=lambda s: None,
        on_last_status=lambda *a: None,
        on_connected=lambda: None,
        on_disconnected=lambda: None,
        controller_factory=lambda addr: fake,
        reconnect_min_s=0.05,
        reconnect_max_s=0.05,
    )
    task = asyncio.create_task(client.run())
    await asyncio.sleep(0.3)
    task.cancel()
    with contextlib_suppress():
        await task
    assert fake.mode_switches == [1]
    assert fake.stats_requests > 0  # сессия жива, опрос идёт


def test_default_controller_factory_uses_adapter():
    from walkingpad_mqtt.pad_client import default_controller_factory

    c = default_controller_factory("AA:BB:CC:DD:EE:FF", adapter="hci9")
    assert c.address == "AA:BB:CC:DD:EE:FF"


async def test_session_disconnects_when_run_fails():
    fake = FakeController(fail_on_run=True)
    events: list[str] = []
    client = PadClient(
        make_cfg(),
        on_status=lambda s: None,
        on_last_status=lambda *a: None,
        on_connected=lambda: events.append("connected"),
        on_disconnected=lambda: events.append("disconnected"),
        controller_factory=lambda addr: fake,
    )
    with pytest.raises(ConnectionError):
        await client._session()
    assert fake.disconnect_calls == 1
    assert events == []  # on_connected не вызывался


async def test_heals_stale_bluez_every_third_failure(monkeypatch):
    calls = []

    def factory(addr):
        return FakeController(fail_on_run=True)

    monkeypatch.setattr("walkingpad_mqtt.pad_client.subprocess.run", lambda *a, **k: None)
    client = PadClient(
        make_cfg(),
        on_status=lambda s: None,
        on_last_status=lambda *a: None,
        on_connected=lambda: None,
        on_disconnected=lambda: None,
        controller_factory=factory,
        reconnect_min_s=0.01,
        reconnect_max_s=0.01,
    )
    monkeypatch.setattr(client, "_heal_stale_bluez", lambda: calls.append("heal"))
    task = asyncio.create_task(client.run())
    await asyncio.sleep(0.3)
    task.cancel()
    with contextlib_suppress():
        await task
    assert len(calls) >= 1  # 3+ неудачи за 0.3 c при backoff 0.01 → минимум один heal
