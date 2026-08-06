from pathlib import Path

import pytest

from icpc_verify import verdicts
from icpc_verify.judge import JudgeOptions, judge_solution
from icpc_verify.problemcfg import load_problem_config
from icpc_verify.solutions import discover_solutions
from icpc_verify.testdata import collect_testcases
from icpc_verify.timelimits import make_time_limits

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
IMAGE = (ROOT / "image" / "IMAGE_DIGEST").read_text().strip()
FIXTURE = ROOT / "tests" / "fixtures" / "interactive"


def judge(tmp_path, rel_path):
    config = load_problem_config(FIXTURE, default_time_limit=1.0, default_memory_mib=2048)
    limits = make_time_limits(config.time_limit, "2s|20%")
    cases = collect_testcases(FIXTURE)
    sols, _ = discover_solutions(FIXTURE)
    solution = next(s for s in sols if s.rel_path == rel_path)
    options = JudgeOptions(image=IMAGE, cpuset=0, memory_mib=config.memory_mib)
    return judge_solution(FIXTURE, config, solution, cases, limits, tmp_path, options)


@pytest.mark.parametrize(
    ("rel_path", "expected"),
    [
        ("accepted/main.cpp", verdicts.ACCEPTED),
        ("wrong_answer/gives_up.py", verdicts.WRONG_ANSWER),
        ("time_limit_exceeded/sleepy.py", verdicts.TIME_LIMIT_EXCEEDED),
        ("run_time_error/crash.c", verdicts.RUN_TIME_ERROR),
    ],
)
def test_interactive_verdicts(tmp_path, rel_path, expected):
    result = judge(tmp_path, rel_path)
    assert result.verdict == expected, result.testcases[0].message


def test_judgemessage_reaches_result(tmp_path):
    result = judge(tmp_path, "wrong_answer/gives_up.py")
    assert "gave up" in result.testcases[0].message


def test_runtime_is_solution_only(tmp_path):
    result = judge(tmp_path, "accepted/main.cpp")
    first = result.testcases[0]
    assert 0 < first.wall <= 1.0
