"""시간제한과 hard kill 시각 계산.

overshoot 표기는 DOMjudge를 따른다.
  "Xs"      초
  "Y%"      시간제한의 백분율
  "Xs|Y%"   둘 중 최대값
  "Xs&Y%"   둘 중 최소값
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SECONDS = re.compile(r"^(\d+(?:\.\d+)?)s$")
_PERCENT = re.compile(r"^(\d+(?:\.\d+)?)%$")


class OvershootSpecError(ValueError):
    """overshoot 표기나 시간제한이 잘못되었다."""


@dataclass(frozen=True)
class TimeLimits:
    limit: float
    overshoot: float
    hard_kill: float


def _term_to_seconds(term: str, limit: float) -> float:
    m = _SECONDS.match(term)
    if m:
        return float(m.group(1))
    m = _PERCENT.match(term)
    if m:
        return limit * float(m.group(1)) / 100.0
    raise OvershootSpecError(f"overshoot 항목을 해석할 수 없습니다: {term!r}")


def make_time_limits(limit: float, overshoot_spec: str) -> TimeLimits:
    if limit <= 0:
        raise OvershootSpecError(f"시간제한은 0보다 커야 합니다: {limit}")

    spec = overshoot_spec.strip()
    if not spec:
        raise OvershootSpecError("overshoot 표기가 비어 있습니다")

    if "|" in spec and "&" in spec:
        raise OvershootSpecError(f"'|'와 '&'를 함께 쓸 수 없습니다: {overshoot_spec!r}")

    if "|" in spec:
        sep, combine = "|", max
    elif "&" in spec:
        sep, combine = "&", min
    else:
        sep, combine = None, None

    if sep is None:
        overshoot = _term_to_seconds(spec, limit)
    else:
        terms = [t.strip() for t in spec.split(sep)]
        if len(terms) != 2:
            raise OvershootSpecError(f"항목이 2개여야 합니다: {overshoot_spec!r}")
        overshoot = combine(_term_to_seconds(t, limit) for t in terms)

    return TimeLimits(limit=limit, overshoot=overshoot, hard_kill=limit + overshoot)
