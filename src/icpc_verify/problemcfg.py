"""problem.yaml 파싱. legacy 와 2023-07-draft 이후를 모두 읽는다.

새 key 를 먼저 보고, 없으면 legacy key 로 내려간다.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml


class ProblemConfigError(Exception):
    """problem.yaml 을 읽을 수 없거나 지원 범위 밖이다."""


class ValidationMode(StrEnum):
    DEFAULT = "default"
    CUSTOM = "custom"
    CUSTOM_INTERACTIVE = "custom interactive"


@dataclass(frozen=True)
class ProblemConfig:
    name: str
    time_limit: float
    memory_mib: int
    time_multiplier: float
    validation: ValidationMode
    validator_flags: tuple[str, ...]
    validator_dir: Path | None
    format_version: str


def _find_validator_dir(problem_dir: Path) -> Path | None:
    singular = problem_dir / "output_validator"
    if singular.is_dir():
        return singular

    plural = problem_dir / "output_validators"
    if not plural.is_dir():
        return None

    candidates = sorted(p for p in plural.iterdir() if p.is_dir())
    if not candidates:
        return None
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise ProblemConfigError(
            f"output_validators/ 아래 디렉토리는 1개여야 합니다. 찾은 것: {names}"
        )
    return candidates[0]


def load_problem_config(
    problem_dir: Path,
    *,
    default_time_limit: float,
    default_memory_mib: int,
) -> ProblemConfig:
    path = problem_dir / "problem.yaml"
    if not path.is_file():
        raise ProblemConfigError(f"problem.yaml 이 없습니다: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProblemConfigError(f"problem.yaml 파싱에 실패했습니다: {exc}") from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ProblemConfigError("problem.yaml 의 최상위는 mapping 이어야 합니다")

    is_new = "problem_format_version" in raw
    format_version = "2023-07" if is_new else "legacy"

    problem_type = str(raw.get("type", "pass-fail")).strip()
    if is_new and problem_type != "pass-fail":
        raise ProblemConfigError(f"type 이 {problem_type!r} 입니다. pass-fail 문제만 지원합니다")

    limits = raw.get("limits") or {}
    if not isinstance(limits, dict):
        raise ProblemConfigError("limits 는 mapping 이어야 합니다")

    time_limit = float(limits.get("time_limit", default_time_limit))
    memory_mib = int(limits.get("memory", default_memory_mib))
    time_multiplier = float(limits.get("time_multiplier", 5))

    validator_dir = _find_validator_dir(problem_dir)

    raw_validation = raw.get("validation")
    if raw_validation is None:
        mode = ValidationMode.CUSTOM if validator_dir else ValidationMode.DEFAULT
    else:
        text = " ".join(str(raw_validation).split())
        try:
            mode = ValidationMode(text)
        except ValueError as exc:
            raise ProblemConfigError(f"알 수 없는 validation 값입니다: {text!r}") from exc

    if mode is not ValidationMode.DEFAULT and validator_dir is None:
        raise ProblemConfigError(
            "validation 이 custom 인데 output_validator(s)/ 디렉토리를 찾지 못했습니다"
        )

    flags_source = raw.get("validator_flags")
    if flags_source is None:
        output_validator = raw.get("output_validator") or {}
        if isinstance(output_validator, dict):
            flags_source = output_validator.get("args")

    if flags_source is None:
        flags: tuple[str, ...] = ()
    elif isinstance(flags_source, str):
        flags = tuple(shlex.split(flags_source))
    elif isinstance(flags_source, list):
        flags = tuple(str(x) for x in flags_source)
    else:
        raise ProblemConfigError("validator_flags 는 문자열이나 리스트여야 합니다")

    return ProblemConfig(
        name=str(raw.get("name", problem_dir.resolve().name)),
        time_limit=time_limit,
        memory_mib=memory_mib,
        time_multiplier=time_multiplier,
        validation=mode,
        validator_flags=flags,
        validator_dir=validator_dir,
        format_version=format_version,
    )
