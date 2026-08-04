import pytest

from icpc_verify.timelimits import OvershootSpecError, make_time_limits


def test_seconds_only():
    t = make_time_limits(1.0, "2s")
    assert t.limit == 1.0
    assert t.overshoot == 2.0
    assert t.hard_kill == 3.0


def test_percent_only():
    t = make_time_limits(5.0, "20%")
    assert t.overshoot == pytest.approx(1.0)
    assert t.hard_kill == pytest.approx(6.0)


def test_pipe_takes_maximum():
    assert make_time_limits(1.0, "2s|20%").overshoot == pytest.approx(2.0)
    assert make_time_limits(20.0, "2s|20%").overshoot == pytest.approx(4.0)


def test_ampersand_takes_minimum():
    assert make_time_limits(1.0, "2s&20%").overshoot == pytest.approx(0.2)
    assert make_time_limits(20.0, "2s&20%").overshoot == pytest.approx(2.0)


def test_whitespace_is_tolerated():
    assert make_time_limits(1.0, " 2s | 20% ").overshoot == pytest.approx(2.0)


@pytest.mark.parametrize("spec", ["", "2", "abc", "2s|", "|20%", "2s|20%|1s", "-2s"])
def test_invalid_spec_raises(spec):
    with pytest.raises(OvershootSpecError):
        make_time_limits(1.0, spec)


def test_non_positive_limit_raises():
    with pytest.raises(OvershootSpecError):
        make_time_limits(0.0, "2s")
