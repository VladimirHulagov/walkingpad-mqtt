from __future__ import annotations

import asyncio
import json
import logging

import aiomqtt

from .commands import Command, parse_command, parse_speed_set
from .config import AppConfig
from .mqtt_payloads import build_session_payload, build_state, discovery_configs
from .sessions import Session

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
            ok = False
            try:
                async with self._connect() as client:
                    self._client = client
                    log.info("MQTT connected to %s:%s", self.cfg.mqtt.host, self.cfg.mqtt.port)
                    await self._on_connect(client)
                    ok = True
                    async for message in client.messages:
                        self._dispatch(message)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("MQTT connection ended: %r", e)
            finally:
                self._client = None
                if ok:
                    backoff = self.reconnect_min_s
            log.info("MQTT reconnect in %.0f s", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.reconnect_max_s)

    def _connect(self) -> aiomqtt.Client:
        m = self.cfg.mqtt
        kwargs: dict = {}
        if m.tls:
            kwargs["tls_params"] = aiomqtt.TLSParameters()
        return aiomqtt.Client(
            hostname=m.host,
            port=m.port,
            username=m.username,
            password=m.password,
            will=aiomqtt.Will(topic=f"{m.prefix}/availability", payload=b"offline", retain=True),
            **kwargs,
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
            try:
                self.on_command(cmd)
            except Exception:
                log.warning("on_command callback failed", exc_info=True)

    def publish_state_nowait(self, sample, calories: float, connected: bool) -> None:
        payload = json.dumps(build_state(sample, calories, connected), ensure_ascii=False).encode()
        self._publish_nowait(f"{self.cfg.mqtt.prefix}/state", payload, retain=True)

    async def publish_offline(self) -> None:
        client = self._client
        if client is None:
            return
        await client.publish(f"{self.cfg.mqtt.prefix}/availability", b"offline", retain=True)

    def publish_session_nowait(self, session: Session) -> None:
        self._publish_nowait(f"{self.cfg.mqtt.prefix}/session", build_session_payload(session).encode(), retain=True)

    def _publish_nowait(self, topic: str, payload: bytes, retain: bool = False) -> None:
        client = self._client
        if client is None:
            return

        async def _pub() -> None:
            try:
                await client.publish(topic, payload, retain=retain)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("MQTT publish to %s failed", topic, exc_info=True)

        try:
            self._bg.append(asyncio.get_running_loop().create_task(_pub()))
            self._bg = [t for t in self._bg if not t.done()]
        except RuntimeError:
            log.debug("publish outside event loop skipped")
