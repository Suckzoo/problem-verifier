"""solution 하나를 testcase 전체에 대해 채점한다.

testcase 1회 = container 1개다. 기본은 lazy judging 이고 첫 비 AC 에서 멈춘다.
validation: default / custom / custom interactive 를 모두 이 모듈이 다룬다.
"""

from __future__ import annotations

import json
import shutil
import signal as signal_module
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import verdicts
from .compare import compare_output, parse_compare_flags
from .compile import CompileOptions, compile_solution
from .problemcfg import ProblemConfig, ValidationMode
from .results import RunMeasurement, SolutionResult, TestCaseResult, classify_run, solution_verdict
from .sandbox import SandboxSpec, host_user, run_sandbox
from .solutions import Language, Solution
from .testdata import TestCase
from .timelimits import TimeLimits
from .validators import (
    VALIDATOR_MOUNT,
    BuiltValidator,
    ValidatorError,
    build_validator,
    read_judgemessage,
    run_custom_validator,
)

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


def _classify_interactive(raw: dict, limits: TimeLimits, memory_mib: int) -> tuple[str, str]:
    """interactive_runner.py 의 result JSON 을 verdict 으로 바꾼다.

    우선순위: TLE(pair timeout 포함) -> 메모리 -> 비정상 종료 -> validator 판정.
    SIGPIPE 는 3번 단계에서 용서되므로 validator 가 43 으로 끝나도 정상 WA 로 남는다
    (spec 의 "SIGPIPE 는 용서한다" 규약).
    """
    sol = raw["solution"]
    if raw["pair_timed_out"] or sol["timed_out"] or sol["wall"] > limits.limit:
        return (
            verdicts.TIME_LIMIT_EXCEEDED,
            f"wall {sol['wall']:.3f}s 가 시간제한 {limits.limit:.3f}s 를 넘었습니다",
        )
    if sol["max_rss_kib"] > memory_mib * 1024:
        return verdicts.RUN_TIME_ERROR, "메모리 제한을 넘었습니다 (max RSS 기준)"
    if sol["signal"] not in (0, int(signal_module.SIGPIPE)):
        return verdicts.RUN_TIME_ERROR, f"signal {sol['signal']} 로 종료했습니다"
    if sol["signal"] == 0 and sol["exit_code"] != 0:
        return verdicts.RUN_TIME_ERROR, f"exit code {sol['exit_code']} 로 종료했습니다"
    verdict = {42: verdicts.ACCEPTED, 43: verdicts.WRONG_ANSWER}.get(
        raw["validator_exit"], verdicts.JUDGE_ERROR
    )
    message = ""
    if verdict == verdicts.JUDGE_ERROR:
        message = f"validator exit code {raw['validator_exit']}"
    return verdict, message


def _run_one_testcase(
    case: TestCase,
    run_argv: Sequence[str],
    work_dir: Path,
    io_dir: Path,
    limits: TimeLimits,
    options: JudgeOptions,
) -> tuple[RunMeasurement | None, bytes, Path, str]:
    """(측정값, team 출력, team 출력 경로, stderr 요약) 을 돌려준다.

    측정값이 None 이면 run.json 을 만들지 못한 것이다 (judge_error). 그 경우 stderr
    요약 자리에는 _describe_missing_run_result 가 만든 진단 메시지가 들어간다.
    team 출력 경로는 항상 존재한다 (출력이 없으면 빈 파일을 만든다) - custom validator
    가 그 경로를 그대로 마운트해서 읽기 때문이다.
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
        return None, b"", out_dir / "stdout", _describe_missing_run_result(result.stderr)

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
    if stdout_path.is_file():
        team_output = stdout_path.read_bytes()
    else:
        team_output = b""
        stdout_path.write_bytes(b"")
    stderr_path = out_dir / "stderr"
    stderr_text = ""
    if stderr_path.is_file():
        data = stderr_path.read_bytes()[:STDERR_KEEP_BYTES]
        stderr_text = data.decode("utf-8", errors="replace")
    return measurement, team_output, stdout_path, stderr_text


def _run_interactive_testcase(
    case: TestCase,
    run_argv: Sequence[str],
    validator: BuiltValidator,
    work_dir: Path,
    io_dir: Path,
    config: ProblemConfig,
    limits: TimeLimits,
    options: JudgeOptions,
) -> tuple[dict | None, Path, str]:
    """(run.json 파싱 결과, feedback 디렉토리, 진단 메시지) 를 돌려준다.

    파싱 결과가 None 이면 run.json 을 만들지 못한 것이다 (judge_error). 그 경우
    메시지 자리에 _describe_missing_run_result 가 만든 진단이 들어간다 (성공했을 때는
    빈 문자열이다 - judgemessage 는 호출한 쪽에서 feedback 디렉토리를 통해 읽는다).

    interactive 에서는 solution 의 stdin 이 validator 의 stdout 이므로 입력 파일을
    solution 에 직접 리다이렉트하지 않는다 - validator 가 argv 로 받은 /data/tc.in 을
    스스로 읽는다.
    """
    data_dir = io_dir / "idata"
    out_dir = io_dir / "out"
    feedback_dir = io_dir / "feedback"
    for d in (data_dir, out_dir, feedback_dir):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    # the container runs as the host user (--user), so owner rwx is enough for every bind.
    data_dir.chmod(0o755)
    out_dir.chmod(0o755)
    feedback_dir.chmod(0o755)
    shutil.copy2(case.input_path, data_dir / "tc.in")
    shutil.copy2(case.answer_path, data_dir / "tc.ans")

    container_memory = options.memory_mib + 512
    result = run_sandbox(
        SandboxSpec(
            image=options.image,
            cpuset=options.cpuset,
            memory_mib=container_memory,
            binds=(
                (work_dir, WORK_MOUNT, "ro"),
                (validator.dir, VALIDATOR_MOUNT, "ro"),
                (data_dir, "/data", "ro"),
                (feedback_dir, "/feedback", "rw"),
                (out_dir, OUT_MOUNT, "rw"),
            ),
            argv=(
                "python3",
                "/usr/local/bin/interactive_runner.py",
                "--result",
                f"{OUT_MOUNT}/run.json",
                "--hard-kill",
                f"{limits.hard_kill:.3f}",
                "--pair-timeout",
                f"{limits.hard_kill + 5.0:.3f}",
                "--validator-json",
                json.dumps(
                    [
                        *validator.argv,
                        "/data/tc.in",
                        "/data/tc.ans",
                        "/feedback",
                        *config.validator_flags,
                    ]
                ),
                "--",
                *run_argv,
            ),
            timeout=limits.hard_kill + 60.0,
            user=host_user(),
        )
    )

    result_file = out_dir / "run.json"
    if not result_file.is_file():
        message = _describe_missing_run_result(result.stderr)
        if result.oom_killed:
            # container 전체 기준이라 solution/validator 중 누가 죽었는지는 모른다.
            oom_note = "container 가 OOMKilled 되었습니다 (누가 죽었는지는 구분할 수 없습니다)"
            message = f"{message}\n{oom_note}"
        return None, feedback_dir, message

    raw = json.loads(result_file.read_text(encoding="utf-8"))
    return raw, feedback_dir, ""


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

    validator = None
    if config.validation in (ValidationMode.CUSTOM, ValidationMode.CUSTOM_INTERACTIVE):
        assert config.validator_dir is not None
        try:
            validator = build_validator(
                config.validator_dir,
                work_root,
                image=options.image,
                cpuset=options.cpuset,
            )
        except ValidatorError as exc:
            result.verdict = verdicts.JUDGE_ERROR
            result.compile_log = f"{result.compile_log}\n[validator] {exc}".strip()
            result.testcases = [
                TestCaseResult(c.id, c.group, verdicts.NOT_RUN, 0.0, 0.0, 0, 0, "")
                for c in testcases
            ]
            return result

    compare_flags = (
        parse_compare_flags(config.validator_flags)
        if config.validation is ValidationMode.DEFAULT
        else None
    )
    stopped = False
    for case in testcases:
        if stopped:
            result.testcases.append(
                TestCaseResult(case.id, case.group, verdicts.NOT_RUN, 0.0, 0.0, 0, 0, "")
            )
            continue

        if config.validation is ValidationMode.CUSTOM_INTERACTIVE:
            assert validator is not None
            raw, feedback_dir, missing_message = _run_interactive_testcase(
                case, outcome.run_argv, validator, work_dir, io_dir, config, limits, options
            )
            if raw is None:
                result.testcases.append(
                    TestCaseResult(
                        id=case.id,
                        group=case.group,
                        verdict=verdicts.JUDGE_ERROR,
                        wall=0.0,
                        cpu=0.0,
                        mem_kib=0,
                        exit_code=0,
                        message=missing_message,
                    )
                )
                if not options.judge_all:
                    stopped = True
                continue

            verdict, message = _classify_interactive(raw, limits, options.memory_mib)
            judgemessage = read_judgemessage(feedback_dir)
            if judgemessage:
                message = f"{message}\n{judgemessage}".strip() if message else judgemessage
            sol = raw["solution"]
            result.testcases.append(
                TestCaseResult(
                    id=case.id,
                    group=case.group,
                    verdict=verdict,
                    wall=sol["wall"],
                    cpu=sol["cpu"],
                    mem_kib=sol["max_rss_kib"],
                    exit_code=sol["exit_code"],
                    message=message,
                )
            )
            if verdict != verdicts.ACCEPTED and not options.judge_all:
                stopped = True
            continue

        measurement, team_output, team_output_path, stderr_text = _run_one_testcase(
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

        if validator is not None:
            # 실행 자체의 건강 상태(TLE/RTE/OLE)를 먼저 판정하고,
            # 깨끗할 때만 validator 에게 출력을 묻는다 (spec §6.3 의 순서).
            verdict, message = classify_run(measurement, limits, True, "")
            if verdict == verdicts.ACCEPTED:
                verdict, message = run_custom_validator(
                    validator,
                    input_path=case.input_path,
                    answer_path=case.answer_path,
                    team_output_path=team_output_path,
                    feedback_dir=io_dir / "feedback",
                    flags=config.validator_flags,
                    image=options.image,
                    cpuset=options.cpuset,
                    timeout=limits.hard_kill + 30.0,
                )
        else:
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
