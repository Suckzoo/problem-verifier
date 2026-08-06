"""custom output validator 의 빌드 계획과 판정 규약.

Kattis/DOMjudge 규약:
  ./validator <input> <judge_ans> <feedback_dir> [flags] < team_output
  exit 42 -> AC, 43 -> WA, 그 외 -> judge_error

빌드 우선순위: build 스크립트 > run 스크립트 > 소스에서 언어 추론.
container 실행이 필요한 부분(빌드/호출)은 이 모듈의 별도 함수가 맡는다 (Task 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import verdicts
from .solutions import Solution, describe_unit

JUDGEMESSAGE_CAP = 4096


class ValidatorError(Exception):
    """validator 를 빌드하거나 실행할 수 없다."""


@dataclass(frozen=True)
class BuildPlan:
    kind: str  # "build-script" | "run-script" | "sources"
    solution: Solution | None = None


def plan_validator_build(validator_dir: Path) -> BuildPlan:
    if not validator_dir.is_dir():
        raise ValidatorError(f"validator 디렉토리가 없습니다: {validator_dir}")

    if (validator_dir / "build").is_file():
        return BuildPlan(kind="build-script")
    if (validator_dir / "run").is_file():
        return BuildPlan(kind="run-script")

    solution, warning = describe_unit(validator_dir, validator_dir.parent, "validator")
    if solution is None:
        raise ValidatorError(f"validator 소스를 찾지 못했습니다: {warning}")
    if solution.error:
        raise ValidatorError(f"validator 소스가 잘못되었습니다: {solution.error}")
    return BuildPlan(kind="sources", solution=solution)


def validator_verdict(exit_code: int) -> str:
    if exit_code == 42:
        return verdicts.ACCEPTED
    if exit_code == 43:
        return verdicts.WRONG_ANSWER
    return verdicts.JUDGE_ERROR


def read_judgemessage(feedback_dir: Path) -> str:
    path = feedback_dir / "judgemessage.txt"
    if not path.is_file():
        return ""
    return path.read_bytes()[:JUDGEMESSAGE_CAP].decode("utf-8", errors="replace")
