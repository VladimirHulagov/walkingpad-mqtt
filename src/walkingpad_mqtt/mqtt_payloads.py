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
        sensor("calories", "WalkingPad калории", "mdi:fire", unit="kcal"),
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
