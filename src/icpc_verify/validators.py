"""custom output validator 의 빌드 계획과 판정 규약.

Kattis/DOMjudge 규약:
  ./validator <input> <judge_ans> <feedback_dir> [flags] < team_output
  exit 42 -> AC, 43 -> WA, 그 외 -> judge_error

빌드 우선순위: build 스크립트 > run 스크립트 > 소스에서 언어 추론.
container 실행이 필요한 부분(빌드/호출)은 이 모듈의 별도 함수가 맡는다 (Task 2).
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import verdicts
from .compile import CompileOptions, compile_solution
from .sandbox import SandboxSpec, host_user, run_sandbox
from .solutions import Solution, describe_unit

JUDGEMESSAGE_CAP = 4096
VALIDATOR_MOUNT = "/validator"
VALIDATOR_MEMORY_MIB = 2048
BUILD_TIMEOUT = 120.0


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


@dataclass(frozen=True)
class BuiltValidator:
    dir: Path
    argv: tuple[str, ...]
    log: str = ""


def build_validator(
    validator_dir: Path, build_root: Path, *, image: str, cpuset: int
) -> BuiltValidator:
    plan = plan_validator_build(validator_dir)

    build_dir = build_root / "validator"
    shutil.rmtree(build_dir, ignore_errors=True)
    shutil.copytree(validator_dir, build_dir)
    build_dir.chmod(0o755)

    if plan.kind == "run-script":
        (build_dir / "run").chmod(0o755)
        return BuiltValidator(dir=build_dir, argv=(f"{VALIDATOR_MOUNT}/run",))

    if plan.kind == "build-script":
        (build_dir / "build").chmod(0o755)
        result = run_sandbox(
            SandboxSpec(
                image=image,
                cpuset=cpuset,
                memory_mib=VALIDATOR_MEMORY_MIB,
                binds=((build_dir, VALIDATOR_MOUNT, "rw"),),
                argv=(f"{VALIDATOR_MOUNT}/build",),
                timeout=BUILD_TIMEOUT,
                user=host_user(),
            )
        )
        log = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        if result.timed_out or result.exit_code != 0:
            raise ValidatorError(f"validator build 스크립트가 실패했습니다:\n{log}")
        run_path = build_dir / "run"
        if not run_path.is_file():
            raise ValidatorError("build 스크립트가 run 실행 파일을 만들지 않았습니다")
        run_path.chmod(0o755)
        return BuiltValidator(dir=build_dir, argv=(f"{VALIDATOR_MOUNT}/run",), log=log)

    # kind == "sources": solution 과 같은 파이프라인으로 컴파일한다
    assert plan.solution is not None
    outcome = compile_solution(
        plan.solution,
        build_dir,
        VALIDATOR_MEMORY_MIB,
        CompileOptions(image=image, cpuset=cpuset),
        mount=VALIDATOR_MOUNT,
    )
    if not outcome.ok:
        raise ValidatorError(f"validator 컴파일에 실패했습니다:\n{outcome.log}")
    return BuiltValidator(dir=build_dir, argv=outcome.run_argv, log=outcome.log)


def run_custom_validator(
    built: BuiltValidator,
    *,
    input_path: Path,
    answer_path: Path,
    team_output_path: Path,
    feedback_dir: Path,
    flags: Sequence[str],
    image: str,
    cpuset: int,
    timeout: float,
) -> tuple[str, str]:
    data_dir = feedback_dir.parent / "vdata"
    shutil.rmtree(data_dir, ignore_errors=True)
    data_dir.mkdir(parents=True)
    data_dir.chmod(0o755)
    shutil.copy2(input_path, data_dir / "tc.in")
    shutil.copy2(answer_path, data_dir / "tc.ans")
    shutil.copy2(team_output_path, data_dir / "tc.out")

    shutil.rmtree(feedback_dir, ignore_errors=True)
    feedback_dir.mkdir(parents=True)
    feedback_dir.chmod(0o755)

    result = run_sandbox(
        SandboxSpec(
            image=image,
            cpuset=cpuset,
            memory_mib=VALIDATOR_MEMORY_MIB,
            binds=(
                (built.dir, VALIDATOR_MOUNT, "ro"),
                (data_dir, "/data", "ro"),
                (feedback_dir, "/feedback", "rw"),
            ),
            argv=(
                "sh",
                "-c",
                'exec "$@" < /data/tc.out',
                "sh",
                *built.argv,
                "/data/tc.in",
                "/data/tc.ans",
                "/feedback",
                *flags,
            ),
            timeout=timeout,
            user=host_user(),
        )
    )

    message = read_judgemessage(feedback_dir)
    if result.timed_out:
        return verdicts.JUDGE_ERROR, "validator 가 시간 안에 끝나지 않았습니다"
    verdict = validator_verdict(result.exit_code)
    if verdict == verdicts.JUDGE_ERROR:
        detail = result.stderr[:JUDGEMESSAGE_CAP].decode("utf-8", errors="replace")
        message = f"validator exit code {result.exit_code}\n{detail}".strip()
    return verdict, message
