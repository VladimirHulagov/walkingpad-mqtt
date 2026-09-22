from walkingpad_mqtt.sessions import SessionDetector, StatusSample


def mk(ts, speed=0.0, dist=0.0, steps=0, t=0):
    return StatusSample(speed_kmh=speed, distance_km=dist, steps=steps, time_s=t, ts=ts)


def test_idle_samples_no_session():
    d = SessionDetector()
    assert d.feed(mk(0)) is None
    assert d.feed(mk(1)) is None
    assert d.session is None


def test_session_opens_on_movement():
    d = SessionDetector()
    assert d.feed(mk(0, speed=3.0, dist=0.0, steps=0, t=0)) is None  # открытие — не закрытие
    assert d.session is not None
    assert d.feed(mk(1, speed=3.0, dist=0.001, steps=1, t=1)) is None
    assert d.session.distance_km == 0.001


def test_session_closes_after_hysteresis():
    d = SessionDetector(hysteresis_s=3.0)
    d.feed(mk(0, speed=3.0, dist=0.0, steps=0, t=0))
    d.feed(mk(1, speed=3.0, dist=0.01, steps=10, t=5))
    assert d.feed(mk(2, speed=0.0, dist=0.01, steps=10, t=6)) is None  # первый ноль
    assert d.feed(mk(3, speed=0.0, dist=0.01, steps=10, t=7)) is None  # 1 с нуля
    closed = d.feed(mk(10, speed=0.0, dist=0.01, steps=10, t=7))      # 8 с нуля
    assert closed is not None
    assert closed.distance_km == 0.01
    assert closed.steps == 10
    assert closed.duration_s == 7
    assert closed.ended_at == 10
    assert d.session is None


def test_blip_does_not_close():
    d = SessionDetector(hysteresis_s=3.0)
    d.feed(mk(0, speed=3.0))
    assert d.feed(mk(1, speed=0.0)) is None
    assert d.feed(mk(2, speed=3.0)) is None  # снова движение — таймер нуля сброшен
    assert d.feed(mk(3, speed=0.0)) is None
    assert d.feed(mk(4, speed=0.0)) is None  # всего 2 с нуля
    assert d.session is not None


def test_counter_reset_closes_and_reopens():
    d = SessionDetector(hysteresis_s=3.0)
    d.feed(mk(0, speed=3.0, dist=0.5, steps=100, t=300))
    d.feed(mk(1, speed=0.0, dist=0.5, steps=100, t=300))
    # сессия ещё не закрыта (гистерезис), но дорожка сбросила счётчики и снова идёт
    closed = d.feed(mk(2, speed=3.0, dist=0.0, steps=0, t=0))
    assert closed is not None
    assert closed.distance_km == 0.5
    assert closed.steps == 100
    assert d.session is not None  # новая сессия уже открыта


def test_reset_while_idle_closes_without_reopen():
    d = SessionDetector(hysteresis_s=3.0)
    d.feed(mk(0, speed=3.0, dist=0.5, steps=100, t=300))
    d.feed(mk(1, speed=0.0, dist=0.5, steps=100, t=300))
    closed = d.feed(mk(2, speed=0.0, dist=0.0, steps=0, t=0))
    assert closed is not None
    assert closed.distance_km == 0.5
    assert closed.steps == 100
    assert d.session is None  # пустая сессия НЕ открыта
    # следующее движение открывает нормальную сессию
    assert d.feed(mk(3, speed=3.0, dist=0.0, steps=0, t=0)) is None
    assert d.session is not None


def test_max_values_tracked():
    d = SessionDetector()
    d.feed(mk(0, speed=3.0, dist=0.1, steps=10, t=60))
    d.feed(mk(1, speed=3.0, dist=0.2, steps=25, t=120))
    d.feed(mk(2, speed=0.0, dist=0.2, steps=25, t=120))
    closed = d.feed(mk(10, speed=0.0, dist=0.2, steps=25, t=120))
    assert closed.distance_km == 0.2
    assert closed.steps == 25
    assert closed.duration_s == 120


def test_force_close():
    d = SessionDetector()
    d.feed(mk(0, speed=3.0, dist=1.0, steps=500, t=600))
    closed = d.force_close(ts=42.0)
    assert closed is not None
    assert closed.ended_at == 42.0
    assert d.force_close(ts=43.0) is None  # второй вызов — нечего закрывать


def test_belt_state_labels_cover_observed_codes():
    from walkingpad_mqtt.sessions import BELT_STATE_LABELS

    assert BELT_STATE_LABELS[0] == "idle"
    assert BELT_STATE_LABELS[1] == "running"
    assert BELT_STATE_LABELS[5] == "stopped"
    assert BELT_STATE_LABELS[9] == "switching"
