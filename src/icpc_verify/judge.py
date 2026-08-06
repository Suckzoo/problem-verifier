"""solution 하나를 testcase 전체에 대해 채점한다.

testcase 1회 = container 1개다. 기본은 lazy judging 이고 첫 비 AC 에서 멈춘다.
이 모듈은 validation: default 만 다룬다. custom/interactive 는 계획 2 다.
"""

from __future__ import annotations

import json
import shutil
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import verdicts
from .compare import compare_output, parse_compare_flags
from .compile import CompileOptions, compile_solution
from .problemcfg import ProblemConfig
from .results import RunMeasurement, SolutionResult, TestCaseResult, classify_run, solution_verdict
from .sandbox import SandboxSpec, host_user, run_sandbox
from .solutions import Language, Solution
from .testdata import TestCase
from .timelimits import TimeLimits

RUN_MOUNT = "/run"
OUT_MOUNT = "/out"
WORK_MOUNT = "/work"
STDERR_KEEP_BYTES = 8 * 1024


@dataclass
class JudgeOptions:
    image: str
    cpuset: int
    judge_all: bool = False
    output_limit_mib: int = 8
    memory_mib: int = 2048
    compile_flags: dict[Language, str] = field(default_factory=dict)
    machine_factor: float = 1.0
    cpu_isolated: bool = False
    warnings: list[str] = field(default_factory=list)


def measure_machine_factor(image: str, cpuset: int, rounds: int = 3) -> float:
    reference_result = run_sandbox(
        SandboxSpec(
            image=image,
            cpuset=cpuset,
            memory_mib=1024,
            binds=(),
            argv=("cat", "/usr/local/lib/icpc/BENCH_REFERENCE"),
            timeout=60.0,
            user=host_user(),
        )
    )
    reference = float(reference_result.stdout.decode().strip())

    samples: list[float] = []
    for _ in range(rounds):
        result = run_sandbox(
            SandboxSpec(
                image=image,
                cpuset=cpuset,
                memory_mib=1024,
                binds=(),
                argv=("/usr/local/bin/bench",),
                timeout=120.0,
                user=host_user(),
            )
        )
        samples.append(float(result.stdout.decode().strip()))
    return statistics.median(samples) / reference


def _describe_missing_run_result(sandbox_stderr: bytes) -> str:
    """run.json 이 없을 때 (docker 실행 자체가 실패했거나 runner 가 끝까지 못 갔을 때)
    보여줄 메시지를 만든다. out_dir/stderr 가 아니라 sandbox(docker) 자신의 stderr 를 쓴다 -
    runner 가 자기 stderr 파일을 열기도 전에 죽었을 수 있기 때문이다."""
    detail = sandbox_stderr[:STDERR_KEEP_BYTES].decode("utf-8", errors="replace").strip()
    message = "run.json 을 만들지 못했습니다 (container 가 끝까지 실행되지 않았습니다)"
    if detail:
        message = f"{message}\nstderr: {detail}"
    return message


def _run_one_testcase(
    case: TestCase,
    run_argv: Sequence[str],
    work_dir: Path,
    io_dir: Path,
    limits: TimeLimits,
    options: JudgeOptions,
) -> tuple[RunMeasurement | None, bytes, str]:
    """(측정값, team 출력, stderr 요약) 을 돌려준다.

    측정값이 None 이면 run.json 을 만들지 못한 것이다 (judge_error). 그 경우 stderr
    요약 자리에는 _describe_missing_run_result 가 만든 진단 메시지가 들어간다.
    """
    run_dir = io_dir / "in"
    out_dir = io_dir / "out"
    for d in (run_dir, out_dir):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    # the container runs as the host user (--user), so owner rwx is enough for both binds;
    # no "other" bits are needed since there's no uid mismatch left to work around.
    run_dir.chmod(0o755)
    out_dir.chmod(0o755)
    shutil.copy2(case.input_path, run_dir / "tc.in")

    output_limit = options.output_limit_mib * 1024 * 1024
    result = run_sandbox(
        SandboxSpec(
            image=options.image,
            cpuset=options.cpuset,
            memory_mib=options.memory_mib,
            binds=(
                (work_dir, WORK_MOUNT, "ro"),
                (run_dir, RUN_MOUNT, "ro"),
                (out_dir, OUT_MOUNT, "rw"),
            ),
            argv=(
                "python3",
                "/usr/local/bin/runner.py",
                "--input",
                f"{RUN_MOUNT}/tc.in",
                "--stdout",
                f"{OUT_MOUNT}/stdout",
                "--stderr",
                f"{OUT_MOUNT}/stderr",
                "--result",
                f"{OUT_MOUNT}/run.json",
                "--hard-kill",
                f"{limits.hard_kill:.3f}",
                "--output-limit",
                str(output_limit),
                "--",
                *run_argv,
            ),
            timeout=limits.hard_kill + 60.0,
            user=host_user(),
        )
    )

    result_file = out_dir / "run.json"
    if not result_file.is_file():
        return None, b"", _describe_missing_run_result(result.stderr)

    raw = json.loads(result_file.read_text(encoding="utf-8"))
    measurement = RunMeasurement(
        wall=raw["wall"],
        cpu=raw["cpu"],
        max_rss_kib=raw["max_rss_kib"],
        exit_code=raw["exit_code"],
        signal=raw["signal"],
        timed_out=raw["timed_out"],
        output_limit_exceeded=raw["output_limit_exceeded"],
        oom_killed=result.oom_killed,
    )

    stdout_path = out_dir / "stdout"
    team_output = stdout_path.read_bytes() if stdout_path.is_file() else b""
    stderr_path = out_dir / "stderr"
    stderr_text = ""
    if stderr_path.is_file():
        data = stderr_path.read_bytes()[:STDERR_KEEP_BYTES]
        stderr_text = data.decode("utf-8", errors="replace")
    return measurement, team_output, stderr_text


def judge_solution(
    problem_dir: Path,
    config: ProblemConfig,
    solution: Solution,
    testcases: Sequence[TestCase],
    limits: TimeLimits,
    work_root: Path,
    options: JudgeOptions,
) -> SolutionResult:
    result = SolutionResult(
        name=solution.name,
        rel_path=solution.rel_path,
        expected=solution.expected,
        language=solution.language.value if solution.language else "",
        verdict=verdicts.JUDGE_ERROR,
        machine_factor=options.machine_factor,
        cpu_isolated=options.cpu_isolated,
        warnings=list(options.warnings),
    )

    work_dir = work_root / "work"
    io_dir = work_root / "io"
    work_dir.mkdir(parents=True, exist_ok=True)
    io_dir.mkdir(parents=True, exist_ok=True)
    # compile_solution binds work_dir rw (container writes binaries/.class/__pycache__ into
    # it as the host user); the later run binds it ro. Owner rwx satisfies both.
    work_dir.chmod(0o755)

    outcome = compile_solution(
        solution,
        work_dir,
        config.memory_mib,
        CompileOptions(image=options.image, cpuset=options.cpuset, flags=options.compile_flags),
    )
    result.compile_log = outcome.log
    if not outcome.ok:
        result.verdict = verdicts.COMPILER_ERROR
        result.testcases = [
            TestCaseResult(c.id, c.group, verdicts.NOT_RUN, 0.0, 0.0, 0, 0, "") for c in testcases
        ]
        return result

    compare_flags = parse_compare_flags(config.validator_flags)
    stopped = False
    for case in testcases:
        if stopped:
            result.testcases.append(
                TestCaseResult(case.id, case.group, verdicts.NOT_RUN, 0.0, 0.0, 0, 0, "")
            )
            continue

        measurement, team_output, stderr_text = _run_one_testcase(
            case, outcome.run_argv, work_dir, io_dir, limits, options
        )
        if measurement is None:
            result.testcases.append(
                TestCaseResult(
                    id=case.id,
                    group=case.group,
                    verdict=verdicts.JUDGE_ERROR,
                    wall=0.0,
                    cpu=0.0,
                    mem_kib=0,
                    exit_code=0,
                    message=stderr_text,
                )
            )
            if not options.judge_all:
                stopped = True
            continue

        compare_ok, compare_message = compare_output(
            team_output, case.answer_path.read_bytes(), compare_flags
        )
        verdict, message = classify_run(measurement, limits, compare_ok, compare_message)
        if stderr_text and verdict == verdicts.RUN_TIME_ERROR:
            message = f"{message}\nstderr: {stderr_text}"

        result.testcases.append(
            TestCaseResult(
                id=case.id,
                group=case.group,
                verdict=verdict,
                wall=measurement.wall,
                cpu=measurement.cpu,
                mem_kib=measurement.max_rss_kib,
                exit_code=measurement.exit_code,
                message=message,
            )
        )
        if verdict != verdicts.ACCEPTED and not options.judge_all:
            stopped = True

    result.verdict = solution_verdict(result.testcases)
    return result
