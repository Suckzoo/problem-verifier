"""측정값을 verdict 으로 바꾸고 결과 구조를 정의한다.

판정 우선순위: 시간 -> 출력 크기 -> 메모리/비정상 종료 -> 출력 내용.
wall <= limit 일 때만 통과다. overshoot 는 판정 경계가 아니다.
runner 는 출력 제한 초과 시 SIGKILL 로 죽이므로(signal=9) 출력 크기 검사가
signal/exit_code 검사보다 먼저여야 OLE 가 run_time_error 로 뒤덮이지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from . import verdicts
from .timelimits import TimeLimits


@dataclass(frozen=True)
class RunMeasurement:
    wall: float
    cpu: float
    max_rss_kib: int
    exit_code: int
    signal: int
    timed_out: bool
    output_limit_exceeded: bool
    oom_killed: bool


@dataclass
class TestCaseResult:
    id: str
    group: str
    verdict: str
    wall: float
    cpu: float
    mem_kib: int
    exit_code: int
    message: str
    expected_excerpt: str = ""
    actual_excerpt: str = ""


@dataclass
class SolutionResult:
    name: str
    rel_path: str
    expected: str
    language: str
    verdict: str
    testcases: list[TestCaseResult] = field(default_factory=list)
    compile_log: str = ""
    machine_factor: float = 1.0
    cpu_isolated: bool = False
    warnings: list[str] = field(default_factory=list)


def classify_run(
    m: RunMeasurement,
    limits: TimeLimits,
    compare_ok: bool,
    compare_message: str,
) -> tuple[str, str]:
    if m.timed_out or m.wall > limits.limit:
        return (
            verdicts.TIME_LIMIT_EXCEEDED,
            f"wall {m.wall:.3f}s 가 시간제한 {limits.limit:.3f}s 를 넘었습니다",
        )
    if m.output_limit_exceeded:
        return verdicts.WRONG_ANSWER, "OLE. 출력이 제한을 넘었습니다"
    if m.oom_killed:
        return verdicts.RUN_TIME_ERROR, "메모리 제한을 넘어 kill 되었습니다"
    if m.signal:
        return verdicts.RUN_TIME_ERROR, f"signal {m.signal} 로 종료했습니다"
    if m.exit_code != 0:
        return verdicts.RUN_TIME_ERROR, f"exit code {m.exit_code} 로 종료했습니다"
    if not compare_ok:
        return verdicts.WRONG_ANSWER, compare_message
    return verdicts.ACCEPTED, ""


def solution_verdict(testcases: Sequence[TestCaseResult]) -> str:
    judged = [c for c in testcases if c.verdict != verdicts.NOT_RUN]
    if not judged:
        return verdicts.JUDGE_ERROR
    for case in judged:
        if case.verdict != verdicts.ACCEPTED:
            return case.verdict
    return verdicts.ACCEPTED


def matches_expectation(expected: str, actual: str, mode: str) -> bool:
    if mode == "exact":
        return expected == actual
    if mode == "any-rejected":
        if expected == verdicts.ACCEPTED:
            return actual == verdicts.ACCEPTED
        return actual != verdicts.ACCEPTED
    raise ValueError(f"알 수 없는 verdict-match 모드입니다: {mode!r}")
