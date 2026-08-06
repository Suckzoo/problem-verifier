"""docker container 하나를 격리 설정으로 돌린다.

testcase 1회당 container 1개다. OOM 판정이 container 단위이기 때문이다.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path


class SandboxError(Exception):
    """docker 를 실행할 수 없다."""


@dataclass(frozen=True)
class SandboxSpec:
    image: str
    cpuset: int
    memory_mib: int
    binds: tuple[tuple[Path, str, str], ...]
    argv: tuple[str, ...]
    timeout: float


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


def run_sandbox(spec: SandboxSpec) -> SandboxResult:
    name = f"icpc-{uuid.uuid4().hex[:12]}"
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
    for host, target, mode in spec.binds:
        argv += ["-v", f"{host.resolve()}:{target}:{mode}"]
    argv += [spec.image, *spec.argv]

    timed_out = False
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
    oom_killed = False
    if inspect.returncode == 0 and inspect.stdout.strip():
        try:
            oom_killed = bool(json.loads(inspect.stdout)["OOMKilled"])
        except (ValueError, KeyError):
            oom_killed = False

    _docker("rm", "-f", name, timeout=30)
    return SandboxResult(
        exit_code=exit_code,
        oom_killed=oom_killed,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
    )
