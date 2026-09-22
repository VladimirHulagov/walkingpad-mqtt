from ph4_walkingpad.pad import WalkingPadCurStatus, WalkingPadLastStatus

# Реальный фрейм статуса A1 Pro (из реверс-инжиниринга ph4-walkingpad):
# скорость 1.5 км/ч, время 4049 с, дистанция 1.71 км, 4782 шага, ручной режим
REAL_CUR_STATUS = bytes(
    [248, 162, 1, 15, 1, 0, 15, 209, 0, 0, 171, 0, 18, 174, 60, 0, 0, 58, 253]
)


def test_cur_status_fields():
    st = WalkingPadCurStatus.from_data(REAL_CUR_STATUS)
    assert st.speed == 15          # ×10 → 1.5 км/ч
    assert st.dist == 171          # ×10 м → 1.71 км
    assert st.steps == 4782
    assert st.time == 4049
    assert st.belt_state == 1
    assert st.manual_mode == 1
    assert st.app_speed == 60


def test_message_type_detection():
    assert WalkingPadCurStatus.check_type(REAL_CUR_STATUS)
    assert not WalkingPadLastStatus.check_type(REAL_CUR_STATUS)


def test_speed_units_are_tenths_of_kmh():
    st = WalkingPadCurStatus.from_data(REAL_CUR_STATUS)
    assert st.speed / 10.0 == 1.5
    assert st.dist / 100.0 == 1.71


# Синтетический last-status фрейм (F8 A7, формат ph4-walkingpad):
# time=0|0|60=60 с, dist=0|0|125=1.25 км, steps=0|1|44=300
SYNTH_LAST_STATUS = bytes(
    [248, 167, 0, 0, 0, 0, 0, 0, 0, 0, 60, 0, 0, 125, 0, 1, 44, 0, 253]
)


def test_last_status_parses():
    st = WalkingPadLastStatus.from_data(SYNTH_LAST_STATUS)
    assert WalkingPadLastStatus.check_type(SYNTH_LAST_STATUS)
    assert st.time == 60
    assert st.dist == 125
    assert st.steps == 300
