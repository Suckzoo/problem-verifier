"""CPU topology 확인과 judge CPU 선택.

physical core 가 2개 이상이면 마지막 core 를 통째로 쓰고 sibling 을 offline 한다.
core 가 1개뿐이면 offline 하지 않는다. 끄면 runner agent 와 judge 가 같은 thread 로 몰린다.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class CpuError(Exception):
    """architecture, CPU flag, topology 가 요구 조건에 맞지 않는다."""


@dataclass(frozen=True)
class CpuPlan:
    judge_cpu: int
    offline: tuple[int, ...]
    isolated: bool
    warnings: tuple[str, ...]


def _parse_cpu_list(text: str) -> tuple[int, ...]:
    values: list[int] = []
    for part in text.strip().split(","):
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            values.extend(range(int(lo), int(hi) + 1))
        else:
            values.append(int(part))
    return tuple(sorted(values))


def read_topology(sysfs: Path = Path("/sys/devices/system/cpu")) -> dict[int, tuple[int, ...]]:
    topology: dict[int, tuple[int, ...]] = {}
    for entry in sorted(sysfs.glob("cpu[0-9]*")):
        siblings_file = entry / "topology" / "thread_siblings_list"
        if not siblings_file.is_file():
            continue
        cpu = int(entry.name.removeprefix("cpu"))
        topology[cpu] = _parse_cpu_list(siblings_file.read_text(encoding="utf-8"))
    return topology


def check_arch_and_flags(machine: str, cpu_flags: set[str], required: Sequence[str]) -> None:
    if machine != "x86_64":
        raise CpuError(f"x86_64 runner 가 필요합니다. 현재 architecture: {machine}")
    missing = [flag for flag in required if flag and flag not in cpu_flags]
    if missing:
        raise CpuError(f"CPU 에 다음 flag 가 없습니다: {', '.join(missing)}")


def read_cpu_flags(cpuinfo: Path = Path("/proc/cpuinfo")) -> set[str]:
    for line in cpuinfo.read_text(encoding="utf-8").splitlines():
        if line.startswith("flags"):
            return set(line.split(":", 1)[1].split())
    return set()


def plan_cpu(
    topology: dict[int, tuple[int, ...]],
    *,
    requested: int | None,
    offline_sibling: bool,
) -> CpuPlan:
    if not topology:
        raise CpuError("CPU topology 를 읽지 못했습니다")

    if requested is not None:
        if requested not in topology:
            raise CpuError(f"judge-cpu {requested} 는 이 runner 에 없습니다")
        return CpuPlan(
            judge_cpu=requested,
            offline=(),
            isolated=False,
            warnings=("judge-cpu 를 직접 지정했습니다. sibling offline 을 하지 않습니다.",),
        )

    cores = sorted({siblings for siblings in topology.values()})
    last_core = cores[-1]

    if len(cores) == 1:
        return CpuPlan(
            judge_cpu=last_core[-1],
            offline=(),
            isolated=False,
            warnings=(
                "physical core 가 1개뿐입니다. sibling 을 끄지 않고 pin 만 합니다. "
                "hyperthread 간섭이 남으므로 timing 은 best-effort 입니다. "
                "4 vCPU 이상 runner 를 권장합니다.",
            ),
        )

    judge_cpu = last_core[0]
    siblings = tuple(cpu for cpu in last_core if cpu != judge_cpu)

    if not siblings:
        return CpuPlan(judge_cpu=judge_cpu, offline=(), isolated=True, warnings=())

    if not offline_sibling:
        return CpuPlan(
            judge_cpu=judge_cpu,
            offline=(),
            isolated=False,
            warnings=("offline-sibling 이 꺼져 있습니다. hyperthread 간섭이 남습니다.",),
        )

    return CpuPlan(judge_cpu=judge_cpu, offline=siblings, isolated=True, warnings=())


def apply_cpu_plan(plan: CpuPlan) -> list[str]:
    """sibling 을 offline 한다. 실패하면 경고 문자열을 돌려준다."""
    warnings: list[str] = []
    for cpu in plan.offline:
        try:
            subprocess.run(
                ["sudo", "tee", f"/sys/devices/system/cpu/cpu{cpu}/online"],
                input="0\n",
                text=True,
                check=True,
                capture_output=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            warnings.append(f"cpu{cpu} offline 에 실패했습니다: {exc}")
    return warnings
