from __future__ import annotations

import time
from dataclasses import dataclass, field

RUNNING_SPEED_THRESHOLD_KMH = 0.05
HYSTERESIS_S = 3.0

# Отображение belt_state WiLink. Коды 0/1/5/9 подтверждены на реальной
# A1 Pro (0 = idle после свежего подключения, 9 = switching после
# switch_mode), остальные — из данных сообщества. Детектор сессий от него
# НЕ зависит (только скорость).
BELT_STATE_LABELS = {
    0: "idle",
    1: "running",
    2: "slowing",
    3: "running",
    4: "starting",
    5: "stopped",
    6: "standby",
    7: "standby",
    9: "switching",
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
    """Закрытая сессия. started_at — момент первого наблюдения (не фактического
    начала, если детектор подключился посреди ходьбы); длительность брать из
    duration_s, а не ended_at - started_at."""

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
