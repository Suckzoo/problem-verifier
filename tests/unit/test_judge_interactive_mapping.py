import signal

from icpc_verify import verdicts
from icpc_verify.judge import _classify_interactive
from icpc_verify.timelimits import make_time_limits

LIMITS = make_time_limits(1.0, "2s|20%")


def raw(**kwargs):
    base = {
        "solution": {
            "wall": 0.1,
            "cpu": 0.1,
            "max_rss_kib": 1000,
            "exit_code": 0,
            "signal": 0,
            "timed_out": False,
        },
        "validator_exit": 42,
        "validator_signal": 0,
        "pair_timed_out": False,
    }
    sol = kwargs.pop("solution", {})
    base["solution"].update(sol)
    base.update(kwargs)
    return base


def test_clean_accept():
    assert _classify_interactive(raw(), LIMITS, 512)[0] == verdicts.ACCEPTED


def test_validator_43_is_wrong_answer():
    assert _classify_interactive(raw(validator_exit=43), LIMITS, 512)[0] == verdicts.WRONG_ANSWER


def test_tle_beats_validator_verdict():
    r = raw(solution={"wall": 1.5}, validator_exit=43)
    assert _classify_interactive(r, LIMITS, 512)[0] == verdicts.TIME_LIMIT_EXCEEDED


def test_pair_timeout_is_tle():
    r = raw(pair_timed_out=True)
    assert _classify_interactive(r, LIMITS, 512)[0] == verdicts.TIME_LIMIT_EXCEEDED


def test_rss_over_limit_is_rte():
    r = raw(solution={"max_rss_kib": 600 * 1024})
    verdict, message = _classify_interactive(r, LIMITS, 512)
    assert verdict == verdicts.RUN_TIME_ERROR
    assert "메모리" in message


def test_crash_beats_validator_43():
    r = raw(solution={"signal": signal.SIGSEGV, "exit_code": -1}, validator_exit=43)
    assert _classify_interactive(r, LIMITS, 512)[0] == verdicts.RUN_TIME_ERROR


def test_sigpipe_is_forgiven():
    r = raw(solution={"signal": signal.SIGPIPE, "exit_code": -1}, validator_exit=43)
    assert _classify_interactive(r, LIMITS, 512)[0] == verdicts.WRONG_ANSWER


def test_nonzero_exit_is_rte():
    r = raw(solution={"exit_code": 3})
    assert _classify_interactive(r, LIMITS, 512)[0] == verdicts.RUN_TIME_ERROR


def test_validator_error_exit_is_judge_error():
    r = raw(validator_exit=1)
    assert _classify_interactive(r, LIMITS, 512)[0] == verdicts.JUDGE_ERROR
