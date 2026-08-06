import pytest

from icpc_verify import verdicts
from icpc_verify.results import (
    RunMeasurement,
    TestCaseResult,
    classify_run,
    matches_expectation,
    solution_verdict,
)
from icpc_verify.timelimits import make_time_limits

LIMITS = make_time_limits(1.0, "2s|20%")


def measure(**kwargs):
    base = dict(
        wall=0.1,
        cpu=0.1,
        max_rss_kib=1000,
        exit_code=0,
        signal=0,
        timed_out=False,
        output_limit_exceeded=False,
        oom_killed=False,
    )
    base.update(kwargs)
    return RunMeasurement(**base)


def test_accepted():
    assert classify_run(measure(), LIMITS, True, "")[0] == verdicts.ACCEPTED


def test_wrong_answer():
    verdict, message = classify_run(measure(), LIMITS, False, "token 1 이 다릅니다")
    assert verdict == verdicts.WRONG_ANSWER
    assert "token 1" in message


def test_wall_over_limit_is_tle_even_when_output_is_correct():
    assert classify_run(measure(wall=1.05), LIMITS, True, "")[0] == verdicts.TIME_LIMIT_EXCEEDED


def test_wall_exactly_at_limit_passes():
    assert classify_run(measure(wall=1.0), LIMITS, True, "")[0] == verdicts.ACCEPTED


def test_hard_kill_is_tle():
    assert classify_run(measure(wall=3.0, timed_out=True), LIMITS, False, "")[0] == (
        verdicts.TIME_LIMIT_EXCEEDED
    )


def test_oom_is_run_time_error():
    verdict, message = classify_run(measure(oom_killed=True, exit_code=137), LIMITS, False, "")
    assert verdict == verdicts.RUN_TIME_ERROR
    assert "메모리" in message


def test_signal_is_run_time_error():
    verdict, message = classify_run(measure(signal=11, exit_code=-1), LIMITS, False, "")
    assert verdict == verdicts.RUN_TIME_ERROR
    assert "11" in message


def test_nonzero_exit_is_run_time_error():
    assert classify_run(measure(exit_code=1), LIMITS, False, "")[0] == verdicts.RUN_TIME_ERROR


def test_output_limit_is_wrong_answer():
    verdict, message = classify_run(measure(output_limit_exceeded=True), LIMITS, False, "")
    assert verdict == verdicts.WRONG_ANSWER
    assert "OLE" in message


def test_output_limit_beats_run_time_error():
    """runner 는 출력 제한 초과 시 SIGKILL 로 죽이므로 signal=9 가 항상 함께 온다.
    그래도 OLE 가 wrong_answer 로 보고돼야 한다 (run_time_error 로 뒤덮이면 안 된다)."""
    verdict, message = classify_run(
        measure(output_limit_exceeded=True, signal=9, exit_code=-1), LIMITS, False, ""
    )
    assert verdict == verdicts.WRONG_ANSWER
    assert "OLE" in message


def test_tle_beats_run_time_error():
    verdict, _ = classify_run(measure(wall=2.0, timed_out=True, signal=9), LIMITS, False, "")
    assert verdict == verdicts.TIME_LIMIT_EXCEEDED


def test_hard_kill_tle_beats_output_limit():
    """hard-kill 도 SIGKILL 이라 output_limit_exceeded 가 함께 True 일 수 있다.
    이때는 시간 초과가 먼저이므로 여전히 TLE 여야 한다."""
    verdict, _ = classify_run(
        measure(wall=3.0, timed_out=True, signal=9, output_limit_exceeded=True),
        LIMITS,
        False,
        "",
    )
    assert verdict == verdicts.TIME_LIMIT_EXCEEDED


def case(verdict):
    return TestCaseResult(
        id="01",
        group="",
        verdict=verdict,
        wall=0.1,
        cpu=0.1,
        mem_kib=100,
        exit_code=0,
        message="",
    )


def test_solution_verdict_all_accepted():
    assert solution_verdict([case(verdicts.ACCEPTED)] * 3) == verdicts.ACCEPTED


def test_solution_verdict_first_failure_wins():
    cases = [case(verdicts.ACCEPTED), case(verdicts.RUN_TIME_ERROR), case(verdicts.WRONG_ANSWER)]
    assert solution_verdict(cases) == verdicts.RUN_TIME_ERROR


def test_solution_verdict_ignores_not_run():
    cases = [case(verdicts.ACCEPTED), case(verdicts.NOT_RUN)]
    assert solution_verdict(cases) == verdicts.ACCEPTED


def test_solution_verdict_empty():
    assert solution_verdict([]) == verdicts.JUDGE_ERROR


@pytest.mark.parametrize(
    ("expected", "actual", "mode", "result"),
    [
        ("accepted", "accepted", "exact", True),
        ("wrong_answer", "wrong_answer", "exact", True),
        ("wrong_answer", "run_time_error", "exact", False),
        ("wrong_answer", "run_time_error", "any-rejected", True),
        ("accepted", "wrong_answer", "any-rejected", False),
        ("time_limit_exceeded", "accepted", "any-rejected", False),
    ],
)
def test_matches_expectation(expected, actual, mode, result):
    assert matches_expectation(expected, actual, mode) is result
