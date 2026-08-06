"""solution 을 judge container 안에서 컴파일하고 실행 argv 를 얻는다."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .sandbox import SandboxSpec, run_sandbox
from .solutions import Language, Solution

WORK_MOUNT = "/work"
COMPILE_MEMORY_MIB = 4096


@dataclass(frozen=True)
class CompileOptions:
    image: str
    cpuset: int
    flags: dict[Language, str] = field(default_factory=dict)
    timeout: float = 120.0


@dataclass(frozen=True)
class CompileOutcome:
    ok: bool
    log: str
    work_dir: Path
    run_argv: tuple[str, ...]


def _stage_sources(solution: Solution, work_dir: Path) -> list[str]:
    """소스를 work_dir 로 복사하고 container 안의 경로 목록을 돌려준다."""
    root = solution.path if solution.path.is_dir() else solution.path.parent
    staged: list[str] = []
    for source in solution.sources:
        rel = source.relative_to(root)
        target = work_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        staged.append(f"{WORK_MOUNT}/{rel.as_posix()}")
    return staged


def compile_solution(
    solution: Solution,
    work_dir: Path,
    memory_mib: int,
    options: CompileOptions,
) -> CompileOutcome:
    if solution.error:
        return CompileOutcome(ok=False, log=solution.error, work_dir=work_dir, run_argv=())

    assert solution.language is not None
    sources = _stage_sources(solution, work_dir)
    binds = ((work_dir, WORK_MOUNT, "rw"),)
    flags = options.flags.get(solution.language, "")

    compile_result = run_sandbox(
        SandboxSpec(
            image=options.image,
            cpuset=options.cpuset,
            memory_mib=COMPILE_MEMORY_MIB,
            binds=binds,
            argv=(
                "/usr/local/lib/icpc/compile.sh",
                solution.language.value,
                WORK_MOUNT,
                solution.entry,
                flags,
                "--",
                *sources,
            ),
            timeout=options.timeout,
        )
    )

    log = (compile_result.stdout + compile_result.stderr).decode("utf-8", errors="replace")
    if compile_result.timed_out:
        return CompileOutcome(False, log + "\ncompile timeout", work_dir, ())
    if compile_result.exit_code != 0:
        return CompileOutcome(False, log or "컴파일에 실패했습니다", work_dir, ())

    run_result = run_sandbox(
        SandboxSpec(
            image=options.image,
            cpuset=options.cpuset,
            memory_mib=COMPILE_MEMORY_MIB,
            binds=binds,
            argv=(
                "/usr/local/lib/icpc/run.sh",
                solution.language.value,
                WORK_MOUNT,
                solution.entry,
                str(memory_mib),
            ),
            timeout=30.0,
        )
    )
    if run_result.exit_code != 0:
        detail = run_result.stderr.decode("utf-8", errors="replace")
        return CompileOutcome(False, f"실행 명령을 만들지 못했습니다: {detail}", work_dir, ())

    argv = tuple(run_result.stdout.decode("utf-8").split("\n"))
    argv = tuple(part for part in argv if part)
    return CompileOutcome(ok=True, log=log, work_dir=work_dir, run_argv=argv)
