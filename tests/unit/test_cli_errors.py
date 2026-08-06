"""main() 이 예상 못한 예외를 EXIT_MISMATCH(1) 이 아니라 EXIT_CONFIG(2) 로 묶는지 본다.

docker 없이 돌아간다: run_judge 를 monkeypatch 로 대체해서 예외를 강제로 일으킨다.
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


def test_unexpected_exception_maps_to_exit_config_not_mismatch(tmp_path, capsys, monkeypatch):
    def boom(args):
        raise RuntimeError("boom: docker 가 갑자기 사라졌다")

    monkeypatch.setattr(cli, "run_judge", boom)

    code = cli.main(_judge_argv(tmp_path, tmp_path / "result.json"))

    assert code == cli.EXIT_CONFIG
    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert "boom" in err
