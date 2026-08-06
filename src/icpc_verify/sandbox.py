"""docker container 하나를 격리 설정으로 돌린다.

testcase 1회당 container 1개다. OOM 판정이 container 단위이기 때문이다.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path


class SandboxError(Exception):
    """docker 를 실행할 수 없다."""


def host_user() -> str:
    """`docker run --user` 에 줄 host 사용자 문자열이다.

    container 를 host uid:gid 로 돌리면 bind mount 에 root 소유 파일이 남지 않는다
    (container root 가 --cap-drop ALL 로 CAP_DAC_OVERRIDE 도 없이 host 파일시스템에
    쓰던 것과 달리, uid 가 host 와 같아지므로 일반 permission bit 로 충분해진다).
    """
    return f"{os.getuid()}:{os.getgid()}"


@dataclass(frozen=True)
class SandboxSpec:
    image: str
    cpuset: int
    memory_mib: int
    binds: tuple[tuple[Path, str, str], ...]
    argv: tuple[str, ...]
    timeout: float
    user: str | None = None
    workdir: str | None = None


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    oom_killed: bool
    stdout: bytes
    stderr: bytes
    timed_out: bool


def _docker(*args: str, **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["docker", *args], capture_output=True, **kwargs)
    except FileNotFoundError as exc:
        raise SandboxError("docker 명령을 찾지 못했습니다") from exc


def _parse_oom_killed(raw: bytes) -> bool:
    """`docker inspect --format '{{json .State}}'` 출력에서 OOMKilled 여부를 읽는다.

    비어있거나, JSON이 아니거나, dict가 아니거나, 키가 없으면 OOM이 아니라고 본다.
    """
    if not raw.strip():
        return False
    try:
        state = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(state, dict):
        return False
    return bool(state.get("OOMKilled", False))


def _build_run_argv(spec: SandboxSpec, name: str) -> list[str]:
    """`docker run` 에 넘길 argv 를 만든다. docker 를 실제로 부르지 않으므로 단독 테스트가 된다."""
    argv = [
        "run",
        "--name",
        name,
        "--cpuset-cpus",
        str(spec.cpuset),
        "--cpuset-mems",
        "0",
        "--memory",
        f"{spec.memory_mib}m",
        "--memory-swap",
        f"{spec.memory_mib}m",
        "--pids-limit",
        "256",
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=64m",
    ]
    if spec.user:
        argv += ["--user", spec.user]
    if spec.workdir:
        argv += ["-w", spec.workdir]
    for host, target, mode in spec.binds:
        argv += ["-v", f"{host.resolve()}:{target}:{mode}"]
    argv += [spec.image, *spec.argv]
    return argv


def run_sandbox(spec: SandboxSpec) -> SandboxResult:
    name = f"icpc-{uuid.uuid4().hex[:12]}"
    argv = _build_run_argv(spec, name)

    timed_out = False
    exit_code = -1
    stdout = b""
    stderr = b""
    oom_killed = False
    try:
        try:
            proc = _docker(*argv, timeout=spec.timeout)
            exit_code = proc.returncode
            stdout, stderr = proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            _docker("kill", name, timeout=30)

        inspect = _docker("inspect", "--format", "{{json .State}}", name, timeout=30)
        if inspect.returncode == 0:
            oom_killed = _parse_oom_killed(inspect.stdout)
    finally:
        # kill/inspect 가 예외를 던지더라도 container 는 반드시 정리한다.
        _docker("rm", "-f", name, timeout=30)

    return SandboxResult(
        exit_code=exit_code,
        oom_killed=oom_killed,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
    )
