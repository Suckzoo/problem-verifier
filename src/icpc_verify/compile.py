"""solution 을 judge container 안에서 컴파일하고 실행 argv 를 얻는다."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .sandbox import SandboxSpec, host_user, run_sandbox
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


def _stage_sources(solution: Solution, work_dir: Path, mount: str = WORK_MOUNT) -> list[str]:
    """소스를 work_dir 로 복사하고 container 안의 컴파일 대상 경로 목록을 돌려준다.

    unit 이 디렉토리면 디렉토리 전체를 복사한다 — header 나 보조 파일이
    소스 옆에 있어야 컴파일이 되기 때문이다. 컴파일 대상 목록은 인식된 소스뿐이다.
    """
    root = solution.path if solution.path.is_dir() else solution.path.parent
    if solution.path.is_dir():
        shutil.copytree(solution.path, work_dir, dirs_exist_ok=True)
    else:
        shutil.copy2(solution.path, work_dir / solution.path.name)
    return [f"{mount}/{source.relative_to(root).as_posix()}" for source in solution.sources]


def compile_solution(
    solution: Solution,
    work_dir: Path,
    memory_mib: int,
    options: CompileOptions,
    mount: str = WORK_MOUNT,
) -> CompileOutcome:
    if solution.error:
        return CompileOutcome(ok=False, log=solution.error, work_dir=work_dir, run_argv=())

    assert solution.language is not None
    sources = _stage_sources(solution, work_dir, mount)
    binds = ((work_dir, mount, "rw"),)
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
                mount,
                solution.entry,
                flags,
                "--",
                *sources,
            ),
            timeout=options.timeout,
            user=host_user(),
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
                mount,
                solution.entry,
                str(memory_mib),
            ),
            timeout=30.0,
            user=host_user(),
        )
    )
    if run_result.exit_code != 0:
        detail = run_result.stderr.decode("utf-8", errors="replace")
        return CompileOutcome(False, f"실행 명령을 만들지 못했습니다: {detail}", work_dir, ())

    argv = tuple(run_result.stdout.decode("utf-8").split("\n"))
    argv = tuple(part for part in argv if part)
    return CompileOutcome(ok=True, log=log, work_dir=work_dir, run_argv=argv)
