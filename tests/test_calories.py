import pytest

from walkingpad_mqtt.calories import estimate_kcal


def test_typical_walk():
    # 80 кг * 5 км * 1.03 = 412.0
    assert estimate_kcal(80.0, 5.0) == 412.0


def test_zero_distance():
    assert estimate_kcal(80.0, 0.0) == 0.0


def test_custom_coefficient():
    assert estimate_kcal(70.0, 2.0, coefficient=1.05) == 147.0


def test_negative_raises():
    with pytest.raises(ValueError):
        estimate_kcal(80.0, -1.0)
    with pytest.raises(ValueError):
        estimate_kcal(-5.0, 1.0)
