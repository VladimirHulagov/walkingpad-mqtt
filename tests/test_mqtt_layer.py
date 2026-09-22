import asyncio
from contextlib import suppress
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


def test_connect_passes_tls_params_when_enabled(monkeypatch):
    import aiomqtt

    cfg = make_cfg()
    cfg.mqtt.tls = True
    captured = {}

    class RecordingClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("walkingpad_mqtt.mqtt_layer.aiomqtt.Client", RecordingClient)
    layer = MqttLayer(cfg)
    layer._connect()
    assert isinstance(captured["tls_params"], aiomqtt.TLSParameters)


def test_connect_no_tls_params_by_default(monkeypatch):
    cfg = make_cfg()
    captured = {}

    class RecordingClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("walkingpad_mqtt.mqtt_layer.aiomqtt.Client", RecordingClient)
    layer = MqttLayer(cfg)
    layer._connect()
    assert "tls_params" not in captured


class FakeClient:
    """Соединение: handshake успешен, затем обрыв (messages бросает ConnectionError)."""

    def __init__(self):
        self.published = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def messages(self):
        async def gen():
            raise ConnectionError("drop")
            yield  # pragma: no cover

        return gen()

    async def publish(self, topic, payload, retain=False):
        self.published.append(topic)

    async def subscribe(self, topic):
        pass


async def test_backoff_resets_after_successful_connection(monkeypatch):
    real_sleep = asyncio.sleep
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
        await real_sleep(0)  # уступаем управление, чтобы run() и тест чередовались

    monkeypatch.setattr("walkingpad_mqtt.mqtt_layer.asyncio.sleep", fake_sleep)

    layer = MqttLayer(make_cfg(), reconnect_min_s=0.01, reconnect_max_s=0.08)
    layer._connect = lambda: FakeClient()

    task = asyncio.create_task(layer.run())
    while len(sleeps) < 3:
        await real_sleep(0)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    # каждая сессия завершается УСПЕШНЫМ on_connect → каждый sleep = min
    assert sleeps == [0.01, 0.01, 0.01]
