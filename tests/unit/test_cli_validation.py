"""validation 모드가 아직 지원하지 않는 범위인 problem 을 CLI 가 거부하는지 본다.

custom (계획 2 Task 3) 은 이제 지원한다. custom interactive 만 (계획 2 Task 5 까지) 거부한다.
docker 없이 돌아간다: load_problem_config 직후, container 작업이 시작되기 전에 거부되어야 한다.
"""

from __future__ import annotations

import icpc_verify.cli as cli


def _judge_argv(problem_dir, output_path, *, solution="accepted/main.cpp"):
    return [
        "judge",
        "--problem-dir",
        str(problem_dir),
        "--solution",
        solution,
        "--output",
        str(output_path),
    ]


def test_custom_interactive_validation_exits_two_before_any_docker_work(tmp_path, capsys):
    (tmp_path / "output_validator").mkdir()
    (tmp_path / "problem.yaml").write_text(
        "problem_format_version: 2023-07-draft\n"
        "name: Custom Interactive\n"
        "type: pass-fail\n"
        "validation: custom interactive\n",
        encoding="utf-8",
    )

    code = cli.main(_judge_argv(tmp_path, tmp_path / "result.json"))

    assert code == cli.EXIT_CONFIG
    err = capsys.readouterr().err
    assert "validation: custom interactive" in err
    assert "계획 2" in err
    assert not (tmp_path / "result.json").exists()
