"""Kattis default validator 와 같은 기본 출력 비교.

flag 가 없으면 공백으로 자른 token 단위로 비교하고 대소문자를 구분하지 않는다.
case_sensitive / space_change_sensitive 가 그 엄격함을 켠다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

_TOLERANCE_FLAGS = {
    "float_tolerance",
    "float_absolute_tolerance",
    "float_relative_tolerance",
}
_BOOL_FLAGS = {"case_sensitive", "space_change_sensitive"}


class CompareFlagError(ValueError):
    """validator_flags 를 해석할 수 없다."""


@dataclass(frozen=True)
class CompareFlags:
    case_sensitive: bool = False
    space_change_sensitive: bool = False
    float_absolute_tolerance: float | None = None
    float_relative_tolerance: float | None = None

    @property
    def compare_floats(self) -> bool:
        return (
            self.float_absolute_tolerance is not None or self.float_relative_tolerance is not None
        )


def parse_compare_flags(flags: Sequence[str]) -> CompareFlags:
    case_sensitive = False
    space_change_sensitive = False
    absolute: float | None = None
    relative: float | None = None

    i = 0
    items = list(flags)
    while i < len(items):
        flag = items[i]
        if flag in _BOOL_FLAGS:
            if flag == "case_sensitive":
                case_sensitive = True
            else:
                space_change_sensitive = True
            i += 1
            continue

        if flag in _TOLERANCE_FLAGS:
            if i + 1 >= len(items):
                raise CompareFlagError(f"{flag} 에 값이 없습니다")
            try:
                value = float(items[i + 1])
            except ValueError as exc:
                raise CompareFlagError(f"{flag} 의 값이 숫자가 아닙니다: {items[i + 1]!r}") from exc
            if flag in ("float_tolerance", "float_absolute_tolerance"):
                absolute = value
            if flag in ("float_tolerance", "float_relative_tolerance"):
                relative = value
            i += 2
            continue

        raise CompareFlagError(f"알 수 없는 validator flag 입니다: {flag!r}")

    return CompareFlags(
        case_sensitive=case_sensitive,
        space_change_sensitive=space_change_sensitive,
        float_absolute_tolerance=absolute,
        float_relative_tolerance=relative,
    )


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="surrogateescape")


def _floats_match(team: str, answer: str, flags: CompareFlags) -> bool | None:
    """숫자로 볼 수 없으면 None 을 돌려준다."""
    try:
        t, a = float(team), float(answer)
    except ValueError:
        return None
    if math.isnan(t) or math.isnan(a):
        return False
    if t == a:
        return True
    if math.isinf(t) or math.isinf(a):
        return False

    diff = abs(t - a)
    if flags.float_absolute_tolerance is not None and diff <= flags.float_absolute_tolerance:
        return True
    if flags.float_relative_tolerance is not None and a != 0:
        return diff / abs(a) <= flags.float_relative_tolerance
    return False


def _compare_tokens(team: str, answer: str, flags: CompareFlags) -> tuple[bool, str]:
    team_tokens = team.split()
    answer_tokens = answer.split()

    for index, (t, a) in enumerate(zip(team_tokens, answer_tokens, strict=False), start=1):
        if flags.compare_floats:
            verdict = _floats_match(t, a, flags)
            if verdict is True:
                continue
            if verdict is False:
                return False, f"token {index} 이 다릅니다: 기대 {a!r}, 실제 {t!r}"
        left, right = (t, a) if flags.case_sensitive else (t.lower(), a.lower())
        if left != right:
            return False, f"token {index} 이 다릅니다: 기대 {a!r}, 실제 {t!r}"

    if len(team_tokens) != len(answer_tokens):
        return False, (
            f"token 개수가 다릅니다: 기대 {len(answer_tokens)}개, 실제 {len(team_tokens)}개"
        )
    return True, ""


def _compare_exact(team: str, answer: str, flags: CompareFlags) -> tuple[bool, str]:
    left = team.rstrip("\n")
    right = answer.rstrip("\n")
    if not flags.case_sensitive:
        left, right = left.lower(), right.lower()
    if left == right:
        return True, ""

    for index, (lc, rc) in enumerate(zip(left, right, strict=False), start=1):
        if lc != rc:
            return False, f"{index}번째 문자가 다릅니다: 기대 {rc!r}, 실제 {lc!r}"
    return False, f"길이가 다릅니다: 기대 {len(right)}, 실제 {len(left)}"


def compare_output(team: bytes, answer: bytes, flags: CompareFlags) -> tuple[bool, str]:
    team_text = _decode(team)
    answer_text = _decode(answer)
    if flags.space_change_sensitive:
        return _compare_exact(team_text, answer_text, flags)
    return _compare_tokens(team_text, answer_text, flags)
