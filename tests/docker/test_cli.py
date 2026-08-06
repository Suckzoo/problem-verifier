import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "plain"
IMAGE = (ROOT / "image" / "IMAGE_DIGEST").read_text().strip()


def run_cli(tmp_path, rel_path, *extra, problem_dir=FIXTURE):
    out = tmp_path / "result.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "icpc_verify.cli",
            "judge",
            "--problem-dir",
            str(problem_dir),
            "--solution",
            rel_path,
            "--output",
            str(out),
            "--image",
            IMAGE,
            "--judge-cpu",
            "0",
            *extra,
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
    return proc, payload


def test_matching_expectation_exits_zero(tmp_path):
    proc, payload = run_cli(tmp_path, "accepted/main.cpp")
    assert proc.returncode == 0, proc.stderr
    assert payload["verdict"] == "accepted"
    assert payload["expectation_met"] is True
    assert payload["machine_factor"] > 0


def test_mismatched_expectation_exits_one(tmp_path):
    """시간제한을 30초로 늘리면 sleepy.cpp 는 accepted 가 되어 기대와 어긋난다."""
    problem = tmp_path / "problem"
    shutil.copytree(FIXTURE, problem)
    (problem / "problem.yaml").write_text(
        "problem_format_version: 2023-07-draft\n"
        "name: Add Two Numbers\n"
        "type: pass-fail\n"
        "limits:\n  time_limit: 30.0\n  memory: 512\n",
        encoding="utf-8",
    )
    proc, payload = run_cli(tmp_path, "time_limit_exceeded/sleepy.cpp", problem_dir=problem)
    assert proc.returncode == 1
    assert payload["verdict"] == "accepted"
    assert payload["expectation_met"] is False


def test_unknown_solution_exits_two(tmp_path):
    proc, _ = run_cli(tmp_path, "accepted/nope.cpp")
    assert proc.returncode == 2
    assert "nope.cpp" in proc.stderr


def test_missing_problem_yaml_exits_two(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "icpc_verify.cli",
            "judge",
            "--problem-dir",
            str(tmp_path),
            "--solution",
            "accepted/x.cpp",
            "--output",
            str(tmp_path / "r.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "problem.yaml" in proc.stderr


def test_result_json_shape(tmp_path):
    _, payload = run_cli(tmp_path, "accepted/main.cpp")
    assert set(payload) >= {
        "name",
        "rel_path",
        "expected",
        "language",
        "verdict",
        "testcases",
        "compile_log",
        "machine_factor",
        "cpu_isolated",
        "warnings",
        "expectation_met",
        "time_limit",
        "hard_kill",
    }
    case = payload["testcases"][0]
    assert set(case) == {"id", "group", "verdict", "wall", "cpu", "mem_kib", "exit_code", "message"}
