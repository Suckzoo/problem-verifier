import json
import subprocess
import sys
from pathlib import Path

import pytest

from icpc_verify.discover import build_matrix, changed_solution_units, decide_scope
from icpc_verify.solutions import discover_solutions


def test_full_flag_wins():
    full, reason = decide_scope(
        full_flag=True,
        event_name="push",
        changed_files=["solutions/accepted/a.cpp"],
        problem_dir_rel="",
    )
    assert full
    assert "full" in reason


@pytest.mark.parametrize("event", ["workflow_dispatch", "schedule"])
def test_manual_events_are_full(event):
    full, _ = decide_scope(
        full_flag=False,
        event_name=event,
        changed_files=[],
        problem_dir_rel="",
    )
    assert full


def test_unknown_changes_fall_back_to_full():
    full, reason = decide_scope(
        full_flag=False,
        event_name="push",
        changed_files=None,
        problem_dir_rel="",
    )
    assert full
    assert "diff" in reason


@pytest.mark.parametrize(
    "path",
    [
        "problem.yaml",
        "data/01.in",
        "data/secret/03.ans",
        "output_validators/check/check.cpp",
        "output_validator/run",
        "include/util.h",
    ],
)
def test_problem_global_files_trigger_full(path):
    full, reason = decide_scope(
        full_flag=False,
        event_name="push",
        changed_files=[path],
        problem_dir_rel="",
    )
    assert full
    assert path.split("/")[0].rstrip("s") in reason or "problem" in reason


def test_solution_only_changes_are_incremental():
    full, _ = decide_scope(
        full_flag=False,
        event_name="push",
        changed_files=["solutions/accepted/a.cpp", "README.md"],
        problem_dir_rel="",
    )
    assert not full


def test_problem_dir_prefix_is_respected():
    # 문제 package 가 repo 하위 디렉토리(prob/)에 있을 때, 다른 문제의 변경은 무시한다
    full, _ = decide_scope(
        full_flag=False,
        event_name="push",
        changed_files=["other/problem.yaml"],
        problem_dir_rel="prob",
    )
    assert not full
    full, _ = decide_scope(
        full_flag=False,
        event_name="push",
        changed_files=["prob/problem.yaml"],
        problem_dir_rel="prob",
    )
    assert full


def test_changed_solution_units_maps_files_to_units():
    units = changed_solution_units(
        [
            "solutions/accepted/a.cpp",
            "solutions/accepted/multi/b.cpp",
            "solutions/wrong_answer/x.py",
            "solutions/accepted/multi/nested/c.h",
            "README.md",
        ],
        "",
    )
    assert units == {"accepted/a.cpp", "accepted/multi", "wrong_answer/x.py"}


def test_changed_solution_units_with_problem_dir():
    units = changed_solution_units(["prob/solutions/accepted/a.cpp"], "prob")
    assert units == {"accepted/a.cpp"}


def make_solutions(tmp_path):
    for rel, text in {
        "accepted/a.cpp": "int main(){}",
        "wrong_answer/b.cpp": "int main(){}",
    }.items():
        p = tmp_path / "solutions" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    sols, _ = discover_solutions(tmp_path)
    return sols


def test_build_matrix_full(tmp_path):
    entries = build_matrix(make_solutions(tmp_path), full=True, changed_units=set())
    assert [e["path"] for e in entries] == ["accepted/a.cpp", "wrong_answer/b.cpp"]
    assert entries[0] == {
        "name": "accepted_a.cpp",
        "path": "accepted/a.cpp",
        "expected": "accepted",
        "lang": "cpp",
    }


def test_build_matrix_incremental(tmp_path):
    entries = build_matrix(
        make_solutions(tmp_path), full=False, changed_units={"wrong_answer/b.cpp"}
    )
    assert [e["path"] for e in entries] == ["wrong_answer/b.cpp"]


FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "plain"


def run_cli(tmp_path, *extra):
    out = tmp_path / "discover.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "icpc_verify.cli",
            "discover",
            "--problem-dir",
            str(FIXTURE),
            "--output",
            str(out),
            *extra,
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
    return proc, payload


def test_cli_full_discovers_fixture(tmp_path):
    proc, payload = run_cli(tmp_path, "--full")
    assert proc.returncode == 0, proc.stderr
    assert payload["full"] is True
    assert payload["count"] == 5
    assert payload["problem"]["name"] == "Add Two Numbers"
    assert payload["problem"]["time_limit"] == 1.0
    assert payload["problem"]["validation"] == "default"
    names = {e["name"] for e in payload["matrix"]}
    assert "accepted_main.cpp" in names


def test_cli_without_git_context_falls_back_to_full(tmp_path):
    # --before/--head 없이 push 이벤트면 diff 를 계산할 수 없어 전체가 된다
    proc, payload = run_cli(tmp_path, "--event-name", "push")
    assert proc.returncode == 0
    assert payload["full"] is True


def test_cli_missing_problem_yaml_exits_two(tmp_path):
    out = tmp_path / "d.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "icpc_verify.cli",
            "discover",
            "--problem-dir",
            str(tmp_path),
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "problem.yaml" in proc.stderr
