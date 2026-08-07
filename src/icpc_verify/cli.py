"""icpc-verify CLI. 계획 1 에서는 judge 하위 명령만 있다."""

from __future__ import annotations

import argparse
import dataclasses
import json
import platform
import subprocess
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
from .discover import build_matrix, changed_solution_units, decide_scope
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

    discover = sub.add_parser("discover", help="채점 대상을 결정한다")
    discover.add_argument("--problem-dir", type=Path, default=Path("."))
    discover.add_argument("--output", type=Path, required=True)
    discover.add_argument("--full", action="store_true")
    discover.add_argument("--event-name", default="")
    discover.add_argument("--before", default="")
    discover.add_argument("--head", default="")
    discover.add_argument("--base-ref", default="")
    discover.add_argument("--solutions-filter", default="")
    discover.add_argument("--default-time-limit", type=float, default=1.0)
    discover.add_argument("--default-memory-mib", type=int, default=2048)
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


def _git_changed_files(args: argparse.Namespace) -> list[str] | None:
    """diff 를 계산한다. 못 하면 None (전체 fallback)."""

    def diff(base: str, head: str) -> list[str] | None:
        proc = subprocess.run(
            ["git", "diff", "--name-only", base, head],
            capture_output=True,
            text=True,
            cwd=args.problem_dir,
        )
        if proc.returncode != 0:
            return None
        return [line for line in proc.stdout.splitlines() if line]

    if args.event_name == "pull_request" and args.base_ref:
        merge_base = subprocess.run(
            ["git", "merge-base", f"origin/{args.base_ref}", "HEAD"],
            capture_output=True,
            text=True,
            cwd=args.problem_dir,
        )
        if merge_base.returncode != 0:
            return None
        return diff(merge_base.stdout.strip(), "HEAD")

    if args.event_name == "push" and args.before and args.head:
        if set(args.before) == {"0"}:
            return None
        return diff(args.before, args.head)

    return None


def run_discover(args: argparse.Namespace) -> int:
    problem_dir = args.problem_dir.resolve()
    config = load_problem_config(
        problem_dir,
        default_time_limit=args.default_time_limit,
        default_memory_mib=args.default_memory_mib,
    )
    collect_testcases(problem_dir)  # data/ 짝 검사를 discover 단계에서 수행한다

    repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        cwd=problem_dir,
    )
    if repo_root.returncode == 0:
        problem_dir_rel = str(problem_dir.relative_to(Path(repo_root.stdout.strip()))).replace(
            "\\", "/"
        )
        if problem_dir_rel == ".":
            problem_dir_rel = ""
    else:
        problem_dir_rel = ""

    changed = _git_changed_files(args)
    full, reason = decide_scope(
        full_flag=args.full,
        event_name=args.event_name,
        changed_files=changed,
        problem_dir_rel=problem_dir_rel,
    )
    changed_units = changed_solution_units(changed, problem_dir_rel) if changed else set()

    solutions, warnings = discover_solutions(problem_dir, filter_glob=args.solutions_filter)
    matrix = build_matrix(solutions, full=full, changed_units=changed_units)

    payload = {
        "matrix": matrix,
        "count": len(matrix),
        "full": full,
        "reason": reason,
        "problem": {
            "name": config.name,
            "time_limit": config.time_limit,
            "memory_mib": config.memory_mib,
            "time_multiplier": config.time_multiplier,
            "validation": config.validation.value,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"discover: {len(matrix)}개 대상 ({reason})")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "judge":
            return run_judge(args)
        if args.command == "discover":
            return run_discover(args)
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
