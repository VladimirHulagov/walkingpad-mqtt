import asyncio
import time as _time

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
    app.ble_connected = True
    submitted = []
    app.pad.submit = submitted.append
    from walkingpad_mqtt.commands import Command

    app._on_command(Command("stop"))
    assert submitted == [Command("stop")]


def test_command_dropped_when_ble_down():
    app = App(make_cfg())
    submitted = []
    app.pad.submit = submitted.append
    from walkingpad_mqtt.commands import Command

    app._on_command(Command("stop"))
    assert submitted == []


def test_empty_last_status_ignored():
    app = App(make_cfg())
    sessions = []
    app.mqtt.publish_session_nowait = sessions.append
    app._on_last_status(0.0, 0, 0)
    assert sessions == []


def test_last_status_recovers_session():
    app = App(make_cfg())
    sessions = []
    app.mqtt.publish_session_nowait = sessions.append
    app._on_last_status(3.3, 1800, 3500)
    assert len(sessions) == 1
    assert sessions[0].distance_km == 3.3
    assert sessions[0].steps == 3500
    assert sessions[0].duration_s == 1800


def test_closed_session_published_with_wall_clock():
    # ts сэмплов должны быть реальными monotonic-значениями: детектор и конвертация
    # monotonic -> wall-clock в _on_status опираются на них.
    app = App(make_cfg())
    sessions = []
    app.mqtt.publish_session_nowait = sessions.append
    m0 = _time.monotonic()
    app._on_status(sample(speed_kmh=3.0, distance_km=0.1, steps=50, time_s=30, ts=m0 - 13.0))
    for dt in (3.0, 2.0, 1.0):
        app._on_status(sample(speed_kmh=0.0, distance_km=0.1, steps=50, time_s=30, ts=m0 - dt))
    before = _time.time()
    _time.sleep(0.01)  # гарантированный запас: wall-читка до mono-читки закрывающего ts
    t_close = _time.monotonic()
    app._on_status(sample(speed_kmh=0.0, distance_km=0.1, steps=50, time_s=30, ts=t_close))
    after = _time.time()
    assert len(sessions) == 1
    s = sessions[0]
    assert before <= s.ended_at <= after
    assert s.duration_s == 30  # длительность — из duration_s, не из timestamps
    mono_span = t_close - (m0 - 13.0)  # end_mono - start_mono
    assert abs((s.ended_at - s.started_at) - mono_span) < 0.1  # wall_start = wall_end - span, не +


async def test_run_cancels_children_and_publishes_offline(monkeypatch):
    app = App(make_cfg())
    state = {"cancelled": 0, "offline": 0}

    async def fake_mqtt_run():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            state["cancelled"] += 1
            raise

    async def fake_pad_run():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            state["cancelled"] += 1
            raise

    async def fake_publish_offline():
        state["offline"] += 1

    monkeypatch.setattr(app.mqtt, "run", fake_mqtt_run)
    monkeypatch.setattr(app.pad, "run", fake_pad_run)
    monkeypatch.setattr(app.mqtt, "publish_offline", fake_publish_offline)
    monkeypatch.setattr(app.mqtt, "publish_state_nowait", lambda *a: None)
    monkeypatch.setattr(app.mqtt, "publish_session_nowait", lambda s: None)

    task = asyncio.create_task(app.run())
    await asyncio.sleep(0.05)
    task.cancel()
    await task  # run() поглощает CancelledError и чисто завершается
    assert state["cancelled"] == 2
    assert state["offline"] == 1
