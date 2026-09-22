from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import logging
import signal
import time
from pathlib import Path

from .calories import estimate_kcal
from .commands import Command
from .config import DEFAULT_CONFIG_PATH, AppConfig, ConfigError, load_config
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
        if not self.ble_connected:
            log.warning("Command %r dropped: BLE not connected", cmd)
            return
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
            wall_end = time.time() - (time.monotonic() - closed.ended_at)
            wall_start = wall_end - (closed.ended_at - closed.started_at)
            self.mqtt.publish_session_nowait(dataclasses.replace(closed, started_at=wall_start, ended_at=wall_end))
        self.mqtt.publish_state_nowait(sample, self.session_kcal, self.ble_connected)

    def _on_last_status(self, dist_km: float, time_s: int, steps: int) -> None:
        # Дорожка отдала финальную статистику последней сессии (обычно после переподключения)
        if dist_km <= 0 and steps <= 0 and time_s <= 0:
            log.debug("Empty last status ignored")
            return
        now = time.time()
        recovered = Session(started_at=now - time_s, ended_at=now, distance_km=dist_km, steps=steps, duration_s=time_s)
        log.info("Recovered last session stats: dist=%.2f km, steps=%d, %d s", dist_km, steps, time_s)
        self.mqtt.publish_session_nowait(recovered)

    def _on_ble_connected(self) -> None:
        self.ble_connected = True
        self.mqtt.publish_state_nowait(self.latest, self.session_kcal, True)

    def _on_ble_disconnected(self) -> None:
        self.ble_connected = False
        self.mqtt.publish_state_nowait(None, 0.0, False)

    async def run(self) -> None:
        tasks = [asyncio.create_task(self.mqtt.run()), asyncio.create_task(self.pad.run())]
        loop = asyncio.get_running_loop()
        main_task = asyncio.current_task()

        def _stop() -> None:
            log.info("Shutdown signal received")
            if main_task is not None:
                main_task.cancel()

        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, _stop)
        try:
            await asyncio.wait(tasks)
        except asyncio.CancelledError:
            pass
        finally:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.mqtt.publish_offline(), timeout=3.0)
                await asyncio.sleep(0.5)
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
            print(f"  MAC: {dev.address}")
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

    try:
        cfg = load_config(Path(args.config))
    except ConfigError as e:
        log.error("Конфигурация некорректна: %s", e)
        return 2
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
