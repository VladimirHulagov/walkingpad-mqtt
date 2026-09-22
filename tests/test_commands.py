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


def test_non_finite_rejected():
    assert parse_command(b'{"cmd":"speed","value":NaN}') is None
    assert parse_command(b'{"cmd":"speed","value":Infinity}') is None
    assert parse_command(b'{"cmd":"speed","value":1' + b"0" * 400 + b"}") is None
    assert parse_speed_set(b"nan") is None
    assert parse_speed_set(b"inf") is None
    assert parse_speed_set(b"-inf") is None


def test_clip_speed_rounding():
    assert clip_speed(4.26, 0.5, 6.0) == 4.3
    assert clip_speed(4.24, 0.5, 6.0) == 4.2
