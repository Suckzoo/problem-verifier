"""icpc-verify CLI. 계획 1 에서는 judge 하위 명령만 있다."""

from __future__ import annotations

import argparse
import dataclasses
import json
import platform
import sys
import tempfile
import traceback
from pathlib import Path

from .cpu import (
    CpuError,
    apply_cpu_plan,
    check_arch_and_flags,
    plan_cpu,
    read_cpu_flags,
    read_topology,
)
from .judge import JudgeOptions, judge_solution, measure_machine_factor
from .problemcfg import ProblemConfigError, load_problem_config
from .results import matches_expectation
from .solutions import Language, discover_solutions
from .testdata import TestDataError, collect_testcases
from .timelimits import OvershootSpecError, make_time_limits

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_CONFIG = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="icpc-verify")
    sub = parser.add_subparsers(dest="command", required=True)

    judge = sub.add_parser("judge", help="solution 하나를 채점한다")
    judge.add_argument("--problem-dir", type=Path, default=Path("."))
    judge.add_argument("--solution", required=True)
    judge.add_argument("--output", type=Path, required=True)
    judge.add_argument("--image", default="")
    judge.add_argument("--judge-cpu", type=int, default=None)
    judge.add_argument("--no-offline-sibling", action="store_true")
    judge.add_argument("--judge-all", action="store_true")
    judge.add_argument("--default-time-limit", type=float, default=1.0)
    judge.add_argument("--default-memory-mib", type=int, default=2048)
    judge.add_argument("--timelimit-overshoot", default="2s|20%")
    judge.add_argument("--output-limit-mib", type=int, default=8)
    judge.add_argument("--required-cpu-flags", default="avx2")
    judge.add_argument("--verdict-match", choices=["exact", "any-rejected"], default="exact")
    judge.add_argument("--compile-flags-cpp", default="")
    judge.add_argument("--compile-flags-c", default="")
    judge.add_argument("--compile-flags-java", default="")
    judge.add_argument("--diff-max-cases", type=int, default=3)
    judge.add_argument("--diff-max-bytes", type=int, default=4096)
    return parser


def _default_image() -> str:
    path = Path(__file__).resolve().parents[2] / "image" / "IMAGE_DIGEST"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    raise FileNotFoundError("judge image 를 정하지 못했습니다. --image 를 주세요")


def run_judge(args: argparse.Namespace) -> int:
    problem_dir = args.problem_dir.resolve()

    config = load_problem_config(
        problem_dir,
        default_time_limit=args.default_time_limit,
        default_memory_mib=args.default_memory_mib,
    )
    limits = make_time_limits(config.time_limit, args.timelimit_overshoot)
    testcases = collect_testcases(problem_dir)

    solutions, warnings = discover_solutions(problem_dir)
    matched = [s for s in solutions if s.rel_path == args.solution]
    if not matched:
        raise ProblemConfigError(f"solution 을 찾지 못했습니다: {args.solution}")
    solution = matched[0]

    required = [f for f in args.required_cpu_flags.split(",") if f.strip()]
    check_arch_and_flags(platform.machine(), read_cpu_flags(), required)

    cpu_plan = plan_cpu(
        read_topology(),
        requested=args.judge_cpu,
        offline_sibling=not args.no_offline_sibling,
    )
    all_warnings = [*warnings, *cpu_plan.warnings, *apply_cpu_plan(cpu_plan)]

    image = args.image or _default_image()
    machine_factor = measure_machine_factor(image, cpu_plan.judge_cpu)

    options = JudgeOptions(
        image=image,
        cpuset=cpu_plan.judge_cpu,
        judge_all=args.judge_all,
        output_limit_mib=args.output_limit_mib,
        memory_mib=config.memory_mib,
        compile_flags={
            Language.CPP: args.compile_flags_cpp,
            Language.C: args.compile_flags_c,
            Language.JAVA: args.compile_flags_java,
        },
        machine_factor=machine_factor,
        cpu_isolated=cpu_plan.isolated,
        warnings=all_warnings,
        diff_max_cases=args.diff_max_cases,
        diff_max_bytes=args.diff_max_bytes,
    )

    with tempfile.TemporaryDirectory(prefix="icpc-judge-") as tmp:
        result = judge_solution(
            problem_dir, config, solution, testcases, limits, Path(tmp), options
        )

    payload = dataclasses.asdict(result)
    payload["expectation_met"] = matches_expectation(
        result.expected, result.verdict, args.verdict_match
    )
    payload["time_limit"] = limits.limit
    payload["hard_kill"] = limits.hard_kill

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    for warning in all_warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"{result.rel_path}: 기대 {result.expected}, 실제 {result.verdict}")

    return EXIT_OK if payload["expectation_met"] else EXIT_MISMATCH


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "judge":
            return run_judge(args)
    except (ProblemConfigError, TestDataError, CpuError, OvershootSpecError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except Exception:
        # 예상 못한 예외까지 EXIT_MISMATCH(1) 로 새면, 이걸 소비하는 쪽에서 "verdict 불일치"와
        # "인프라 장애"를 구별하지 못한다. 그러니 여기서 잡아 EXIT_CONFIG 로 묶는다.
        traceback.print_exc(file=sys.stderr)
        return EXIT_CONFIG
    return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
