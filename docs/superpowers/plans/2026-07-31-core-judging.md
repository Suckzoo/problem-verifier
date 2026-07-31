# ICPC Problem Verifier — 계획 1: 채점 코어 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kattis/DOMjudge 호환 문제 package에서 solution 하나를 격리된 container 안에서 채점하고 `result.json`을 내는 CLI를 만든다.

**Architecture:** 순수 python 라이브러리(`src/icpc_verify/`)가 문제를 읽고 verdict을 정한다. 실제 실행은 ghcr에 올린 judge image의 container 안에서 하고, container 안에서는 `runner.py`가 시간과 메모리를 잰다. testcase 1회당 container 1개다. `validation: default`만 이 계획에서 다룬다. custom/interactive validator는 계획 2다.

**Tech Stack:** Python 3.12 (host), Docker, Ubuntu 24.04 judge image (g++ 13 / gcc 13 / OpenJDK 21 / CPython 3.9), pytest, ruff.

## Global Constraints

spec `docs/superpowers/specs/2026-07-31-icpc-problem-verifier-design.md`의 전역 요구사항이다. 모든 task에 적용된다.

- 대상 architecture는 **`x86_64` 전용**이다. arm64와 QEMU emulation은 지원하지 않는다.
- SIMD를 막지 않는다. compile flag에 `-march=native`를 절대 넣지 않는다. `#pragma GCC target("avx2")`와 intrinsic이 동작해야 한다.
- 기본 CPU flag 요구사항은 `avx2`다.
- 시간제한 기본값 1.0초, 메모리 기본값 2048 MiB.
- overshoot 기본 표기는 `2s|20%` 이고 `|`는 **최대값**, `&`는 **최소값**이다.
- verdict은 `wall time <= limit` 일 때만 통과다. overshoot는 판정 경계가 아니다.
- 언어는 C++(`gnu++20`), C(`gnu11`), Java 21, Python 3.9 네 가지다.
- verdict 이름은 Kattis 디렉토리 이름과 같다: `accepted`, `wrong_answer`, `time_limit_exceeded`, `run_time_error`. 여기에 내부 verdict `compiler_error`, `judge_error`, `not_run`을 더한다.
- MLE verdict은 없다. OOM은 `run_time_error`다.
- host python은 3.12이고 표준 라이브러리 + `PyYAML`만 쓴다.
- 모든 파일 경로는 `pathlib.Path`로 다룬다.
- 커밋 메시지는 Conventional Commits를 쓴다.

---

### Task 1: Repo 뼈대와 테스트 환경

**Files:**
- Create: `pyproject.toml`
- Create: `src/icpc_verify/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_smoke.py`
- Create: `.gitignore`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: 없음
- Produces: `icpc_verify.__version__: str`. package import 경로 `icpc_verify`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/unit/test_smoke.py`:

```python
def test_package_imports():
    import icpc_verify

    assert icpc_verify.__version__ == "0.1.0"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/test_smoke.py -v`
Expected: FAIL. `ModuleNotFoundError: No module named 'icpc_verify'`

- [ ] **Step 3: 최소 구현을 쓴다**

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "icpc-verify"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["PyYAML>=6.0"]

[project.scripts]
icpc-verify = "icpc_verify.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["docker: judge image가 필요한 테스트"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

`src/icpc_verify/__init__.py`:

```python
__version__ = "0.1.0"
```

`tests/unit/__init__.py`: 빈 파일.

`.gitignore`:

```
__pycache__/
*.egg-info/
.pytest_cache/
.ruff_cache/
build/
dist/
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pip install -e . && python -m pytest tests/unit -v`
Expected: PASS

- [ ] **Step 5: CI workflow를 쓴다**

`.github/workflows/ci.yml`:

```yaml
name: ci
on:
  push:
  pull_request:

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install -e . pytest ruff
      - run: ruff check .
      - run: ruff format --check .
      - run: python -m pytest tests/unit -v
```

- [ ] **Step 6: lint와 테스트를 돌린다**

Run: `ruff check . && ruff format --check . && python -m pytest tests/unit -v`
Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add pyproject.toml src tests .gitignore .github/workflows/ci.yml
git commit -m "chore: scaffold icpc-verify package with pytest and ruff"
```

---

### Task 2: 시간제한 계산

**Files:**
- Create: `src/icpc_verify/timelimits.py`
- Create: `tests/unit/test_timelimits.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `TimeLimits` dataclass: `limit: float`, `overshoot: float`, `hard_kill: float`
  - `make_time_limits(limit: float, overshoot_spec: str) -> TimeLimits`
  - `OvershootSpecError(ValueError)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/unit/test_timelimits.py`:

```python
import pytest

from icpc_verify.timelimits import OvershootSpecError, make_time_limits


def test_seconds_only():
    t = make_time_limits(1.0, "2s")
    assert t.limit == 1.0
    assert t.overshoot == 2.0
    assert t.hard_kill == 3.0


def test_percent_only():
    t = make_time_limits(5.0, "20%")
    assert t.overshoot == pytest.approx(1.0)
    assert t.hard_kill == pytest.approx(6.0)


def test_pipe_takes_maximum():
    assert make_time_limits(1.0, "2s|20%").overshoot == pytest.approx(2.0)
    assert make_time_limits(20.0, "2s|20%").overshoot == pytest.approx(4.0)


def test_ampersand_takes_minimum():
    assert make_time_limits(1.0, "2s&20%").overshoot == pytest.approx(0.2)
    assert make_time_limits(20.0, "2s&20%").overshoot == pytest.approx(2.0)


def test_whitespace_is_tolerated():
    assert make_time_limits(1.0, " 2s | 20% ").overshoot == pytest.approx(2.0)


@pytest.mark.parametrize("spec", ["", "2", "abc", "2s|", "|20%", "2s|20%|1s", "-2s"])
def test_invalid_spec_raises(spec):
    with pytest.raises(OvershootSpecError):
        make_time_limits(1.0, spec)


def test_non_positive_limit_raises():
    with pytest.raises(OvershootSpecError):
        make_time_limits(0.0, "2s")
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/test_timelimits.py -v`
Expected: FAIL. `ModuleNotFoundError: No module named 'icpc_verify.timelimits'`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/icpc_verify/timelimits.py`:

```python
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
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/unit/test_timelimits.py -v`
Expected: PASS. 12개 전부

- [ ] **Step 5: 커밋**

```bash
git add src/icpc_verify/timelimits.py tests/unit/test_timelimits.py
git commit -m "feat: parse DOMjudge timelimit overshoot spec"
```

---

### Task 3: verdict 상수

**Files:**
- Create: `src/icpc_verify/verdicts.py`
- Create: `tests/unit/test_verdicts.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - 상수 `ACCEPTED`, `WRONG_ANSWER`, `TIME_LIMIT_EXCEEDED`, `RUN_TIME_ERROR`, `COMPILER_ERROR`, `JUDGE_ERROR`, `NOT_RUN` (전부 `str`)
  - `EXPECTED_VERDICTS: tuple[str, ...]` — `solutions/` 하위 디렉토리로 쓸 수 있는 4개
  - `SUMMARY_ICON: dict[str, str]` — verdict -> emoji

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/unit/test_verdicts.py`:

```python
from icpc_verify import verdicts


def test_expected_verdicts_are_kattis_directory_names():
    assert verdicts.EXPECTED_VERDICTS == (
        "accepted",
        "wrong_answer",
        "time_limit_exceeded",
        "run_time_error",
    )


def test_every_verdict_has_an_icon():
    all_verdicts = {
        verdicts.ACCEPTED,
        verdicts.WRONG_ANSWER,
        verdicts.TIME_LIMIT_EXCEEDED,
        verdicts.RUN_TIME_ERROR,
        verdicts.COMPILER_ERROR,
        verdicts.JUDGE_ERROR,
        verdicts.NOT_RUN,
    }
    assert all_verdicts <= set(verdicts.SUMMARY_ICON)


def test_not_run_icon_is_white():
    assert verdicts.SUMMARY_ICON[verdicts.NOT_RUN] == "⬜"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/test_verdicts.py -v`
Expected: FAIL. `ModuleNotFoundError`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/icpc_verify/verdicts.py`:

```python
"""verdict 이름과 표시용 기호.

이름은 Kattis 의 solutions/ 하위 디렉토리 이름과 같다.
DOMjudge/Kattis 에 MLE verdict 이 없으므로 OOM 은 run_time_error 로 매핑한다.
"""

from __future__ import annotations

ACCEPTED = "accepted"
WRONG_ANSWER = "wrong_answer"
TIME_LIMIT_EXCEEDED = "time_limit_exceeded"
RUN_TIME_ERROR = "run_time_error"
COMPILER_ERROR = "compiler_error"
JUDGE_ERROR = "judge_error"
NOT_RUN = "not_run"

EXPECTED_VERDICTS: tuple[str, ...] = (
    ACCEPTED,
    WRONG_ANSWER,
    TIME_LIMIT_EXCEEDED,
    RUN_TIME_ERROR,
)

SUMMARY_ICON: dict[str, str] = {
    ACCEPTED: "\U0001f7e9",
    WRONG_ANSWER: "\U0001f7e5",
    TIME_LIMIT_EXCEEDED: "\U0001f7e8",
    RUN_TIME_ERROR: "\U0001f7e7",
    COMPILER_ERROR: "\U0001f7ea",
    JUDGE_ERROR: "\U0001f7ea",
    NOT_RUN: "⬜",
}
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/unit/test_verdicts.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/icpc_verify/verdicts.py tests/unit/test_verdicts.py
git commit -m "feat: define verdict names and summary icons"
```

---

### Task 4: problem.yaml 파싱

**Files:**
- Create: `src/icpc_verify/problemcfg.py`
- Create: `tests/unit/test_problemcfg.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `ValidationMode` — `str` Enum. 값 `"default"`, `"custom"`, `"custom interactive"`
  - `ProblemConfig` dataclass:
    `name: str`, `time_limit: float`, `memory_mib: int`, `time_multiplier: float`,
    `validation: ValidationMode`, `validator_flags: tuple[str, ...]`,
    `validator_dir: Path | None`, `format_version: str`
  - `load_problem_config(problem_dir: Path, *, default_time_limit: float, default_memory_mib: int) -> ProblemConfig`
  - `ProblemConfigError(Exception)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/unit/test_problemcfg.py`:

```python
import pytest

from icpc_verify.problemcfg import (
    ProblemConfigError,
    ValidationMode,
    load_problem_config,
)

DEFAULTS = {"default_time_limit": 1.0, "default_memory_mib": 2048}


def write_problem(tmp_path, yaml_text, *, validator_dir=None):
    (tmp_path / "problem.yaml").write_text(yaml_text, encoding="utf-8")
    if validator_dir:
        (tmp_path / validator_dir).mkdir(parents=True)
        (tmp_path / validator_dir / "check.cpp").write_text("int main(){}", encoding="utf-8")
    return tmp_path


def test_legacy_defaults(tmp_path):
    write_problem(tmp_path, "name: Hello\n")
    cfg = load_problem_config(tmp_path, **DEFAULTS)
    assert cfg.name == "Hello"
    assert cfg.time_limit == 1.0
    assert cfg.memory_mib == 2048
    assert cfg.time_multiplier == 5.0
    assert cfg.validation is ValidationMode.DEFAULT
    assert cfg.validator_flags == ()
    assert cfg.validator_dir is None
    assert cfg.format_version == "legacy"


def test_legacy_custom_validator(tmp_path):
    write_problem(
        tmp_path,
        "name: Hello\nvalidation: custom\nvalidator_flags: float_tolerance 1e-6\n",
        validator_dir="output_validators/check",
    )
    cfg = load_problem_config(tmp_path, **DEFAULTS)
    assert cfg.validation is ValidationMode.CUSTOM
    assert cfg.validator_flags == ("float_tolerance", "1e-6")
    assert cfg.validator_dir.name == "check"


def test_legacy_interactive(tmp_path):
    write_problem(
        tmp_path,
        "name: Hello\nvalidation: custom interactive\n",
        validator_dir="output_validators/inter",
    )
    cfg = load_problem_config(tmp_path, **DEFAULTS)
    assert cfg.validation is ValidationMode.CUSTOM_INTERACTIVE


def test_legacy_limits(tmp_path):
    write_problem(tmp_path, "name: Hello\nlimits:\n  memory: 512\n  time_multiplier: 3\n")
    cfg = load_problem_config(tmp_path, **DEFAULTS)
    assert cfg.memory_mib == 512
    assert cfg.time_multiplier == 3.0


def test_new_format(tmp_path):
    write_problem(
        tmp_path,
        "problem_format_version: 2023-07-draft\n"
        "name: Hello\n"
        "type: pass-fail\n"
        "limits:\n  time_limit: 2.5\n  memory: 1024\n",
    )
    cfg = load_problem_config(tmp_path, **DEFAULTS)
    assert cfg.format_version == "2023-07"
    assert cfg.time_limit == 2.5
    assert cfg.memory_mib == 1024
    assert cfg.validation is ValidationMode.DEFAULT


def test_new_format_singular_validator_dir(tmp_path):
    write_problem(
        tmp_path,
        "problem_format_version: 2023-07-draft\nname: Hello\ntype: pass-fail\n",
        validator_dir="output_validator",
    )
    cfg = load_problem_config(tmp_path, **DEFAULTS)
    assert cfg.validation is ValidationMode.CUSTOM
    assert cfg.validator_dir.name == "output_validator"


def test_scoring_type_is_rejected(tmp_path):
    write_problem(
        tmp_path,
        "problem_format_version: 2023-07-draft\nname: Hello\ntype: scoring\n",
    )
    with pytest.raises(ProblemConfigError, match="pass-fail"):
        load_problem_config(tmp_path, **DEFAULTS)


def test_missing_file(tmp_path):
    with pytest.raises(ProblemConfigError, match="problem.yaml"):
        load_problem_config(tmp_path, **DEFAULTS)


def test_broken_yaml(tmp_path):
    (tmp_path / "problem.yaml").write_text("name: [unclosed\n", encoding="utf-8")
    with pytest.raises(ProblemConfigError):
        load_problem_config(tmp_path, **DEFAULTS)


def test_custom_validation_without_validator_dir(tmp_path):
    write_problem(tmp_path, "name: Hello\nvalidation: custom\n")
    with pytest.raises(ProblemConfigError, match="output_validator"):
        load_problem_config(tmp_path, **DEFAULTS)


def test_multiple_legacy_validator_dirs_is_rejected(tmp_path):
    write_problem(
        tmp_path,
        "name: Hello\nvalidation: custom\n",
        validator_dir="output_validators/a",
    )
    (tmp_path / "output_validators" / "b").mkdir()
    with pytest.raises(ProblemConfigError, match="1개"):
        load_problem_config(tmp_path, **DEFAULTS)
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/test_problemcfg.py -v`
Expected: FAIL. `ModuleNotFoundError`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/icpc_verify/problemcfg.py`:

```python
"""problem.yaml 파싱. legacy 와 2023-07-draft 이후를 모두 읽는다.

새 key 를 먼저 보고, 없으면 legacy key 로 내려간다.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml


class ProblemConfigError(Exception):
    """problem.yaml 을 읽을 수 없거나 지원 범위 밖이다."""


class ValidationMode(str, Enum):
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
        raise ProblemConfigError(
            f"type 이 {problem_type!r} 입니다. pass-fail 문제만 지원합니다"
        )

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
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/unit/test_problemcfg.py -v`
Expected: PASS. 11개 전부

- [ ] **Step 5: 커밋**

```bash
git add src/icpc_verify/problemcfg.py tests/unit/test_problemcfg.py
git commit -m "feat: parse problem.yaml for legacy and 2023-07 formats"
```

---

### Task 5: testcase 수집

**Files:**
- Create: `src/icpc_verify/testdata.py`
- Create: `tests/unit/test_testdata.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `TestCase` dataclass: `id: str`, `group: str`, `input_path: Path`, `answer_path: Path`
  - `collect_testcases(problem_dir: Path) -> list[TestCase]`
  - `TestDataError(Exception)`

`id`는 `data/` 기준 상대 경로에서 확장자를 뗀 값이다 (예: `secret/03`). `group`은 상대 디렉토리이고 평평한 구조에서는 빈 문자열이다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/unit/test_testdata.py`:

```python
import pytest

from icpc_verify.testdata import TestDataError, collect_testcases


def make_case(root, rel, ans=True):
    p = root / "data" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.with_suffix(".in").write_text("1\n", encoding="utf-8")
    if ans:
        p.with_suffix(".ans").write_text("1\n", encoding="utf-8")


def test_flat_layout(tmp_path):
    make_case(tmp_path, "02")
    make_case(tmp_path, "01")
    cases = collect_testcases(tmp_path)
    assert [c.id for c in cases] == ["01", "02"]
    assert [c.group for c in cases] == ["", ""]


def test_kattis_nested_layout(tmp_path):
    make_case(tmp_path, "sample/01")
    make_case(tmp_path, "secret/03")
    cases = collect_testcases(tmp_path)
    assert [c.id for c in cases] == ["sample/01", "secret/03"]
    assert [c.group for c in cases] == ["sample", "secret"]


def test_answer_must_be_in_same_directory(tmp_path):
    make_case(tmp_path, "secret/03", ans=False)
    (tmp_path / "data" / "03.ans").write_text("1\n", encoding="utf-8")
    with pytest.raises(TestDataError, match="secret/03"):
        collect_testcases(tmp_path)


def test_missing_data_dir(tmp_path):
    with pytest.raises(TestDataError, match="data"):
        collect_testcases(tmp_path)


def test_empty_data_dir(tmp_path):
    (tmp_path / "data").mkdir()
    with pytest.raises(TestDataError, match="testcase"):
        collect_testcases(tmp_path)
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/test_testdata.py -v`
Expected: FAIL. `ModuleNotFoundError`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/icpc_verify/testdata.py`:

```python
"""data/ 아래의 testcase 수집.

평평한 구조(data/01.in)와 Kattis 중첩 구조(data/secret/03.in)를 모두 지원한다.
.ans 는 같은 디렉토리에 같은 이름으로 있어야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class TestDataError(Exception):
    """data/ 구조가 잘못되었다."""


@dataclass(frozen=True)
class TestCase:
    id: str
    group: str
    input_path: Path
    answer_path: Path


def collect_testcases(problem_dir: Path) -> list[TestCase]:
    data_dir = problem_dir / "data"
    if not data_dir.is_dir():
        raise TestDataError(f"data/ 디렉토리가 없습니다: {data_dir}")

    cases: list[TestCase] = []
    for input_path in sorted(data_dir.rglob("*.in")):
        rel = input_path.relative_to(data_dir).with_suffix("")
        answer_path = input_path.with_suffix(".ans")
        if not answer_path.is_file():
            raise TestDataError(f"{rel.as_posix()} 의 .ans 파일이 없습니다: {answer_path}")
        cases.append(
            TestCase(
                id=rel.as_posix(),
                group=rel.parent.as_posix() if rel.parent != Path(".") else "",
                input_path=input_path,
                answer_path=answer_path,
            )
        )

    if not cases:
        raise TestDataError(f"testcase 를 찾지 못했습니다: {data_dir}")
    return cases
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/unit/test_testdata.py -v`
Expected: PASS. 5개 전부

- [ ] **Step 5: 커밋**

```bash
git add src/icpc_verify/testdata.py tests/unit/test_testdata.py
git commit -m "feat: collect testcases from flat and nested data layouts"
```

---

### Task 6: solution 발견과 언어 판별

**Files:**
- Create: `src/icpc_verify/solutions.py`
- Create: `tests/unit/test_solutions.py`

**Interfaces:**
- Consumes: `icpc_verify.verdicts.EXPECTED_VERDICTS`
- Produces:
  - `Language` — `str` Enum. 값 `"cpp"`, `"c"`, `"java"`, `"python"`
  - `Solution` dataclass:
    `name: str`, `rel_path: str`, `path: Path`, `expected: str`,
    `language: Language | None`, `sources: tuple[Path, ...]`,
    `entry: str`, `error: str | None`
  - `discover_solutions(problem_dir: Path, *, filter_glob: str = "") -> tuple[list[Solution], list[str]]`
    반환은 `(solutions, warnings)`다.
  - `sanitize_name(rel_path: str) -> str`

`error`가 채워진 `Solution`은 judge 단계에서 `compiler_error`가 된다. 발견 단계에서는 예외를 던지지 않는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/unit/test_solutions.py`:

```python
from icpc_verify.solutions import Language, discover_solutions, sanitize_name

JAVA_MAIN = "public class Main { public static void main(String[] args) {} }\n"


def write(root, rel, text="x"):
    p = root / "solutions" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_sanitize_name():
    assert sanitize_name("accepted/main.cpp") == "accepted_main.cpp"
    assert sanitize_name("wrong_answer/a b.py") == "wrong_answer_a_b.py"


def test_single_file_solutions(tmp_path):
    write(tmp_path, "accepted/main.cpp")
    write(tmp_path, "wrong_answer/greedy.c")
    sols, warnings = discover_solutions(tmp_path)
    assert warnings == []
    assert [(s.rel_path, s.expected, s.language) for s in sols] == [
        ("accepted/main.cpp", "accepted", Language.CPP),
        ("wrong_answer/greedy.c", "wrong_answer", Language.C),
    ]


def test_multi_file_directory_solution(tmp_path):
    write(tmp_path, "accepted/multi/a.cpp")
    write(tmp_path, "accepted/multi/b.cpp")
    sols, _ = discover_solutions(tmp_path)
    assert len(sols) == 1
    assert sols[0].rel_path == "accepted/multi"
    assert len(sols[0].sources) == 2


def test_java_entry_point(tmp_path):
    write(tmp_path, "accepted/Main.java", JAVA_MAIN)
    sols, _ = discover_solutions(tmp_path)
    assert sols[0].language is Language.JAVA
    assert sols[0].entry == "Main"
    assert sols[0].error is None


def test_java_without_main_is_an_error(tmp_path):
    write(tmp_path, "accepted/Helper.java", "public class Helper {}\n")
    sols, _ = discover_solutions(tmp_path)
    assert sols[0].error is not None
    assert "main" in sols[0].error


def test_python_single_file_entry(tmp_path):
    write(tmp_path, "accepted/sol.py", "print(1)\n")
    sols, _ = discover_solutions(tmp_path)
    assert sols[0].language is Language.PYTHON
    assert sols[0].entry == "sol.py"


def test_python_multi_file_needs_main_py(tmp_path):
    write(tmp_path, "accepted/pkg/a.py")
    write(tmp_path, "accepted/pkg/b.py")
    sols, _ = discover_solutions(tmp_path)
    assert sols[0].error is not None
    assert "main.py" in sols[0].error


def test_mixed_languages_is_an_error(tmp_path):
    write(tmp_path, "accepted/mix/a.cpp")
    write(tmp_path, "accepted/mix/b.py")
    sols, _ = discover_solutions(tmp_path)
    assert sols[0].error is not None
    assert "언어" in sols[0].error


def test_unknown_directory_warns_and_is_skipped(tmp_path):
    write(tmp_path, "maybe_accepted/x.cpp")
    sols, warnings = discover_solutions(tmp_path)
    assert sols == []
    assert any("maybe_accepted" in w for w in warnings)


def test_unsupported_extension_warns_and_is_skipped(tmp_path):
    write(tmp_path, "accepted/notes.txt")
    sols, warnings = discover_solutions(tmp_path)
    assert sols == []
    assert any("notes.txt" in w for w in warnings)


def test_filter_glob(tmp_path):
    write(tmp_path, "accepted/main.cpp")
    write(tmp_path, "wrong_answer/greedy.cpp")
    sols, _ = discover_solutions(tmp_path, filter_glob="accepted/**")
    assert [s.rel_path for s in sols] == ["accepted/main.cpp"]


def test_missing_solutions_dir_returns_empty(tmp_path):
    sols, warnings = discover_solutions(tmp_path)
    assert sols == []
    assert any("solutions" in w for w in warnings)
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/test_solutions.py -v`
Expected: FAIL. `ModuleNotFoundError`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/icpc_verify/solutions.py`:

```python
"""solutions/ 아래에서 채점 대상을 찾고 언어와 entry point 를 정한다.

solution 단위는 solutions/<verdict>/<이름>.<ext> 또는 solutions/<verdict>/<이름>/ 이다.
문제가 있는 solution 은 예외 대신 error 필드를 채워 돌려준다.
judge 단계가 그것을 compiler_error 로 바꾼다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path

from .verdicts import EXPECTED_VERDICTS

JAVA_MAIN_RE = re.compile(r"public\s+static\s+void\s+main\s*\(\s*String")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class Language(str, Enum):
    CPP = "cpp"
    C = "c"
    JAVA = "java"
    PYTHON = "python"


EXTENSIONS: dict[str, Language] = {
    ".cpp": Language.CPP,
    ".cc": Language.CPP,
    ".cxx": Language.CPP,
    ".C": Language.CPP,
    ".c": Language.C,
    ".java": Language.JAVA,
    ".py": Language.PYTHON,
}


@dataclass(frozen=True)
class Solution:
    name: str
    rel_path: str
    path: Path
    expected: str
    language: Language | None
    sources: tuple[Path, ...]
    entry: str
    error: str | None


def sanitize_name(rel_path: str) -> str:
    return _UNSAFE.sub("_", rel_path)


def _language_of(path: Path) -> Language | None:
    return EXTENSIONS.get(path.suffix)


def _java_entry(sources: tuple[Path, ...]) -> tuple[str, str | None]:
    mains = [p for p in sources if JAVA_MAIN_RE.search(p.read_text(encoding="utf-8", errors="replace"))]
    if not mains:
        return "", "java main 메서드를 가진 파일을 찾지 못했습니다"
    if len(mains) > 1:
        names = ", ".join(p.name for p in mains)
        return "", f"java main 메서드가 여러 파일에 있습니다: {names}"
    return mains[0].stem, None


def _python_entry(sources: tuple[Path, ...], root: Path) -> tuple[str, str | None]:
    if len(sources) == 1:
        return sources[0].name, None
    for p in sources:
        if p.name == "main.py":
            return p.relative_to(root).as_posix(), None
    return "", "python 소스가 여러 개면 main.py 가 있어야 합니다"


def _build_solution(unit: Path, expected: str, problem_dir: Path) -> tuple[Solution | None, str | None]:
    """(solution, warning) 을 돌려준다. 건너뛸 대상이면 solution 이 None 이다."""
    solutions_root = problem_dir / "solutions"
    rel_path = unit.relative_to(solutions_root).as_posix()

    if unit.is_dir():
        sources = tuple(sorted(p for p in unit.rglob("*") if p.is_file() and _language_of(p)))
        source_root = unit
    else:
        if _language_of(unit) is None:
            return None, f"지원하지 않는 확장자입니다. 건너뜁니다: solutions/{rel_path}"
        sources = (unit,)
        source_root = unit.parent

    if not sources:
        return None, f"소스 파일이 없습니다. 건너뜁니다: solutions/{rel_path}"

    languages = {_language_of(p) for p in sources}
    name = sanitize_name(rel_path)

    if len(languages) > 1:
        found = ", ".join(sorted(lang.value for lang in languages))
        return (
            Solution(
                name=name,
                rel_path=rel_path,
                path=unit,
                expected=expected,
                language=None,
                sources=sources,
                entry="",
                error=f"한 solution 에 두 언어가 섞였습니다: {found}",
            ),
            None,
        )

    language = next(iter(languages))
    entry, error = "", None
    if language is Language.JAVA:
        entry, error = _java_entry(sources)
    elif language is Language.PYTHON:
        entry, error = _python_entry(sources, source_root)

    return (
        Solution(
            name=name,
            rel_path=rel_path,
            path=unit,
            expected=expected,
            language=language,
            sources=sources,
            entry=entry,
            error=error,
        ),
        None,
    )


def discover_solutions(
    problem_dir: Path, *, filter_glob: str = ""
) -> tuple[list[Solution], list[str]]:
    solutions_root = problem_dir / "solutions"
    warnings: list[str] = []
    if not solutions_root.is_dir():
        return [], [f"solutions/ 디렉토리가 없습니다: {solutions_root}"]

    found: list[Solution] = []
    for child in sorted(solutions_root.iterdir()):
        if not child.is_dir():
            warnings.append(f"solutions/ 바로 아래의 파일은 무시합니다: {child.name}")
            continue
        if child.name not in EXPECTED_VERDICTS:
            warnings.append(
                f"알 수 없는 verdict 디렉토리입니다. 건너뜁니다: solutions/{child.name}"
            )
            continue

        for unit in sorted(child.iterdir()):
            solution, warning = _build_solution(unit, child.name, problem_dir)
            if warning:
                warnings.append(warning)
            if solution is None:
                continue
            if filter_glob and not fnmatch(solution.rel_path, filter_glob):
                continue
            found.append(solution)

    return found, warnings
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/unit/test_solutions.py -v`
Expected: PASS. 12개 전부

- [ ] **Step 5: 커밋**

```bash
git add src/icpc_verify/solutions.py tests/unit/test_solutions.py
git commit -m "feat: discover solutions and resolve language and entry point"
```

---

### Task 7: default validator

**Files:**
- Create: `src/icpc_verify/compare.py`
- Create: `tests/unit/test_compare.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `CompareFlags` dataclass: `case_sensitive: bool`, `space_change_sensitive: bool`,
    `float_absolute_tolerance: float | None`, `float_relative_tolerance: float | None`
  - `parse_compare_flags(flags: Sequence[str]) -> CompareFlags`
  - `compare_output(team: bytes, answer: bytes, flags: CompareFlags) -> tuple[bool, str]`
    반환은 `(accepted, message)`다. 통과면 `message`가 빈 문자열이다.
  - `CompareFlagError(ValueError)`

기본 동작은 Kattis default validator를 따른다. flag가 없으면 token 단위 비교이고 **대소문자를 구분하지 않는다**.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/unit/test_compare.py`:

```python
import pytest

from icpc_verify.compare import CompareFlagError, compare_output, parse_compare_flags

NONE = parse_compare_flags([])


def ok(team, answer, flags=NONE):
    accepted, message = compare_output(team.encode(), answer.encode(), flags)
    return accepted, message


def test_identical_output():
    assert ok("1 2 3\n", "1 2 3\n")[0]


def test_trailing_newline_is_ignored():
    assert ok("1 2 3", "1 2 3\n")[0]


def test_whitespace_amount_is_ignored_by_default():
    assert ok("1   2\n\n3\n", "1 2 3\n")[0]


def test_case_is_ignored_by_default():
    assert ok("YES\n", "yes\n")[0]


def test_case_sensitive_flag():
    flags = parse_compare_flags(["case_sensitive"])
    assert not ok("YES\n", "yes\n", flags)[0]
    assert ok("yes\n", "yes\n", flags)[0]


def test_space_change_sensitive_flag():
    flags = parse_compare_flags(["space_change_sensitive"])
    assert not ok("1  2\n", "1 2\n", flags)[0]
    assert ok("1 2\n", "1 2\n", flags)[0]


def test_token_count_mismatch_reports_position():
    accepted, message = ok("1 2\n", "1 2 3\n")
    assert not accepted
    assert "3" in message


def test_float_tolerance_sets_both():
    flags = parse_compare_flags(["float_tolerance", "1e-6"])
    assert flags.float_absolute_tolerance == pytest.approx(1e-6)
    assert flags.float_relative_tolerance == pytest.approx(1e-6)
    assert ok("1.0000001\n", "1.0\n", flags)[0]
    assert not ok("1.1\n", "1.0\n", flags)[0]


def test_absolute_tolerance_only():
    flags = parse_compare_flags(["float_absolute_tolerance", "0.5"])
    assert ok("1000000.4\n", "1000000.0\n", flags)[0]
    assert not ok("2.0\n", "1.0\n", flags)[0]


def test_relative_tolerance_only():
    flags = parse_compare_flags(["float_relative_tolerance", "0.01"])
    assert ok("101.0\n", "100.0\n", flags)[0]
    assert not ok("110.0\n", "100.0\n", flags)[0]


def test_either_tolerance_passing_is_enough():
    flags = parse_compare_flags(["float_tolerance", "0.01"])
    assert ok("0.005\n", "0.0\n", flags)[0]


def test_non_numeric_tokens_compare_as_text_even_with_float_flags():
    flags = parse_compare_flags(["float_tolerance", "1e-6"])
    assert ok("abc\n", "abc\n", flags)[0]
    assert not ok("abc\n", "abd\n", flags)[0]


def test_nan_never_matches():
    flags = parse_compare_flags(["float_tolerance", "1e-6"])
    assert not ok("nan\n", "1.0\n", flags)[0]


def test_unknown_flag_raises():
    with pytest.raises(CompareFlagError):
        parse_compare_flags(["no_such_flag"])


def test_tolerance_without_value_raises():
    with pytest.raises(CompareFlagError):
        parse_compare_flags(["float_tolerance"])


def test_invalid_utf8_is_tolerated():
    accepted, _ = compare_output(b"\xff\xfe\n", b"\xff\xfe\n", NONE)
    assert accepted
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/test_compare.py -v`
Expected: FAIL. `ModuleNotFoundError`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/icpc_verify/compare.py`:

```python
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
            self.float_absolute_tolerance is not None
            or self.float_relative_tolerance is not None
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

    for index, (t, a) in enumerate(zip(team_tokens, answer_tokens), start=1):
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

    for index, (lc, rc) in enumerate(zip(left, right), start=1):
        if lc != rc:
            return False, f"{index}번째 문자가 다릅니다: 기대 {rc!r}, 실제 {lc!r}"
    return False, f"길이가 다릅니다: 기대 {len(right)}, 실제 {len(left)}"


def compare_output(team: bytes, answer: bytes, flags: CompareFlags) -> tuple[bool, str]:
    team_text = _decode(team)
    answer_text = _decode(answer)
    if flags.space_change_sensitive:
        return _compare_exact(team_text, answer_text, flags)
    return _compare_tokens(team_text, answer_text, flags)
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/unit/test_compare.py -v`
Expected: PASS. 16개 전부

- [ ] **Step 5: 커밋**

```bash
git add src/icpc_verify/compare.py tests/unit/test_compare.py
git commit -m "feat: implement Kattis default output validator"
```

---

### Task 8: container 안의 실행 감시자

**Files:**
- Create: `image/runner.py`
- Create: `tests/unit/test_runner.py`

**Interfaces:**
- Consumes: 없음. container 안에서 독립 실행되는 script다. `icpc_verify` package를 import하지 않는다.
- Produces: CLI

```
python3 /usr/local/bin/runner.py \
  --input <path|-> --stdout <path> --stderr <path> --result <path> \
  --hard-kill <sec> --output-limit <bytes> -- <argv...>
```

`--result` 파일에 JSON을 쓴다:

```json
{"wall": 0.102, "cpu": 0.098, "max_rss_kib": 12345,
 "exit_code": 0, "signal": 0, "timed_out": false, "output_limit_exceeded": false}
```

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/unit/test_runner.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[2] / "image" / "runner.py"


def run(tmp_path, argv, *, stdin_text="", hard_kill=5.0, output_limit=1 << 20):
    stdin_path = tmp_path / "in"
    stdin_path.write_text(stdin_text, encoding="utf-8")
    result_path = tmp_path / "result.json"
    subprocess.run(
        [
            sys.executable, str(RUNNER),
            "--input", str(stdin_path),
            "--stdout", str(tmp_path / "out"),
            "--stderr", str(tmp_path / "err"),
            "--result", str(result_path),
            "--hard-kill", str(hard_kill),
            "--output-limit", str(output_limit),
            "--", *argv,
        ],
        check=True,
    )
    return json.loads(result_path.read_text(encoding="utf-8"))


def test_successful_run(tmp_path):
    r = run(tmp_path, [sys.executable, "-c", "print('hi')"])
    assert r["exit_code"] == 0
    assert r["signal"] == 0
    assert not r["timed_out"]
    assert not r["output_limit_exceeded"]
    assert r["wall"] > 0
    assert (tmp_path / "out").read_text() == "hi\n"


def test_stdin_is_piped(tmp_path):
    r = run(tmp_path, [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"],
            stdin_text="abc")
    assert r["exit_code"] == 0
    assert (tmp_path / "out").read_text() == "abc"


def test_nonzero_exit_is_recorded(tmp_path):
    r = run(tmp_path, [sys.executable, "-c", "raise SystemExit(3)"])
    assert r["exit_code"] == 3
    assert r["signal"] == 0


def test_signal_is_recorded(tmp_path):
    r = run(tmp_path, [sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGSEGV)"])
    assert r["signal"] == 11


def test_hard_kill(tmp_path):
    r = run(tmp_path, [sys.executable, "-c", "import time; time.sleep(30)"], hard_kill=0.5)
    assert r["timed_out"]
    assert r["wall"] >= 0.5
    assert r["wall"] < 5.0


def test_output_limit(tmp_path):
    code = "import sys\nwhile True: sys.stdout.write('x' * 4096)"
    r = run(tmp_path, [sys.executable, "-c", code], hard_kill=10.0, output_limit=64 * 1024)
    assert r["output_limit_exceeded"]
    assert r["wall"] < 10.0


def test_child_process_group_is_killed(tmp_path):
    code = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "time.sleep(30)\n"
    )
    r = run(tmp_path, [sys.executable, "-c", code], hard_kill=0.5)
    assert r["timed_out"]


def test_max_rss_is_reported(tmp_path):
    r = run(tmp_path, [sys.executable, "-c", "x = bytearray(64 * 1024 * 1024); print(len(x))"])
    assert r["max_rss_kib"] > 32 * 1024
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/test_runner.py -v`
Expected: FAIL. `image/runner.py` 가 없다

- [ ] **Step 3: 최소 구현을 쓴다**

`image/runner.py`:

```python
#!/usr/bin/env python3
"""judge container 안에서 solution 하나를 돌리고 시간과 메모리를 잰다.

icpc_verify package 에 의존하지 않는다. image 에 단독으로 들어간다.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import signal
import subprocess
import sys
import threading
import time


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--stdout", required=True)
    p.add_argument("--stderr", required=True)
    p.add_argument("--result", required=True)
    p.add_argument("--hard-kill", type=float, required=True)
    p.add_argument("--output-limit", type=int, required=True)
    p.add_argument("argv", nargs=argparse.REMAINDER)
    args = p.parse_args()
    if args.argv and args.argv[0] == "--":
        args.argv = args.argv[1:]
    if not args.argv:
        p.error("실행할 명령이 없습니다")
    return args


def watch_output_size(path: str, limit: int, stop: threading.Event) -> bool:
    """출력이 limit 을 넘으면 True 를 돌려준다."""
    while not stop.wait(0.05):
        try:
            if os.path.getsize(path) > limit:
                return True
        except OSError:
            pass
    return False


def main() -> int:
    args = parse_args()

    def set_child_limits() -> None:
        os.setsid()
        soft = int(args.hard_kill) + 2
        resource.setrlimit(resource.RLIMIT_CPU, (soft, soft + 1))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    exceeded = False
    stop = threading.Event()
    watcher_result: list[bool] = []

    with (
        open(args.input, "rb") as stdin_file,
        open(args.stdout, "wb") as stdout_file,
        open(args.stderr, "wb") as stderr_file,
    ):
        started = time.monotonic()
        child = subprocess.Popen(
            args.argv,
            stdin=stdin_file,
            stdout=stdout_file,
            stderr=stderr_file,
            preexec_fn=set_child_limits,
        )

        def watch() -> None:
            watcher_result.append(watch_output_size(args.stdout, args.output_limit, stop))

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()

        timed_out = False
        deadline = started + args.hard_kill
        while True:
            pid, status, usage = os.wait4(child.pid, os.WNOHANG)
            if pid != 0:
                break
            now = time.monotonic()
            if watcher_result and watcher_result[0]:
                exceeded = True
                os.killpg(child.pid, signal.SIGKILL)
                pid, status, usage = os.wait4(child.pid, 0)
                break
            if now >= deadline:
                timed_out = True
                os.killpg(child.pid, signal.SIGKILL)
                pid, status, usage = os.wait4(child.pid, 0)
                break
            time.sleep(0.002)

        wall = time.monotonic() - started
        stop.set()
        watcher.join(timeout=1.0)
        # os.wait4 로 직접 거둬들였으므로 Popen 이 다시 wait 하지 않게 한다
        child.returncode = 0

    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    if not exceeded:
        try:
            exceeded = os.path.getsize(args.stdout) > args.output_limit
        except OSError:
            exceeded = False

    result = {
        "wall": round(wall, 6),
        "cpu": round(usage.ru_utime + usage.ru_stime, 6),
        "max_rss_kib": int(usage.ru_maxrss),
        "exit_code": os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else -1,
        "signal": os.WTERMSIG(status) if os.WIFSIGNALED(status) else 0,
        "timed_out": timed_out,
        "output_limit_exceeded": exceeded,
    }
    with open(args.result, "w", encoding="utf-8") as f:
        json.dump(result, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/unit/test_runner.py -v`
Expected: PASS. 8개 전부

- [ ] **Step 5: 커밋**

```bash
git add image/runner.py tests/unit/test_runner.py
git commit -m "feat: add in-container process runner measuring time and memory"
```

---

### Task 9: judge image

**Files:**
- Create: `image/Dockerfile`
- Create: `image/python39.env`
- Create: `image/bench/bench.c`
- Create: `image/languages/cpp.sh`
- Create: `image/languages/c.sh`
- Create: `image/languages/java.sh`
- Create: `image/languages/python.sh`
- Create: `image/IMAGE_DIGEST`
- Create: `.github/workflows/publish-image.yml`
- Create: `tests/docker/test_image.py`

**Interfaces:**
- Consumes: `image/runner.py` (Task 8)
- Produces:
  - image `ghcr.io/suckzoo/icpc-judge`. 안에 다음이 있다.
    - `/usr/local/bin/runner.py`
    - `/usr/local/lib/icpc/compile.sh <language> <workdir> <entry> <flags> -- <sources...>`
    - `/usr/local/lib/icpc/run.sh <language> <workdir> <entry> <memory_mib>` — 실행 argv를 stdout에 한 줄씩 출력한다
    - `/usr/local/bin/bench` — machine factor benchmark
    - `/usr/local/lib/icpc/BENCH_REFERENCE` — image build 때 잰 기준 초
  - `image/IMAGE_DIGEST` — `ghcr.io/suckzoo/icpc-judge@sha256:...` 한 줄

- [ ] **Step 1: CPython 3.9 tarball을 고정한다**

Run:

```bash
gh release list --repo astral-sh/python-build-standalone --limit 3
```

가장 최근 tag를 `T`라고 하자. 그 tag의 체크섬에서 값을 뽑는다.

```bash
T=<위에서 고른 tag>
curl -sL "https://github.com/astral-sh/python-build-standalone/releases/download/$T/SHA256SUMS" \
  | grep -E 'cpython-3\.9\.[0-9]+\+.*-x86_64-unknown-linux-gnu-install_only\.tar\.gz$'
```

나온 sha256과 파일 이름으로 `image/python39.env`를 쓴다.

```sh
# image/python39.env — 위 명령으로 뽑은 실제 값으로 채운다
PY39_URL=https://github.com/astral-sh/python-build-standalone/releases/download/<T>/<파일이름>
PY39_SHA256=<sha256>
```

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/docker/test_image.py`:

```python
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "icpc-judge:test"

pytestmark = pytest.mark.docker


def sh(*argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, check=True, **kwargs).stdout


def dock(*argv):
    return sh("docker", "run", "--rm", IMAGE, *argv)


def test_cpp_supports_gnu20_and_avx2(tmp_path):
    src = tmp_path / "a.cpp"
    src.write_text(
        '#include <immintrin.h>\n'
        '#include <cstdio>\n'
        '#pragma GCC target("avx2")\n'
        "int main(){ __m256i v = _mm256_set1_epi32(2); "
        "printf(\"%d\\n\", _mm256_extract_epi32(v, 0)); }\n",
        encoding="utf-8",
    )
    out = sh(
        "docker", "run", "--rm", "-v", f"{tmp_path}:/w", IMAGE,
        "bash", "-c",
        "/usr/local/lib/icpc/compile.sh cpp /w '' '' -- /w/a.cpp && /w/bin",
    )
    assert out.strip() == "2"


def test_c_gnu11(tmp_path):
    src = tmp_path / "a.c"
    src.write_text('#include <stdio.h>\nint main(void){ puts("ok"); return 0; }\n', encoding="utf-8")
    out = sh(
        "docker", "run", "--rm", "-v", f"{tmp_path}:/w", IMAGE,
        "bash", "-c",
        "/usr/local/lib/icpc/compile.sh c /w '' '' -- /w/a.c && /w/bin",
    )
    assert out.strip() == "ok"


def test_java_21():
    version = subprocess.run(
        ["docker", "run", "--rm", IMAGE, "java", "-version"],
        capture_output=True, text=True, check=True,
    ).stderr
    assert '"21' in version


def test_python_39():
    assert dock("python3.9", "--version").startswith("Python 3.9")


def test_runner_is_installed():
    assert "usage" in dock("python3", "/usr/local/bin/runner.py", "--help").lower()


def test_bench_prints_seconds():
    assert float(dock("/usr/local/bin/bench").strip()) > 0


def test_bench_reference_is_baked_in():
    value = dock("cat", "/usr/local/lib/icpc/BENCH_REFERENCE").strip()
    assert float(value) > 0
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/docker -v -m docker`
Expected: FAIL. image `icpc-judge:test` 가 없다

- [ ] **Step 4: benchmark를 쓴다**

`image/bench/bench.c`:

```c
/* machine factor 측정용 고정 benchmark.
   정수, 부동소수, 메모리 접근을 섞는다. 결과 초를 stdout 에 출력한다. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#define N (1 << 22)

int main(void) {
    uint32_t *a = malloc(N * sizeof(uint32_t));
    double acc = 0.0;
    uint64_t h = 1469598103934665603ULL;

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    for (int i = 0; i < N; i++) a[i] = (uint32_t)(i * 2654435761u);
    for (int round = 0; round < 8; round++) {
        for (int i = 0; i < N; i++) {
            h ^= a[(i * 7919u) & (N - 1)];
            h *= 1099511628211ULL;
            acc += (double)(h >> 40) * 1e-9;
        }
    }

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double seconds = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) * 1e-9;
    fprintf(stderr, "%f %llu\n", acc, (unsigned long long)h);
    printf("%.6f\n", seconds);
    free(a);
    return 0;
}
```

- [ ] **Step 5: 언어 script를 쓴다**

`image/languages/cpp.sh`:

각 script는 공통 규약을 지킨다. `set -eu`를 쓰므로 `[ ... ] && shift` 형태를 쓰면 조건이
거짓일 때 script 전체가 죽는다. 반드시 `if` 문으로 쓴다.

```sh
#!/bin/sh
# compile: cpp.sh compile <workdir> <entry> <flags> -- <sources...>
# run:     cpp.sh run <workdir> <entry> <memory_mib>
set -eu
mode=$1; workdir=$2; shift 3   # $3 은 entry 이며 C++ 에서는 쓰지 않는다

if [ "$mode" = "compile" ]; then
    flags=$1; shift
    if [ "${1-}" = "--" ]; then shift; fi
    if [ -z "$flags" ]; then
        flags="-x c++ -Wall -O2 -static -pipe -std=gnu++20"
    fi
    # shellcheck disable=SC2086
    exec g++ $flags -o "$workdir/bin" "$@" -lm
fi

echo "$workdir/bin"
```

`image/languages/c.sh`:

```sh
#!/bin/sh
set -eu
mode=$1; workdir=$2; shift 3

if [ "$mode" = "compile" ]; then
    flags=$1; shift
    if [ "${1-}" = "--" ]; then shift; fi
    if [ -z "$flags" ]; then
        flags="-x c -Wall -O2 -static -pipe -std=gnu11"
    fi
    # shellcheck disable=SC2086
    exec gcc $flags -o "$workdir/bin" "$@" -lm
fi

echo "$workdir/bin"
```

`image/languages/java.sh`:

```sh
#!/bin/sh
set -eu
mode=$1; workdir=$2; entry=$3; shift 3

if [ "$mode" = "compile" ]; then
    flags=$1; shift
    if [ "${1-}" = "--" ]; then shift; fi
    if [ -z "$flags" ]; then
        flags="-encoding UTF-8"
    fi
    # shellcheck disable=SC2086
    exec javac $flags -sourcepath "$workdir" -d "$workdir" "$@"
fi

memory_mib=$1
heap=$((memory_mib - 256))
if [ "$heap" -lt 256 ]; then heap=256; fi
printf '%s\n' java -Xrs -XX:+UseSerialGC -Xss64m "-Xmx${heap}m" -cp "$workdir" "$entry"
```

`image/languages/python.sh`:

```sh
#!/bin/sh
set -eu
mode=$1; workdir=$2; entry=$3; shift 3

if [ "$mode" = "compile" ]; then
    # 나머지 인자(flags, --, sources)는 쓰지 않는다. entry 만 문법 검사한다.
    exec python3.9 -m py_compile "$workdir/$entry"
fi

printf '%s\n' python3.9 "$workdir/$entry"
```

`image/languages/` 에 공통 진입점 두 개를 더 만든다.

`image/languages/compile.sh`:

```sh
#!/bin/sh
# compile.sh <language> <workdir> <entry> <flags> -- <sources...>
set -eu
lang=$1; shift
exec "/usr/local/lib/icpc/languages/${lang}.sh" compile "$@"
```

`image/languages/run.sh`:

```sh
#!/bin/sh
# run.sh <language> <workdir> <entry> <memory_mib>
# 실행 argv 를 한 줄에 하나씩 stdout 에 출력한다.
set -eu
lang=$1; shift
exec "/usr/local/lib/icpc/languages/${lang}.sh" run "$@"
```

- [ ] **Step 6: Dockerfile을 쓴다**

`image/Dockerfile`:

```dockerfile
FROM ubuntu:24.04

ARG PY39_URL
ARG PY39_SHA256

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        g++-13 gcc-13 openjdk-21-jdk-headless \
        python3 ca-certificates curl xz-utils \
    && ln -sf /usr/bin/g++-13 /usr/bin/g++ \
    && ln -sf /usr/bin/gcc-13 /usr/bin/gcc \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "$PY39_URL" -o /tmp/py39.tar.gz \
    && echo "$PY39_SHA256  /tmp/py39.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/python39 \
    && tar -xzf /tmp/py39.tar.gz -C /opt/python39 --strip-components=1 \
    && ln -sf /opt/python39/bin/python3.9 /usr/local/bin/python3.9 \
    && rm /tmp/py39.tar.gz

COPY runner.py /usr/local/bin/runner.py
COPY languages/ /usr/local/lib/icpc/languages/
COPY bench/bench.c /tmp/bench.c

RUN chmod +x /usr/local/bin/runner.py /usr/local/lib/icpc/languages/*.sh \
    && ln -sf /usr/local/lib/icpc/languages/compile.sh /usr/local/lib/icpc/compile.sh \
    && ln -sf /usr/local/lib/icpc/languages/run.sh /usr/local/lib/icpc/run.sh \
    && gcc -O2 -o /usr/local/bin/bench /tmp/bench.c && rm /tmp/bench.c

# 기준 시간을 3회 중앙값으로 잰다
RUN set -eu; \
    a=$(/usr/local/bin/bench 2>/dev/null); \
    b=$(/usr/local/bin/bench 2>/dev/null); \
    c=$(/usr/local/bin/bench 2>/dev/null); \
    printf '%s\n%s\n%s\n' "$a" "$b" "$c" | sort -g | sed -n 2p \
      > /usr/local/lib/icpc/BENCH_REFERENCE; \
    cat /usr/local/lib/icpc/BENCH_REFERENCE

WORKDIR /work
```

- [ ] **Step 7: image를 build하고 테스트한다**

Run:

```bash
set -a && . image/python39.env && set +a
docker build --platform linux/amd64 \
  --build-arg PY39_URL="$PY39_URL" --build-arg PY39_SHA256="$PY39_SHA256" \
  -t icpc-judge:test image/
python -m pytest tests/docker -v -m docker
```

Expected: build 성공, 테스트 7개 PASS

- [ ] **Step 8: publish workflow를 쓴다**

`.github/workflows/publish-image.yml`:

```yaml
name: publish-image
on:
  push:
    branches: [main]
    paths:
      - "image/**"
      - ".github/workflows/publish-image.yml"
  workflow_dispatch:

permissions:
  contents: read
  packages: write

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Load python 3.9 pin
        run: cat image/python39.env >> "$GITHUB_ENV"
      - uses: docker/build-push-action@v6
        id: build
        with:
          context: image
          platforms: linux/amd64
          push: true
          tags: ghcr.io/suckzoo/icpc-judge:latest
          build-args: |
            PY39_URL=${{ env.PY39_URL }}
            PY39_SHA256=${{ env.PY39_SHA256 }}
      - name: Print digest to pin
        run: |
          echo "image/IMAGE_DIGEST 에 아래 한 줄을 커밋하세요"
          echo "ghcr.io/suckzoo/icpc-judge@${{ steps.build.outputs.digest }}"
```

- [ ] **Step 9: 로컬 digest를 임시로 채운다**

`image/IMAGE_DIGEST`에 로컬 build 결과를 넣어 계획 1의 나머지 task가 돌아가게 한다.
publish workflow가 처음 돌면 ghcr digest로 바꾼다.

Run:

```bash
echo "icpc-judge:test" > image/IMAGE_DIGEST
```

- [ ] **Step 10: 커밋**

```bash
git add image .github/workflows/publish-image.yml tests/docker
git commit -m "feat: build judge image with gcc 13, jdk 21, cpython 3.9 and bench"
```

---

### Task 10: CPU 격리 계획

**Files:**
- Create: `src/icpc_verify/cpu.py`
- Create: `tests/unit/test_cpu.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `CpuPlan` dataclass: `judge_cpu: int`, `offline: tuple[int, ...]`, `isolated: bool`, `warnings: tuple[str, ...]`
  - `read_topology(sysfs: Path) -> dict[int, tuple[int, ...]]` — cpu 번호 -> 같은 core의 thread 목록
  - `plan_cpu(topology: dict[int, tuple[int, ...]], *, requested: int | None, offline_sibling: bool) -> CpuPlan`
  - `check_arch_and_flags(machine: str, cpu_flags: set[str], required: Sequence[str]) -> None`
  - `CpuError(Exception)`

`plan_cpu`와 `check_arch_and_flags`는 순수 함수다. sysfs 읽기와 offline 적용은 따로 둔다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/unit/test_cpu.py`:

```python
import pytest

from icpc_verify.cpu import CpuError, check_arch_and_flags, plan_cpu, read_topology

TWO_VCPU = {0: (0, 1), 1: (0, 1)}
FOUR_VCPU = {0: (0, 1), 1: (0, 1), 2: (2, 3), 3: (2, 3)}
NO_SMT_FOUR = {0: (0,), 1: (1,), 2: (2,), 3: (3,)}


def test_read_topology(tmp_path):
    for cpu, siblings in (("cpu0", "0-1"), ("cpu1", "0-1"), ("cpu2", "2,3"), ("cpu3", "2,3")):
        d = tmp_path / "cpu" / cpu / "topology"
        d.mkdir(parents=True)
        (d / "thread_siblings_list").write_text(siblings + "\n", encoding="utf-8")
    assert read_topology(tmp_path / "cpu") == FOUR_VCPU


def test_two_vcpu_pins_highest_and_does_not_offline():
    plan = plan_cpu(TWO_VCPU, requested=None, offline_sibling=True)
    assert plan.judge_cpu == 1
    assert plan.offline == ()
    assert plan.isolated is False
    assert any("best-effort" in w for w in plan.warnings)


def test_four_vcpu_uses_last_core_and_offlines_sibling():
    plan = plan_cpu(FOUR_VCPU, requested=None, offline_sibling=True)
    assert plan.judge_cpu == 2
    assert plan.offline == (3,)
    assert plan.isolated is True


def test_offline_sibling_disabled():
    plan = plan_cpu(FOUR_VCPU, requested=None, offline_sibling=False)
    assert plan.judge_cpu == 2
    assert plan.offline == ()
    assert plan.isolated is False


def test_no_smt_needs_no_offline():
    plan = plan_cpu(NO_SMT_FOUR, requested=None, offline_sibling=True)
    assert plan.judge_cpu == 3
    assert plan.offline == ()
    assert plan.isolated is True


def test_requested_cpu_wins():
    plan = plan_cpu(FOUR_VCPU, requested=1, offline_sibling=True)
    assert plan.judge_cpu == 1
    assert plan.offline == ()


def test_requested_cpu_out_of_range():
    with pytest.raises(CpuError):
        plan_cpu(FOUR_VCPU, requested=9, offline_sibling=True)


def test_empty_topology():
    with pytest.raises(CpuError):
        plan_cpu({}, requested=None, offline_sibling=True)


def test_arch_check_rejects_arm():
    with pytest.raises(CpuError, match="x86_64"):
        check_arch_and_flags("aarch64", {"neon"}, ["avx2"])


def test_flag_check_rejects_missing_avx2():
    with pytest.raises(CpuError, match="avx2"):
        check_arch_and_flags("x86_64", {"sse2"}, ["avx2"])


def test_arch_and_flags_pass():
    check_arch_and_flags("x86_64", {"sse2", "avx2", "avx512f"}, ["avx2"])
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/test_cpu.py -v`
Expected: FAIL. `ModuleNotFoundError`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/icpc_verify/cpu.py`:

```python
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
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/unit/test_cpu.py -v`
Expected: PASS. 11개 전부

- [ ] **Step 5: 커밋**

```bash
git add src/icpc_verify/cpu.py tests/unit/test_cpu.py
git commit -m "feat: plan judge cpu from thread sibling topology"
```

---

### Task 11: docker sandbox 래퍼

**Files:**
- Create: `src/icpc_verify/sandbox.py`
- Create: `tests/docker/test_sandbox.py`

**Interfaces:**
- Consumes: `image/IMAGE_DIGEST` (Task 9)
- Produces:
  - `SandboxSpec` dataclass: `image: str`, `cpuset: int`, `memory_mib: int`,
    `binds: tuple[tuple[Path, str, str], ...]`, `argv: tuple[str, ...]`, `timeout: float`
  - `SandboxResult` dataclass: `exit_code: int`, `oom_killed: bool`, `stdout: bytes`, `stderr: bytes`, `timed_out: bool`
  - `run_sandbox(spec: SandboxSpec) -> SandboxResult`
  - `SandboxError(Exception)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/docker/test_sandbox.py`:

```python
from pathlib import Path

import pytest

from icpc_verify.sandbox import SandboxSpec, run_sandbox

pytestmark = pytest.mark.docker

IMAGE = (Path(__file__).resolve().parents[2] / "image" / "IMAGE_DIGEST").read_text().strip()


def spec(argv, **kwargs):
    defaults = dict(image=IMAGE, cpuset=0, memory_mib=512, binds=(), timeout=30.0)
    defaults.update(kwargs)
    return SandboxSpec(argv=tuple(argv), **defaults)


def test_runs_and_captures_stdout():
    r = run_sandbox(spec(["echo", "hello"]))
    assert r.exit_code == 0
    assert r.stdout.strip() == b"hello"
    assert not r.oom_killed


def test_nonzero_exit():
    r = run_sandbox(spec(["sh", "-c", "exit 7"]))
    assert r.exit_code == 7


def test_oom_is_detected():
    r = run_sandbox(spec(
        ["python3", "-c", "x = bytearray(400 * 1024 * 1024); print(len(x))"],
        memory_mib=64,
    ))
    assert r.oom_killed


def test_network_is_disabled():
    r = run_sandbox(spec(["python3", "-c",
                          "import socket; socket.create_connection(('1.1.1.1', 80), 2)"]))
    assert r.exit_code != 0


def test_bind_mount_is_readable(tmp_path):
    (tmp_path / "f.txt").write_text("bound\n", encoding="utf-8")
    r = run_sandbox(spec(["cat", "/mnt/f.txt"], binds=((tmp_path, "/mnt", "ro"),)))
    assert r.stdout.strip() == b"bound"


def test_bind_mount_ro_is_not_writable(tmp_path):
    r = run_sandbox(spec(["sh", "-c", "echo x > /mnt/new"], binds=((tmp_path, "/mnt", "ro"),)))
    assert r.exit_code != 0


def test_cpuset_is_applied():
    r = run_sandbox(spec(["cat", "/sys/fs/cgroup/cpuset.cpus.effective"], cpuset=0))
    assert r.stdout.strip() == b"0"


def test_timeout(tmp_path):
    r = run_sandbox(spec(["sleep", "30"], timeout=2.0))
    assert r.timed_out
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/docker/test_sandbox.py -v -m docker`
Expected: FAIL. `ModuleNotFoundError: No module named 'icpc_verify.sandbox'`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/icpc_verify/sandbox.py`:

```python
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
        "run", "--name", name,
        "--cpuset-cpus", str(spec.cpuset),
        "--cpuset-mems", "0",
        "--memory", f"{spec.memory_mib}m",
        "--memory-swap", f"{spec.memory_mib}m",
        "--pids-limit", "256",
        "--network", "none",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=64m",
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
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/docker/test_sandbox.py -v -m docker`
Expected: PASS. 8개 전부

- [ ] **Step 5: 커밋**

```bash
git add src/icpc_verify/sandbox.py tests/docker/test_sandbox.py
git commit -m "feat: run isolated docker sandbox with cpuset and memory limits"
```

---

### Task 12: compile 단계

**Files:**
- Create: `src/icpc_verify/compile.py`
- Create: `tests/docker/test_compile.py`

**Interfaces:**
- Consumes: `icpc_verify.sandbox`, `icpc_verify.solutions.Solution`, `icpc_verify.solutions.Language`
- Produces:
  - `CompileOptions` dataclass: `image: str`, `cpuset: int`, `flags: dict[Language, str]`, `timeout: float`
  - `CompileOutcome` dataclass: `ok: bool`, `log: str`, `work_dir: Path`, `run_argv: tuple[str, ...]`
  - `compile_solution(solution: Solution, work_dir: Path, memory_mib: int, options: CompileOptions) -> CompileOutcome`
    `work_dir`에 소스와 산출물을 둔다. `run_argv`는 container 안에서 실행할 argv다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/docker/test_compile.py`:

```python
from pathlib import Path

import pytest

from icpc_verify.compile import CompileOptions, compile_solution
from icpc_verify.solutions import discover_solutions

pytestmark = pytest.mark.docker

IMAGE = (Path(__file__).resolve().parents[2] / "image" / "IMAGE_DIGEST").read_text().strip()
OPTIONS = CompileOptions(image=IMAGE, cpuset=0, flags={}, timeout=120.0)

HELLO = {
    "accepted/a.cpp": '#include <cstdio>\nint main(){puts("hi");}\n',
    "accepted/b.c": '#include <stdio.h>\nint main(){puts("hi");return 0;}\n',
    "accepted/Main.java": 'public class Main{public static void main(String[] a){System.out.println("hi");}}\n',
    "accepted/s.py": 'print("hi")\n',
}


def make_problem(tmp_path, rel, text):
    p = tmp_path / "solutions" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("rel", sorted(HELLO))
def test_each_language_compiles_and_runs(tmp_path, rel):
    make_problem(tmp_path, rel, HELLO[rel])
    sols, _ = discover_solutions(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    outcome = compile_solution(sols[0], work, 2048, OPTIONS)
    assert outcome.ok, outcome.log
    assert outcome.run_argv


def test_compile_error_is_reported(tmp_path):
    make_problem(tmp_path, "accepted/bad.cpp", "int main(){ this is not c++ }\n")
    sols, _ = discover_solutions(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    outcome = compile_solution(sols[0], work, 2048, OPTIONS)
    assert not outcome.ok
    assert "error" in outcome.log.lower()


def test_avx2_pragma_compiles(tmp_path):
    make_problem(
        tmp_path,
        "accepted/simd.cpp",
        '#pragma GCC target("avx2")\n'
        "#include <immintrin.h>\n#include <cstdio>\n"
        "int main(){__m256i v=_mm256_set1_epi32(7);printf(\"%d\\n\",_mm256_extract_epi32(v,0));}\n",
    )
    sols, _ = discover_solutions(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    assert compile_solution(sols[0], work, 2048, OPTIONS).ok


def test_discovery_error_becomes_compile_failure(tmp_path):
    make_problem(tmp_path, "accepted/Helper.java", "public class Helper {}\n")
    sols, _ = discover_solutions(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    outcome = compile_solution(sols[0], work, 2048, OPTIONS)
    assert not outcome.ok
    assert "main" in outcome.log
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/docker/test_compile.py -v -m docker`
Expected: FAIL. `ModuleNotFoundError: No module named 'icpc_verify.compile'`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/icpc_verify/compile.py`:

```python
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
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/docker/test_compile.py -v -m docker`
Expected: PASS. 7개 전부 (parametrize 4개 + 3개)

- [ ] **Step 5: 커밋**

```bash
git add src/icpc_verify/compile.py tests/docker/test_compile.py
git commit -m "feat: compile solutions inside judge container"
```

---

### Task 13: verdict 판정

**Files:**
- Create: `src/icpc_verify/results.py`
- Create: `tests/unit/test_results.py`

**Interfaces:**
- Consumes: `icpc_verify.verdicts`, `icpc_verify.timelimits.TimeLimits`
- Produces:
  - `RunMeasurement` dataclass: `wall: float`, `cpu: float`, `max_rss_kib: int`,
    `exit_code: int`, `signal: int`, `timed_out: bool`, `output_limit_exceeded: bool`, `oom_killed: bool`
  - `classify_run(m: RunMeasurement, limits: TimeLimits, compare_ok: bool, compare_message: str) -> tuple[str, str]`
    반환은 `(verdict, message)`다.
  - `TestCaseResult` dataclass: `id`, `group`, `verdict`, `wall`, `cpu`, `mem_kib`, `exit_code`, `message`
  - `SolutionResult` dataclass: `name`, `rel_path`, `expected`, `language`, `verdict`,
    `testcases: list[TestCaseResult]`, `compile_log`, `machine_factor`, `cpu_isolated`, `warnings`
  - `solution_verdict(testcases: Sequence[TestCaseResult]) -> str`
  - `matches_expectation(expected: str, actual: str, mode: str) -> bool` — `mode`는 `"exact"` 또는 `"any-rejected"`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/unit/test_results.py`:

```python
import pytest

from icpc_verify import verdicts
from icpc_verify.results import (
    RunMeasurement,
    TestCaseResult,
    classify_run,
    matches_expectation,
    solution_verdict,
)
from icpc_verify.timelimits import make_time_limits

LIMITS = make_time_limits(1.0, "2s|20%")


def measure(**kwargs):
    base = dict(
        wall=0.1, cpu=0.1, max_rss_kib=1000, exit_code=0, signal=0,
        timed_out=False, output_limit_exceeded=False, oom_killed=False,
    )
    base.update(kwargs)
    return RunMeasurement(**base)


def test_accepted():
    assert classify_run(measure(), LIMITS, True, "")[0] == verdicts.ACCEPTED


def test_wrong_answer():
    verdict, message = classify_run(measure(), LIMITS, False, "token 1 이 다릅니다")
    assert verdict == verdicts.WRONG_ANSWER
    assert "token 1" in message


def test_wall_over_limit_is_tle_even_when_output_is_correct():
    assert classify_run(measure(wall=1.05), LIMITS, True, "")[0] == verdicts.TIME_LIMIT_EXCEEDED


def test_wall_exactly_at_limit_passes():
    assert classify_run(measure(wall=1.0), LIMITS, True, "")[0] == verdicts.ACCEPTED


def test_hard_kill_is_tle():
    assert classify_run(measure(wall=3.0, timed_out=True), LIMITS, False, "")[0] == (
        verdicts.TIME_LIMIT_EXCEEDED
    )


def test_oom_is_run_time_error():
    verdict, message = classify_run(measure(oom_killed=True, exit_code=137), LIMITS, False, "")
    assert verdict == verdicts.RUN_TIME_ERROR
    assert "메모리" in message


def test_signal_is_run_time_error():
    verdict, message = classify_run(measure(signal=11, exit_code=-1), LIMITS, False, "")
    assert verdict == verdicts.RUN_TIME_ERROR
    assert "11" in message


def test_nonzero_exit_is_run_time_error():
    assert classify_run(measure(exit_code=1), LIMITS, False, "")[0] == verdicts.RUN_TIME_ERROR


def test_output_limit_is_wrong_answer():
    verdict, message = classify_run(measure(output_limit_exceeded=True), LIMITS, False, "")
    assert verdict == verdicts.WRONG_ANSWER
    assert "OLE" in message


def test_tle_beats_run_time_error():
    verdict, _ = classify_run(measure(wall=2.0, timed_out=True, signal=9), LIMITS, False, "")
    assert verdict == verdicts.TIME_LIMIT_EXCEEDED


def case(verdict):
    return TestCaseResult(
        id="01", group="", verdict=verdict, wall=0.1, cpu=0.1,
        mem_kib=100, exit_code=0, message="",
    )


def test_solution_verdict_all_accepted():
    assert solution_verdict([case(verdicts.ACCEPTED)] * 3) == verdicts.ACCEPTED


def test_solution_verdict_first_failure_wins():
    cases = [case(verdicts.ACCEPTED), case(verdicts.RUN_TIME_ERROR), case(verdicts.WRONG_ANSWER)]
    assert solution_verdict(cases) == verdicts.RUN_TIME_ERROR


def test_solution_verdict_ignores_not_run():
    cases = [case(verdicts.ACCEPTED), case(verdicts.NOT_RUN)]
    assert solution_verdict(cases) == verdicts.ACCEPTED


def test_solution_verdict_empty():
    assert solution_verdict([]) == verdicts.JUDGE_ERROR


@pytest.mark.parametrize(
    ("expected", "actual", "mode", "result"),
    [
        ("accepted", "accepted", "exact", True),
        ("wrong_answer", "wrong_answer", "exact", True),
        ("wrong_answer", "run_time_error", "exact", False),
        ("wrong_answer", "run_time_error", "any-rejected", True),
        ("accepted", "wrong_answer", "any-rejected", False),
        ("time_limit_exceeded", "accepted", "any-rejected", False),
    ],
)
def test_matches_expectation(expected, actual, mode, result):
    assert matches_expectation(expected, actual, mode) is result
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/test_results.py -v`
Expected: FAIL. `ModuleNotFoundError`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/icpc_verify/results.py`:

```python
"""측정값을 verdict 으로 바꾸고 결과 구조를 정의한다.

판정 우선순위: 시간 -> 메모리/비정상 종료 -> 출력 크기 -> 출력 내용.
wall <= limit 일 때만 통과다. overshoot 는 판정 경계가 아니다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from . import verdicts
from .timelimits import TimeLimits


@dataclass(frozen=True)
class RunMeasurement:
    wall: float
    cpu: float
    max_rss_kib: int
    exit_code: int
    signal: int
    timed_out: bool
    output_limit_exceeded: bool
    oom_killed: bool


@dataclass
class TestCaseResult:
    id: str
    group: str
    verdict: str
    wall: float
    cpu: float
    mem_kib: int
    exit_code: int
    message: str


@dataclass
class SolutionResult:
    name: str
    rel_path: str
    expected: str
    language: str
    verdict: str
    testcases: list[TestCaseResult] = field(default_factory=list)
    compile_log: str = ""
    machine_factor: float = 1.0
    cpu_isolated: bool = False
    warnings: list[str] = field(default_factory=list)


def classify_run(
    m: RunMeasurement,
    limits: TimeLimits,
    compare_ok: bool,
    compare_message: str,
) -> tuple[str, str]:
    if m.timed_out or m.wall > limits.limit:
        return (
            verdicts.TIME_LIMIT_EXCEEDED,
            f"wall {m.wall:.3f}s 가 시간제한 {limits.limit:.3f}s 를 넘었습니다",
        )
    if m.oom_killed:
        return verdicts.RUN_TIME_ERROR, "메모리 제한을 넘어 kill 되었습니다"
    if m.signal:
        return verdicts.RUN_TIME_ERROR, f"signal {m.signal} 로 종료했습니다"
    if m.exit_code != 0:
        return verdicts.RUN_TIME_ERROR, f"exit code {m.exit_code} 로 종료했습니다"
    if m.output_limit_exceeded:
        return verdicts.WRONG_ANSWER, "OLE. 출력이 제한을 넘었습니다"
    if not compare_ok:
        return verdicts.WRONG_ANSWER, compare_message
    return verdicts.ACCEPTED, ""


def solution_verdict(testcases: Sequence[TestCaseResult]) -> str:
    judged = [c for c in testcases if c.verdict != verdicts.NOT_RUN]
    if not judged:
        return verdicts.JUDGE_ERROR
    for case in judged:
        if case.verdict != verdicts.ACCEPTED:
            return case.verdict
    return verdicts.ACCEPTED


def matches_expectation(expected: str, actual: str, mode: str) -> bool:
    if mode == "exact":
        return expected == actual
    if mode == "any-rejected":
        if expected == verdicts.ACCEPTED:
            return actual == verdicts.ACCEPTED
        return actual != verdicts.ACCEPTED
    raise ValueError(f"알 수 없는 verdict-match 모드입니다: {mode!r}")
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/unit/test_results.py -v`
Expected: PASS. 20개 전부

- [ ] **Step 5: 커밋**

```bash
git add src/icpc_verify/results.py tests/unit/test_results.py
git commit -m "feat: classify run measurements into verdicts"
```

---

### Task 14: judge 본체

**Files:**
- Create: `src/icpc_verify/judge.py`
- Create: `tests/docker/test_judge.py`
- Create: `tests/fixtures/plain/problem.yaml`
- Create: `tests/fixtures/plain/data/01.in`
- Create: `tests/fixtures/plain/data/01.ans`
- Create: `tests/fixtures/plain/data/02.in`
- Create: `tests/fixtures/plain/data/02.ans`
- Create: `tests/fixtures/plain/solutions/accepted/main.cpp`
- Create: `tests/fixtures/plain/solutions/accepted/alt.py`
- Create: `tests/fixtures/plain/solutions/wrong_answer/off_by_one.cpp`
- Create: `tests/fixtures/plain/solutions/time_limit_exceeded/sleepy.cpp`
- Create: `tests/fixtures/plain/solutions/run_time_error/crash.c`

**Interfaces:**
- Consumes: `icpc_verify.compile`, `icpc_verify.sandbox`, `icpc_verify.compare`,
  `icpc_verify.results`, `icpc_verify.testdata`, `icpc_verify.solutions`,
  `icpc_verify.timelimits`, `icpc_verify.cpu`
- Produces:
  - `JudgeOptions` dataclass: `image: str`, `cpuset: int`, `judge_all: bool`,
    `output_limit_mib: int`, `compile_flags: dict[Language, str]`, `machine_factor: float`,
    `cpu_isolated: bool`, `warnings: list[str]`
  - `judge_solution(problem_dir: Path, config: ProblemConfig, solution: Solution, testcases: Sequence[TestCase], limits: TimeLimits, work_root: Path, options: JudgeOptions) -> SolutionResult`
  - `measure_machine_factor(image: str, cpuset: int, rounds: int = 3) -> float`

문제는 "두 정수를 더해 출력하라"이고 시간제한은 1초다.

- [ ] **Step 1: fixture를 만든다**

`tests/fixtures/plain/problem.yaml`:

```yaml
problem_format_version: 2023-07-draft
name: Add Two Numbers
type: pass-fail
limits:
  time_limit: 1.0
  memory: 512
```

`tests/fixtures/plain/data/01.in`: `1 2\n`
`tests/fixtures/plain/data/01.ans`: `3\n`
`tests/fixtures/plain/data/02.in`: `10 20\n`
`tests/fixtures/plain/data/02.ans`: `30\n`

`tests/fixtures/plain/solutions/accepted/main.cpp`:

```cpp
#include <cstdio>
int main() {
    long long a, b;
    if (scanf("%lld %lld", &a, &b) != 2) return 1;
    printf("%lld\n", a + b);
    return 0;
}
```

`tests/fixtures/plain/solutions/accepted/alt.py`:

```python
a, b = map(int, input().split())
print(a + b)
```

`tests/fixtures/plain/solutions/wrong_answer/off_by_one.cpp`:

```cpp
#include <cstdio>
int main() {
    long long a, b;
    if (scanf("%lld %lld", &a, &b) != 2) return 1;
    printf("%lld\n", a + b + 1);
    return 0;
}
```

`tests/fixtures/plain/solutions/time_limit_exceeded/sleepy.cpp`:

```cpp
#include <chrono>
#include <cstdio>
#include <thread>
int main() {
    std::this_thread::sleep_for(std::chrono::seconds(10));
    puts("0");
    return 0;
}
```

`tests/fixtures/plain/solutions/run_time_error/crash.c`:

```c
#include <stdlib.h>
int main(void) {
    abort();
}
```

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/docker/test_judge.py`:

```python
from pathlib import Path

import pytest

from icpc_verify import verdicts
from icpc_verify.judge import JudgeOptions, judge_solution, measure_machine_factor
from icpc_verify.problemcfg import load_problem_config
from icpc_verify.solutions import discover_solutions
from icpc_verify.testdata import collect_testcases
from icpc_verify.timelimits import make_time_limits

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
IMAGE = (ROOT / "image" / "IMAGE_DIGEST").read_text().strip()
FIXTURE = ROOT / "tests" / "fixtures" / "plain"


def options(**kwargs):
    base = dict(
        image=IMAGE, cpuset=0, judge_all=False, output_limit_mib=8,
        compile_flags={}, machine_factor=1.0, cpu_isolated=False, warnings=[],
    )
    base.update(kwargs)
    return JudgeOptions(**base)


def judge(tmp_path, rel_path, **kwargs):
    config = load_problem_config(FIXTURE, default_time_limit=1.0, default_memory_mib=2048)
    limits = make_time_limits(config.time_limit, "2s|20%")
    cases = collect_testcases(FIXTURE)
    sols, _ = discover_solutions(FIXTURE)
    solution = next(s for s in sols if s.rel_path == rel_path)
    return judge_solution(FIXTURE, config, solution, cases, limits, tmp_path, options(**kwargs))


@pytest.mark.parametrize(
    ("rel_path", "expected"),
    [
        ("accepted/main.cpp", verdicts.ACCEPTED),
        ("accepted/alt.py", verdicts.ACCEPTED),
        ("wrong_answer/off_by_one.cpp", verdicts.WRONG_ANSWER),
        ("time_limit_exceeded/sleepy.cpp", verdicts.TIME_LIMIT_EXCEEDED),
        ("run_time_error/crash.c", verdicts.RUN_TIME_ERROR),
    ],
)
def test_verdicts_match_directories(tmp_path, rel_path, expected):
    result = judge(tmp_path, rel_path)
    assert result.verdict == expected
    assert result.expected == rel_path.split("/")[0]


def test_accepted_runs_every_testcase(tmp_path):
    result = judge(tmp_path, "accepted/main.cpp")
    assert [c.verdict for c in result.testcases] == [verdicts.ACCEPTED] * 2


def test_lazy_judging_marks_remaining_as_not_run(tmp_path):
    result = judge(tmp_path, "wrong_answer/off_by_one.cpp")
    assert result.testcases[0].verdict == verdicts.WRONG_ANSWER
    assert result.testcases[1].verdict == verdicts.NOT_RUN


def test_judge_all_runs_everything(tmp_path):
    result = judge(tmp_path, "wrong_answer/off_by_one.cpp", judge_all=True)
    assert all(c.verdict == verdicts.WRONG_ANSWER for c in result.testcases)


def test_runtime_is_recorded(tmp_path):
    result = judge(tmp_path, "accepted/main.cpp")
    assert all(c.wall > 0 for c in result.testcases)
    assert all(c.mem_kib > 0 for c in result.testcases)


def test_tle_is_not_killed_before_hard_limit(tmp_path):
    result = judge(tmp_path, "time_limit_exceeded/sleepy.cpp")
    first = result.testcases[0]
    assert first.wall >= 1.0
    assert first.wall <= 4.0


def test_machine_factor_is_positive():
    assert measure_machine_factor(IMAGE, 0) > 0
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/docker/test_judge.py -v -m docker`
Expected: FAIL. `ModuleNotFoundError: No module named 'icpc_verify.judge'`

- [ ] **Step 4: 최소 구현을 쓴다**

`src/icpc_verify/judge.py`:

```python
"""solution 하나를 testcase 전체에 대해 채점한다.

testcase 1회 = container 1개다. 기본은 lazy judging 이고 첫 비 AC 에서 멈춘다.
이 모듈은 validation: default 만 다룬다. custom/interactive 는 계획 2 다.
"""

from __future__ import annotations

import json
import shutil
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import verdicts
from .compare import compare_output, parse_compare_flags
from .compile import CompileOptions, compile_solution
from .problemcfg import ProblemConfig
from .results import RunMeasurement, SolutionResult, TestCaseResult, classify_run, solution_verdict
from .sandbox import SandboxSpec, run_sandbox
from .solutions import Language, Solution
from .testdata import TestCase
from .timelimits import TimeLimits

RUN_MOUNT = "/run"
OUT_MOUNT = "/out"
WORK_MOUNT = "/work"
STDERR_KEEP_BYTES = 8 * 1024


@dataclass
class JudgeOptions:
    image: str
    cpuset: int
    judge_all: bool = False
    output_limit_mib: int = 8
    memory_mib: int = 2048
    compile_flags: dict[Language, str] = field(default_factory=dict)
    machine_factor: float = 1.0
    cpu_isolated: bool = False
    warnings: list[str] = field(default_factory=list)


def measure_machine_factor(image: str, cpuset: int, rounds: int = 3) -> float:
    reference_result = run_sandbox(
        SandboxSpec(
            image=image, cpuset=cpuset, memory_mib=1024, binds=(),
            argv=("cat", "/usr/local/lib/icpc/BENCH_REFERENCE"), timeout=60.0,
        )
    )
    reference = float(reference_result.stdout.decode().strip())

    samples: list[float] = []
    for _ in range(rounds):
        result = run_sandbox(
            SandboxSpec(
                image=image, cpuset=cpuset, memory_mib=1024, binds=(),
                argv=("/usr/local/bin/bench",), timeout=120.0,
            )
        )
        samples.append(float(result.stdout.decode().strip()))
    return statistics.median(samples) / reference


def _run_one_testcase(
    case: TestCase,
    run_argv: Sequence[str],
    work_dir: Path,
    io_dir: Path,
    limits: TimeLimits,
    options: JudgeOptions,
) -> tuple[RunMeasurement, bytes, str]:
    """(측정값, team 출력, stderr 요약) 을 돌려준다."""
    run_dir = io_dir / "in"
    out_dir = io_dir / "out"
    for d in (run_dir, out_dir):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    shutil.copy2(case.input_path, run_dir / "tc.in")

    output_limit = options.output_limit_mib * 1024 * 1024
    result = run_sandbox(
        SandboxSpec(
            image=options.image,
            cpuset=options.cpuset,
            memory_mib=options.memory_mib,
            binds=(
                (work_dir, WORK_MOUNT, "ro"),
                (run_dir, RUN_MOUNT, "ro"),
                (out_dir, OUT_MOUNT, "rw"),
            ),
            argv=(
                "python3", "/usr/local/bin/runner.py",
                "--input", f"{RUN_MOUNT}/tc.in",
                "--stdout", f"{OUT_MOUNT}/stdout",
                "--stderr", f"{OUT_MOUNT}/stderr",
                "--result", f"{OUT_MOUNT}/run.json",
                "--hard-kill", f"{limits.hard_kill:.3f}",
                "--output-limit", str(output_limit),
                "--", *run_argv,
            ),
            timeout=limits.hard_kill + 60.0,
        )
    )

    result_file = out_dir / "run.json"
    if result_file.is_file():
        raw = json.loads(result_file.read_text(encoding="utf-8"))
        measurement = RunMeasurement(
            wall=raw["wall"],
            cpu=raw["cpu"],
            max_rss_kib=raw["max_rss_kib"],
            exit_code=raw["exit_code"],
            signal=raw["signal"],
            timed_out=raw["timed_out"],
            output_limit_exceeded=raw["output_limit_exceeded"],
            oom_killed=result.oom_killed,
        )
    else:
        measurement = RunMeasurement(
            wall=limits.hard_kill, cpu=0.0, max_rss_kib=0, exit_code=result.exit_code,
            signal=0, timed_out=result.timed_out, output_limit_exceeded=False,
            oom_killed=result.oom_killed,
        )

    stdout_path = out_dir / "stdout"
    team_output = stdout_path.read_bytes() if stdout_path.is_file() else b""
    stderr_path = out_dir / "stderr"
    stderr_text = ""
    if stderr_path.is_file():
        data = stderr_path.read_bytes()[:STDERR_KEEP_BYTES]
        stderr_text = data.decode("utf-8", errors="replace")
    return measurement, team_output, stderr_text


def judge_solution(
    problem_dir: Path,
    config: ProblemConfig,
    solution: Solution,
    testcases: Sequence[TestCase],
    limits: TimeLimits,
    work_root: Path,
    options: JudgeOptions,
) -> SolutionResult:
    result = SolutionResult(
        name=solution.name,
        rel_path=solution.rel_path,
        expected=solution.expected,
        language=solution.language.value if solution.language else "",
        verdict=verdicts.JUDGE_ERROR,
        machine_factor=options.machine_factor,
        cpu_isolated=options.cpu_isolated,
        warnings=list(options.warnings),
    )

    work_dir = work_root / "work"
    io_dir = work_root / "io"
    work_dir.mkdir(parents=True, exist_ok=True)
    io_dir.mkdir(parents=True, exist_ok=True)

    outcome = compile_solution(
        solution,
        work_dir,
        config.memory_mib,
        CompileOptions(image=options.image, cpuset=options.cpuset, flags=options.compile_flags),
    )
    result.compile_log = outcome.log
    if not outcome.ok:
        result.verdict = verdicts.COMPILER_ERROR
        result.testcases = [
            TestCaseResult(c.id, c.group, verdicts.NOT_RUN, 0.0, 0.0, 0, 0, "")
            for c in testcases
        ]
        return result

    compare_flags = parse_compare_flags(config.validator_flags)
    stopped = False
    for case in testcases:
        if stopped:
            result.testcases.append(
                TestCaseResult(case.id, case.group, verdicts.NOT_RUN, 0.0, 0.0, 0, 0, "")
            )
            continue

        measurement, team_output, stderr_text = _run_one_testcase(
            case, outcome.run_argv, work_dir, io_dir, limits, options
        )
        compare_ok, compare_message = compare_output(
            team_output, case.answer_path.read_bytes(), compare_flags
        )
        verdict, message = classify_run(measurement, limits, compare_ok, compare_message)
        if stderr_text and verdict == verdicts.RUN_TIME_ERROR:
            message = f"{message}\nstderr: {stderr_text}"

        result.testcases.append(
            TestCaseResult(
                id=case.id,
                group=case.group,
                verdict=verdict,
                wall=measurement.wall,
                cpu=measurement.cpu,
                mem_kib=measurement.max_rss_kib,
                exit_code=measurement.exit_code,
                message=message,
            )
        )
        if verdict != verdicts.ACCEPTED and not options.judge_all:
            stopped = True

    result.verdict = solution_verdict(result.testcases)
    return result
```

호출하는 쪽이 `JudgeOptions.memory_mib`에 `config.memory_mib`을 넣어 준다.
Task 15 의 CLI 가 그렇게 한다. Task 14 의 테스트는 fixture 의 512 MiB 대신 기본값 2048 을
쓰지만, 두 값 모두 이 fixture 를 돌리기에 충분하므로 verdict 은 같다.

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/docker/test_judge.py -v -m docker`
Expected: PASS. 11개 전부 (parametrize 5개 + 6개)

- [ ] **Step 6: 커밋**

```bash
git add src/icpc_verify/judge.py tests/docker/test_judge.py tests/fixtures/plain
git commit -m "feat: judge one solution against all testcases in containers"
```

---

### Task 15: CLI

**Files:**
- Create: `src/icpc_verify/cli.py`
- Create: `tests/docker/test_cli.py`
- Modify: `.github/workflows/ci.yml`
- Create: `README.md`

**Interfaces:**
- Consumes: 앞의 모든 module
- Produces:
  - `main(argv: list[str] | None = None) -> int`
  - CLI:

```
icpc-verify judge --problem-dir <dir> --solution <rel_path> --output <result.json> \
  [--judge-all] [--image <ref>] [--judge-cpu <n>] [--no-offline-sibling] \
  [--default-time-limit 1.0] [--default-memory-mib 2048] \
  [--timelimit-overshoot "2s|20%"] [--output-limit-mib 8] \
  [--required-cpu-flags avx2] [--verdict-match exact] \
  [--compile-flags-cpp ...] [--compile-flags-c ...] [--compile-flags-java ...]
```

- exit code: 기대와 실제가 같으면 `0`, 다르면 `1`, 설정 오류면 `2`.
- `--output` 파일에 `SolutionResult`를 JSON으로 쓴다. `expectation_met: bool`을 같이 넣는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/docker/test_cli.py`:

```python
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "plain"
IMAGE = (ROOT / "image" / "IMAGE_DIGEST").read_text().strip()


def run_cli(tmp_path, rel_path, *extra, problem_dir=FIXTURE):
    out = tmp_path / "result.json"
    proc = subprocess.run(
        [
            sys.executable, "-m", "icpc_verify.cli", "judge",
            "--problem-dir", str(problem_dir),
            "--solution", rel_path,
            "--output", str(out),
            "--image", IMAGE,
            "--judge-cpu", "0",
            *extra,
        ],
        capture_output=True, text=True,
    )
    payload = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
    return proc, payload


def test_matching_expectation_exits_zero(tmp_path):
    proc, payload = run_cli(tmp_path, "accepted/main.cpp")
    assert proc.returncode == 0, proc.stderr
    assert payload["verdict"] == "accepted"
    assert payload["expectation_met"] is True
    assert payload["machine_factor"] > 0


def test_mismatched_expectation_exits_one(tmp_path):
    """시간제한을 30초로 늘리면 sleepy.cpp 는 accepted 가 되어 기대와 어긋난다."""
    problem = tmp_path / "problem"
    shutil.copytree(FIXTURE, problem)
    (problem / "problem.yaml").write_text(
        "problem_format_version: 2023-07-draft\n"
        "name: Add Two Numbers\n"
        "type: pass-fail\n"
        "limits:\n  time_limit: 30.0\n  memory: 512\n",
        encoding="utf-8",
    )
    proc, payload = run_cli(
        tmp_path, "time_limit_exceeded/sleepy.cpp", problem_dir=problem
    )
    assert proc.returncode == 1
    assert payload["verdict"] == "accepted"
    assert payload["expectation_met"] is False


def test_unknown_solution_exits_two(tmp_path):
    proc, _ = run_cli(tmp_path, "accepted/nope.cpp")
    assert proc.returncode == 2
    assert "nope.cpp" in proc.stderr


def test_missing_problem_yaml_exits_two(tmp_path):
    proc = subprocess.run(
        [
            sys.executable, "-m", "icpc_verify.cli", "judge",
            "--problem-dir", str(tmp_path),
            "--solution", "accepted/x.cpp",
            "--output", str(tmp_path / "r.json"),
        ],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "problem.yaml" in proc.stderr


def test_result_json_shape(tmp_path):
    _, payload = run_cli(tmp_path, "accepted/main.cpp")
    assert set(payload) >= {
        "name", "rel_path", "expected", "language", "verdict", "testcases",
        "compile_log", "machine_factor", "cpu_isolated", "warnings", "expectation_met",
        "time_limit", "hard_kill",
    }
    case = payload["testcases"][0]
    assert set(case) == {"id", "group", "verdict", "wall", "cpu", "mem_kib", "exit_code", "message"}
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/docker/test_cli.py -v -m docker`
Expected: FAIL. `No module named icpc_verify.cli`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/icpc_verify/cli.py`:

```python
"""icpc-verify CLI. 계획 1 에서는 judge 하위 명령만 있다."""

from __future__ import annotations

import argparse
import dataclasses
import json
import platform
import sys
import tempfile
from pathlib import Path

from .cpu import CpuError, apply_cpu_plan, check_arch_and_flags, plan_cpu, read_cpu_flags, read_topology
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "judge":
            return run_judge(args)
    except (ProblemConfigError, TestDataError, CpuError, OvershootSpecError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/docker/test_cli.py -v -m docker`
Expected: PASS. 5개 전부

- [ ] **Step 5: 전체 테스트와 lint를 돌린다**

Run: `ruff check . && ruff format --check . && python -m pytest tests -v`
Expected: 전부 PASS

- [ ] **Step 6: CI에 docker 테스트를 추가한다**

`.github/workflows/ci.yml`의 `jobs`에 job을 하나 더 넣는다.

```yaml
  docker-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install -e . pytest
      - name: Build judge image
        run: |
          set -a && . image/python39.env && set +a
          docker build --platform linux/amd64 \
            --build-arg PY39_URL="$PY39_URL" --build-arg PY39_SHA256="$PY39_SHA256" \
            -t icpc-judge:test image/
          echo "icpc-judge:test" > image/IMAGE_DIGEST
      - run: python -m pytest tests/docker -v -m docker
```

- [ ] **Step 7: README를 쓴다**

`README.md`:

```markdown
# icpc-verify

Kattis / DOMjudge 호환 ICPC 문제 package 검증 도구.

계획 1 범위: 로컬 CLI. `validation: default` 문제를 채점한다.
GitHub Action 통합은 계획 3 이다.

## 설치

    python -m pip install -e .

## judge image 준비

    set -a && . image/python39.env && set +a
    docker build --platform linux/amd64 \
      --build-arg PY39_URL="$PY39_URL" --build-arg PY39_SHA256="$PY39_SHA256" \
      -t icpc-judge:test image/
    echo "icpc-judge:test" > image/IMAGE_DIGEST

## 사용

    icpc-verify judge \
      --problem-dir path/to/problem \
      --solution accepted/main.cpp \
      --output result.json

exit code 는 기대와 실제가 같으면 0, 다르면 1, 설정 오류면 2 다.

## 요구 사항

- x86_64 runner. AVX2 필요
- Docker
- python 3.12

## 알려진 한계

- hosted runner 의 hypervisor 간섭은 제거할 수 없다. machine factor 로 드러낸다.
- physical core 가 1개인 runner (2 vCPU) 에서는 격리가 best-effort 다. 4 vCPU 이상을 권장한다.
```

- [ ] **Step 8: 커밋**

```bash
git add src/icpc_verify/cli.py tests/docker/test_cli.py .github/workflows/ci.yml README.md
git commit -m "feat: add icpc-verify judge CLI"
```

---

## 계획 1 완료 조건

- [ ] `ruff check .` 와 `ruff format --check .` 가 통과한다
- [ ] `python -m pytest tests/unit -v` 가 통과한다
- [ ] `python -m pytest tests/docker -v -m docker` 가 통과한다
- [ ] `tests/fixtures/plain`의 solution 5개가 각자 디렉토리 이름과 같은 verdict을 낸다
- [ ] `image/python39.env`와 `image/IMAGE_DIGEST`가 실제 값으로 채워져 있다

## 다음 계획

- **계획 2**: custom validator 빌드/호출, interactive validator. `judge.py`의 비교 단계를 validator 전략으로 갈아끼운다.
- **계획 3**: `discover.py` 변경 감지, action 3개, reusable workflow, Job Summary와 HTML 리포트,
  권장 시간제한 계산(spec §10.5), selftest workflow.
