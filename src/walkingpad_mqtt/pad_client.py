from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess
from functools import partial
from typing import Callable

from .commands import Command
from .config import AppConfig
from .sessions import BELT_STATE_LABELS, StatusSample

log = logging.getLogger(__name__)

RECONNECT_MIN_S = 5.0
RECONNECT_MAX_S = 60.0
SPEED_DEBOUNCE_S = 0.3


def default_controller_factory(address: str, adapter: str = "hci0"):
    from bleak import BleakClient
    from ph4_walkingpad.pad import Controller

    class AdapterController(Controller):
        async def connect(self, address=None):
            address = address or self.address
            self.client = BleakClient(address, bluez={"adapter": adapter})
            return await self.client.connect(timeout=10.0)

    c = AdapterController(address, do_read_chars=False)
    c.log_messages_info = False
    return c


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
        self.controller_factory = controller_factory or partial(
            default_controller_factory, adapter=cfg.ble.adapter
        )
        self.reconnect_min_s = reconnect_min_s
        self.reconnect_max_s = reconnect_max_s
        self._queue: asyncio.Queue[Command] = asyncio.Queue()

    def submit(self, cmd: Command) -> None:
        self._queue.put_nowait(cmd)

    def _heal_stale_bluez(self) -> None:
        try:
            r = subprocess.run(
                ["bluetoothctl", "disconnect", self.cfg.ble.mac],
                capture_output=True,
                timeout=5,
            )
            log.info("BlueZ stale-link heal ran (rc=%s)", r.returncode)
        except FileNotFoundError:
            log.debug("bluetoothctl not available, skip heal")
        except Exception as e:
            log.debug("BlueZ heal failed: %r", e)

    async def run(self) -> None:
        """Reconnect-цикл. on_disconnected вызывается при завершении ПОПЫТКИ
        сессии (в т.ч. если подключение не состоялось) — колбэк должен быть
        идемпотентным."""
        backoff = self.reconnect_min_s
        failures = 0
        while True:
            try:
                await self._session()
                backoff = self.reconnect_min_s
                failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("BLE session ended: %r", e)
                failures += 1
                if failures % 3 == 0:
                    self._heal_stale_bluez()
            self._safe(self.on_disconnected)
            log.info("BLE reconnect in %.0f s", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.reconnect_max_s)

    async def _session(self) -> None:
        controller = self.controller_factory(self.cfg.ble.mac)
        controller.handler_cur_status = self._handle_cur_status
        controller.handler_last_status = self._handle_last_status
        try:
            await controller.run()
            self._safe(self.on_connected)
            try:
                await asyncio.wait_for(controller.ask_hist(), timeout=5.0)
            except Exception as e:
                log.debug("ask_hist on connect failed: %r", e)
            # Как приложение KingSmith: активировать ручной режим после
            # подключения, иначе дорожка отвечает на start/speed только писком.
            # 1 = MODE_MANUAL (литерал — без импорта ph4_walkingpad).
            try:
                await asyncio.wait_for(controller.switch_mode(1), timeout=5.0)
            except Exception as e:
                log.debug("switch_mode(manual) on connect failed: %r", e)
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

    # Не-speed команды, пришедшие в окне debounce, выполнятся ПОСЛЕ коллапса
    # скоростей (инверсия порядка в редком окне ~1 с; безопасное направление —
    # stop задерживается, не теряется).
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
