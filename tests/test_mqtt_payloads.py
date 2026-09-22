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
    assert '"connected": true' in json.dumps(build_state(sample(), calories=123.5, connected=True))


def test_build_state_rounding():
    st = build_state(sample(speed_kmh=3.26, distance_km=1.234), calories=0.0, connected=True)
    assert st["speed"] == 3.3
    assert st["distance"] == 1.23


def test_build_state_without_sample():
    st = build_state(None, calories=0.0, connected=False)
    assert st == {"connected": False}
    assert '"connected": false' in json.dumps(build_state(None, calories=0.0, connected=False))


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
