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


def test_pair_timeout_with_slow_solution_is_tle():
    r = raw(pair_timed_out=True, solution={"wall": 1.5})
    verdict, message = _classify_interactive(r, LIMITS, 512)
    assert verdict == verdicts.TIME_LIMIT_EXCEEDED
    assert "1.500" in message


def test_pair_timeout_with_healthy_solution_is_judge_error():
    # validator 가 pair timeout 까지 안 끝났지만 solution 은 제한 시간 안에 끝났다면
    # 잘못은 validator 에 있다 - solution 을 TLE 로 몰면 안 되고, "wall X 가 시간제한
    # Y 를 넘었다" 는 거짓 문장을 말해서도 안 된다 (X <= Y 인데 그렇게 말하면 거짓이다).
    r = raw(pair_timed_out=True)
    verdict, message = _classify_interactive(r, LIMITS, 512)
    assert verdict == verdicts.JUDGE_ERROR
    assert "시간제한" not in message or "넘었" not in message
    assert "validator" in message


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


def test_validator_error_exit_beats_solution_nonzero_exit():
    # validator 가 죽으면 그 pipe 의 EOF 때문에 solution 도 따라 비정상 종료하는 경우가
    # 흔하다 - solution 의 exit code 를 탓하지 말고 validator 를 탓해야 한다.
    r = raw(validator_exit=1, solution={"exit_code": 3})
    verdict, message = _classify_interactive(r, LIMITS, 512)
    assert verdict == verdicts.JUDGE_ERROR
    assert "validator exit code 1" in message


def test_validator_error_exit_beats_solution_crash():
    r = raw(validator_exit=1, solution={"signal": signal.SIGSEGV, "exit_code": -1})
    verdict, message = _classify_interactive(r, LIMITS, 512)
    assert verdict == verdicts.JUDGE_ERROR
    assert "validator exit code 1" in message
