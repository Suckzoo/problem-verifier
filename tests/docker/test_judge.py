from pathlib import Path

import pytest

from icpc_verify import verdicts
from icpc_verify.judge import JudgeOptions, judge_solution, measure_machine_factor
from icpc_verify.problemcfg import load_problem_config
from icpc_verify.solutions import discover_solutions
from icpc_verify.testdata import collect_testcases
from icpc_verify.timelimits import make_time_limits

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
IMAGE = (ROOT / "image" / "IMAGE_DIGEST").read_text().strip()
FIXTURE = ROOT / "tests" / "fixtures" / "plain"


def options(**kwargs):
    base = dict(
        image=IMAGE,
        cpuset=0,
        judge_all=False,
        output_limit_mib=8,
        compile_flags={},
        machine_factor=1.0,
        cpu_isolated=False,
        warnings=[],
    )
    base.update(kwargs)
    return JudgeOptions(**base)


def judge(tmp_path, rel_path, **kwargs):
    config = load_problem_config(FIXTURE, default_time_limit=1.0, default_memory_mib=2048)
    limits = make_time_limits(config.time_limit, "2s|20%")
    cases = collect_testcases(FIXTURE)
    sols, _ = discover_solutions(FIXTURE)
    solution = next(s for s in sols if s.rel_path == rel_path)
    return judge_solution(FIXTURE, config, solution, cases, limits, tmp_path, options(**kwargs))


@pytest.mark.parametrize(
    ("rel_path", "expected"),
    [
        ("accepted/main.cpp", verdicts.ACCEPTED),
        ("accepted/alt.py", verdicts.ACCEPTED),
        ("wrong_answer/off_by_one.cpp", verdicts.WRONG_ANSWER),
        ("time_limit_exceeded/sleepy.cpp", verdicts.TIME_LIMIT_EXCEEDED),
        ("run_time_error/crash.c", verdicts.RUN_TIME_ERROR),
    ],
)
def test_verdicts_match_directories(tmp_path, rel_path, expected):
    result = judge(tmp_path, rel_path)
    assert result.verdict == expected
    assert result.expected == rel_path.split("/")[0]


def test_accepted_runs_every_testcase(tmp_path):
    result = judge(tmp_path, "accepted/main.cpp")
    assert [c.verdict for c in result.testcases] == [verdicts.ACCEPTED] * 2


def test_lazy_judging_marks_remaining_as_not_run(tmp_path):
    result = judge(tmp_path, "wrong_answer/off_by_one.cpp")
    assert result.testcases[0].verdict == verdicts.WRONG_ANSWER
    assert result.testcases[1].verdict == verdicts.NOT_RUN


def test_judge_all_runs_everything(tmp_path):
    result = judge(tmp_path, "wrong_answer/off_by_one.cpp", judge_all=True)
    assert all(c.verdict == verdicts.WRONG_ANSWER for c in result.testcases)


def test_runtime_is_recorded(tmp_path):
    result = judge(tmp_path, "accepted/main.cpp")
    assert all(c.wall > 0 for c in result.testcases)
    assert all(c.mem_kib > 0 for c in result.testcases)


def test_tle_is_not_killed_before_hard_limit(tmp_path):
    result = judge(tmp_path, "time_limit_exceeded/sleepy.cpp")
    first = result.testcases[0]
    assert first.wall >= 1.0
    assert first.wall <= 4.0


def test_machine_factor_is_positive():
    assert measure_machine_factor(IMAGE, 0) > 0
