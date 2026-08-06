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
FIXTURE = ROOT / "tests" / "fixtures" / "custom"


def judge(tmp_path, rel_path, **kwargs):
    config = load_problem_config(FIXTURE, default_time_limit=1.0, default_memory_mib=2048)
    limits = make_time_limits(config.time_limit, "2s|20%")
    cases = collect_testcases(FIXTURE)
    sols, _ = discover_solutions(FIXTURE)
    solution = next(s for s in sols if s.rel_path == rel_path)
    options = JudgeOptions(image=IMAGE, cpuset=0, memory_mib=config.memory_mib, **kwargs)
    return judge_solution(FIXTURE, config, solution, cases, limits, tmp_path, options)


def test_alternative_answer_is_accepted(tmp_path):
    result = judge(tmp_path, "accepted/main.cpp")
    assert result.verdict == verdicts.ACCEPTED
    assert [c.verdict for c in result.testcases] == [verdicts.ACCEPTED] * 2


def test_python_alternative_answer_is_accepted(tmp_path):
    result = judge(tmp_path, "accepted/alt.py")
    assert result.verdict == verdicts.ACCEPTED


def test_wrong_sum_is_rejected_with_judgemessage(tmp_path):
    result = judge(tmp_path, "wrong_answer/bad.cpp")
    assert result.verdict == verdicts.WRONG_ANSWER
    first = result.testcases[0]
    assert "!=" in first.message
    assert result.testcases[1].verdict == verdicts.NOT_RUN


def test_broken_validator_is_judge_error(tmp_path):
    import shutil

    problem = tmp_path / "problem"
    shutil.copytree(FIXTURE, problem)
    check = problem / "output_validators" / "check"
    shutil.rmtree(check)
    check.mkdir()
    (check / "run").write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")

    config = load_problem_config(problem, default_time_limit=1.0, default_memory_mib=2048)
    limits = make_time_limits(config.time_limit, "2s|20%")
    cases = collect_testcases(problem)
    sols, _ = discover_solutions(problem)
    solution = next(s for s in sols if s.rel_path == "accepted/main.cpp")
    options = JudgeOptions(image=IMAGE, cpuset=0, memory_mib=config.memory_mib)
    result = judge_solution(problem, config, solution, cases, limits, tmp_path / "w", options)
    assert result.verdict == verdicts.JUDGE_ERROR


def test_validator_build_failure_is_judge_error_without_running(tmp_path):
    import shutil

    problem = tmp_path / "problem"
    shutil.copytree(FIXTURE, problem)
    (problem / "output_validators" / "check" / "check.cpp").write_text("not c++", encoding="utf-8")

    config = load_problem_config(problem, default_time_limit=1.0, default_memory_mib=2048)
    limits = make_time_limits(config.time_limit, "2s|20%")
    cases = collect_testcases(problem)
    sols, _ = discover_solutions(problem)
    solution = next(s for s in sols if s.rel_path == "accepted/main.cpp")
    options = JudgeOptions(image=IMAGE, cpuset=0, memory_mib=config.memory_mib)
    result = judge_solution(problem, config, solution, cases, limits, tmp_path / "w", options)
    assert result.verdict == verdicts.JUDGE_ERROR
    assert all(c.verdict == verdicts.NOT_RUN for c in result.testcases)
    assert "[validator]" in result.compile_log
