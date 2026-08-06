# ICPC Problem Verifier — 계획 2: Validator 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `validation: custom`(special judge)과 `validation: custom interactive` 문제를 채점할 수 있게 한다.

**Architecture:** validator를 solution과 같은 language script로 빌드해 별도 container에서 실행한다 (`exit 42=AC, 43=WA, 그 외=judge_error`). custom은 solution 실행 후 validator container를 하나 더 띄우고, interactive는 새 `image/interactive_runner.py`가 한 container 안에서 solution과 validator를 양방향 pipe로 묶는다. `judge.py`의 비교 단계가 `config.validation`에 따라 분기한다.

**Tech Stack:** 계획 1과 동일 — Python 3.12 (host), Docker, judge image (ubuntu 24.04), pytest, ruff.

## Global Constraints

계획 1의 Global Constraints가 전부 그대로 적용된다. 추가:

- validator 호출 규약: `./validator <input> <judge_ans> <feedback_dir> [validator_flags] < team_output`, exit `42`=AC, `43`=WA, 그 외=`judge_error`.
- `feedback_dir/judgemessage.txt`는 최대 **4096 byte**만 읽어 리포트에 넣는다.
- custom validator container: 메모리 **2048 MiB** 고정(solution 제한과 무관), timeout **hard_kill + 30초**.
- interactive: 시간과 메모리는 **solution만** 측정. 쌍 전체에 **hard_kill + 5초** 안전 timeout. validator가 42/43으로 먼저 끝나고 solution이 SIGPIPE로 죽으면 validator 판정을 우선한다. SIGPIPE 이외의 signal/비정상 exit는 `run_time_error`가 validator 판정보다 우선한다.
- interactive container 메모리 = `solution limit + 512 MiB`, solution의 max RSS가 limit을 넘으면 `run_time_error`.
- `image/interactive_runner.py`는 `image/runner.py`처럼 **stdlib 단독**이고 `icpc_verify`를 import하지 않는다.
- 이 호스트는 arm64 macOS다. docker 테스트는 branch push 후 GitHub Actions CI(docker-test job)로 검증한다. container는 항상 `user=host_user()`로 돈다.
- mainline 단위 테스트는 현재 115개다. 각 task는 이를 깨지 않는다.

## 실행 순서 (병렬성)

- Task 1(순수 리팩토링)과 Task 4(interactive_runner)는 **병렬 가능**하다.
- Task 2는 1에, Task 3은 2에, Task 5는 3과 4에 의존한다.

---

### Task 1: describe_unit 공개 리팩토링 + validator 빌드 계획(순수 로직)

**Files:**
- Modify: `src/icpc_verify/solutions.py`
- Create: `src/icpc_verify/validators.py`
- Test: `tests/unit/test_validators.py`
- Modify: `tests/unit/test_solutions.py` (기존 테스트는 그대로 통과해야 함. 추가만 한다)

**Interfaces:**
- Consumes: `solutions._build_solution`의 기존 로직, `verdicts` 상수
- Produces:
  - `solutions.describe_unit(unit: Path, root: Path, expected: str) -> tuple[Solution | None, str | None]`
    — 기존 `_build_solution`의 본체를 공개 함수로 뺀 것. `rel_path`는 `root` 기준.
    `_build_solution`은 이걸 호출하는 wrapper로 남는다.
  - `validators.ValidatorError(Exception)`
  - `validators.BuildPlan` — frozen dataclass: `kind: str` (`"build-script" | "run-script" | "sources"`), `solution: Solution | None` (kind가 `sources`일 때만)
  - `validators.plan_validator_build(validator_dir: Path) -> BuildPlan`
  - `validators.validator_verdict(exit_code: int) -> str` — 42→`accepted`, 43→`wrong_answer`, 그 외→`judge_error`
  - `validators.read_judgemessage(feedback_dir: Path) -> str` — `judgemessage.txt` 앞 4096 byte, 없으면 `""`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/unit/test_validators.py`:

```python
from pathlib import Path

import pytest

from icpc_verify import verdicts
from icpc_verify.solutions import Language
from icpc_verify.validators import (
    ValidatorError,
    plan_validator_build,
    read_judgemessage,
    validator_verdict,
)


def make_dir(tmp_path, files):
    d = tmp_path / "check"
    d.mkdir()
    for name, text in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return d


def test_build_script_wins(tmp_path):
    d = make_dir(tmp_path, {"build": "#!/bin/sh\n", "check.cpp": "int main(){}"})
    plan = plan_validator_build(d)
    assert plan.kind == "build-script"
    assert plan.solution is None


def test_run_script_without_build(tmp_path):
    d = make_dir(tmp_path, {"run": "#!/bin/sh\nexit 42\n"})
    plan = plan_validator_build(d)
    assert plan.kind == "run-script"


def test_sources_inferred(tmp_path):
    d = make_dir(tmp_path, {"check.cpp": "int main(){}", "validate.h": "// header"})
    plan = plan_validator_build(d)
    assert plan.kind == "sources"
    assert plan.solution is not None
    assert plan.solution.language is Language.CPP
    assert [p.name for p in plan.solution.sources] == ["check.cpp"]


def test_python_validator_entry(tmp_path):
    d = make_dir(tmp_path, {"grade.py": "print(42)"})
    plan = plan_validator_build(d)
    assert plan.solution.language is Language.PYTHON
    assert plan.solution.entry == "grade.py"


def test_empty_dir_raises(tmp_path):
    d = make_dir(tmp_path, {"README.md": "docs only"})
    with pytest.raises(ValidatorError, match="소스"):
        plan_validator_build(d)


def test_mixed_language_raises(tmp_path):
    d = make_dir(tmp_path, {"a.cpp": "int main(){}", "b.py": "pass"})
    with pytest.raises(ValidatorError, match="언어"):
        plan_validator_build(d)


def test_missing_dir_raises(tmp_path):
    with pytest.raises(ValidatorError, match="디렉토리"):
        plan_validator_build(tmp_path / "nope")


@pytest.mark.parametrize(
    ("code", "verdict"),
    [
        (42, verdicts.ACCEPTED),
        (43, verdicts.WRONG_ANSWER),
        (0, verdicts.JUDGE_ERROR),
        (1, verdicts.JUDGE_ERROR),
        (-11, verdicts.JUDGE_ERROR),
    ],
)
def test_validator_verdict(code, verdict):
    assert validator_verdict(code) == verdict


def test_read_judgemessage_caps_at_4096(tmp_path):
    (tmp_path / "judgemessage.txt").write_text("x" * 10000, encoding="utf-8")
    assert read_judgemessage(tmp_path) == "x" * 4096


def test_read_judgemessage_missing(tmp_path):
    assert read_judgemessage(tmp_path) == ""


def test_describe_unit_is_public(tmp_path):
    from icpc_verify.solutions import describe_unit

    src = tmp_path / "v"
    src.mkdir()
    (src / "main.cpp").write_text("int main(){}", encoding="utf-8")
    solution, warning = describe_unit(src, tmp_path, "validator")
    assert warning is None
    assert solution.rel_path == "v"
    assert solution.expected == "validator"
    assert solution.language is Language.CPP
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `PYTHONPATH=src python3 -m pytest tests/unit/test_validators.py -v`
Expected: FAIL. `ModuleNotFoundError: No module named 'icpc_verify.validators'`

- [ ] **Step 3: solutions.py를 리팩토링한다**

`src/icpc_verify/solutions.py`에서 `_build_solution`의 본체를 공개 함수로 옮긴다.
기존 `_build_solution(unit, expected, problem_dir)`은 아래처럼 wrapper가 된다.
로직 자체는 한 줄도 바꾸지 않는다 — `solutions_root` 계산만 인자로 바뀐다.

```python
def describe_unit(unit: Path, root: Path, expected: str) -> tuple[Solution | None, str | None]:
    """단일 파일 또는 디렉토리 unit 을 Solution 으로 해석한다. rel_path 는 root 기준이다.

    (solution, warning) 을 돌려준다. 건너뛸 대상이면 solution 이 None 이다.
    """
    rel_path = unit.relative_to(root).as_posix()

    if unit.is_dir():
        sources = tuple(sorted(p for p in unit.rglob("*") if p.is_file() and _language_of(p)))
        source_root = unit
    else:
        if _language_of(unit) is None:
            return None, f"지원하지 않는 확장자입니다. 건너뜁니다: {rel_path}"
        sources = (unit,)
        source_root = unit.parent

    if not sources:
        return None, f"소스 파일이 없습니다. 건너뜁니다: {rel_path}"

    # ... (기존 _build_solution 의 나머지 본체를 그대로 이 함수로 옮긴다:
    #      languages 집합, name, 언어 혼합 오류, entry 결정, Solution 생성)


def _build_solution(
    unit: Path, expected: str, problem_dir: Path
) -> tuple[Solution | None, str | None]:
    return describe_unit(unit, problem_dir / "solutions", expected)
```

주의: 기존 `_build_solution`의 warning 문구는 `solutions/{rel_path}` 형식이었다.
`describe_unit`으로 옮기면서 `{rel_path}`만 남기면 `test_solutions.py`의
`test_unsupported_extension_warns_and_is_skipped`가 실패할 수 있다 — 그 테스트는
`"notes.txt" in w`만 확인하므로 통과한다. `test_missing_solutions_dir_returns_empty`도
`discover_solutions` 쪽 문구라 영향 없다. 리팩토링 후 기존 테스트 전체를 돌려 확인한다.

- [ ] **Step 4: validators.py의 순수 부분을 구현한다**

`src/icpc_verify/validators.py`:

```python
"""custom output validator 의 빌드 계획과 판정 규약.

Kattis/DOMjudge 규약:
  ./validator <input> <judge_ans> <feedback_dir> [flags] < team_output
  exit 42 -> AC, 43 -> WA, 그 외 -> judge_error

빌드 우선순위: build 스크립트 > run 스크립트 > 소스에서 언어 추론.
container 실행이 필요한 부분(빌드/호출)은 이 모듈의 별도 함수가 맡는다 (Task 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import verdicts
from .solutions import Solution, describe_unit

JUDGEMESSAGE_CAP = 4096


class ValidatorError(Exception):
    """validator 를 빌드하거나 실행할 수 없다."""


@dataclass(frozen=True)
class BuildPlan:
    kind: str  # "build-script" | "run-script" | "sources"
    solution: Solution | None = None


def plan_validator_build(validator_dir: Path) -> BuildPlan:
    if not validator_dir.is_dir():
        raise ValidatorError(f"validator 디렉토리가 없습니다: {validator_dir}")

    if (validator_dir / "build").is_file():
        return BuildPlan(kind="build-script")
    if (validator_dir / "run").is_file():
        return BuildPlan(kind="run-script")

    solution, warning = describe_unit(validator_dir, validator_dir.parent, "validator")
    if solution is None:
        raise ValidatorError(f"validator 소스를 찾지 못했습니다: {warning}")
    if solution.error:
        raise ValidatorError(f"validator 소스가 잘못되었습니다: {solution.error}")
    return BuildPlan(kind="sources", solution=solution)


def validator_verdict(exit_code: int) -> str:
    if exit_code == 42:
        return verdicts.ACCEPTED
    if exit_code == 43:
        return verdicts.WRONG_ANSWER
    return verdicts.JUDGE_ERROR


def read_judgemessage(feedback_dir: Path) -> str:
    path = feedback_dir / "judgemessage.txt"
    if not path.is_file():
        return ""
    return path.read_bytes()[:JUDGEMESSAGE_CAP].decode("utf-8", errors="replace")
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `PYTHONPATH=src python3 -m pytest tests/unit/test_validators.py tests/unit/test_solutions.py -v`
Expected: 새 테스트 12개 + 기존 solutions 테스트 12개 전부 PASS

- [ ] **Step 6: 전체 단위 테스트와 lint를 돌린다**

Run: `ruff check . && ruff format --check . && PYTHONPATH=src python3 -m pytest tests/unit -q`
Expected: 전부 PASS (기존 115 + 신규 12 = 127)

- [ ] **Step 7: 커밋**

```bash
git add src/icpc_verify/solutions.py src/icpc_verify/validators.py tests/unit/test_validators.py
git commit -m "feat: plan validator builds and map validator exit codes"
```

---

### Task 2: validator 빌드·호출 (container)

**Files:**
- Modify: `src/icpc_verify/compile.py` (디렉토리 staging 수정 + mount 매개변수화)
- Modify: `src/icpc_verify/validators.py` (빌드/호출 함수 추가)
- Test: `tests/unit/test_compile_staging.py`
- Test: `tests/docker/test_validators.py`

**Interfaces:**
- Consumes: Task 1의 `BuildPlan`, `plan_validator_build`, `validator_verdict`, `read_judgemessage`;
  `compile.compile_solution`, `sandbox.run_sandbox`/`SandboxSpec`/`host_user`
- Produces:
  - `compile.compile_solution(solution, work_dir, memory_mib, options, mount: str = "/work")`
    — 기존 시그니처에 keyword 인자 `mount` 추가. compile.sh/run.sh 호출과 staged 경로가
    전부 이 mount를 쓴다. 기본값이 `/work`이므로 기존 호출부는 변화 없다.
  - `compile._stage_sources`: unit이 **디렉토리**면 소스만이 아니라 **디렉토리 전체를 복사**한다
    (header, 데이터 파일 포함). 반환값(컴파일 대상 경로 목록)은 여전히 인식된 소스만.
  - `validators.VALIDATOR_MOUNT = "/validator"`, `validators.VALIDATOR_MEMORY_MIB = 2048`
  - `validators.BuiltValidator` — frozen dataclass: `dir: Path` (host 쪽 빌드 결과 디렉토리),
    `argv: tuple[str, ...]` (container 안 `/validator` 기준 실행 argv), `log: str`
  - `validators.build_validator(validator_dir: Path, build_root: Path, *, image: str, cpuset: int) -> BuiltValidator`
    — 실패 시 `ValidatorError`
  - `validators.run_custom_validator(built: BuiltValidator, *, input_path: Path, answer_path: Path, team_output_path: Path, feedback_dir: Path, flags: Sequence[str], image: str, cpuset: int, timeout: float) -> tuple[str, str]`
    — `(verdict, judgemessage)`를 돌려준다. verdict은 `validator_verdict` 결과.
    container 실행 자체가 실패(timeout 등)하면 `(judge_error, 진단문구)`.

- [ ] **Step 1: staging 단위 테스트를 쓴다**

`tests/unit/test_compile_staging.py`:

```python
from pathlib import Path

from icpc_verify.compile import _stage_sources
from icpc_verify.solutions import describe_unit


def test_directory_unit_stages_all_files(tmp_path):
    unit = tmp_path / "multi"
    unit.mkdir()
    (unit / "a.cpp").write_text("int main(){}", encoding="utf-8")
    (unit / "helper.h").write_text("// header", encoding="utf-8")
    solution, _ = describe_unit(unit, tmp_path, "accepted")

    work = tmp_path / "work"
    work.mkdir()
    staged = _stage_sources(solution, work)

    assert (work / "a.cpp").is_file()
    assert (work / "helper.h").is_file()          # 소스가 아니어도 복사된다
    assert staged == ["/work/a.cpp"]              # 컴파일 대상은 소스만


def test_single_file_unit_stages_only_that_file(tmp_path):
    src = tmp_path / "sol.cpp"
    src.write_text("int main(){}", encoding="utf-8")
    (tmp_path / "neighbor.txt").write_text("x", encoding="utf-8")
    solution, _ = describe_unit(src, tmp_path, "accepted")

    work = tmp_path / "work"
    work.mkdir()
    staged = _stage_sources(solution, work)

    assert (work / "sol.cpp").is_file()
    assert not (work / "neighbor.txt").exists()   # 이웃 파일은 안 따라온다
    assert staged == ["/work/sol.cpp"]


def test_mount_parameter_changes_container_paths(tmp_path):
    src = tmp_path / "check.py"
    src.write_text("print(42)", encoding="utf-8")
    solution, _ = describe_unit(src, tmp_path, "validator")

    work = tmp_path / "work"
    work.mkdir()
    staged = _stage_sources(solution, work, mount="/validator")
    assert staged == ["/validator/check.py"]
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `PYTHONPATH=src python3 -m pytest tests/unit/test_compile_staging.py -v`
Expected: FAIL (`_stage_sources`에 mount 인자가 없고, 디렉토리 전체 복사가 아직 없다)

- [ ] **Step 3: compile.py를 수정한다**

`src/icpc_verify/compile.py`의 `_stage_sources`와 `compile_solution`을 이렇게 바꾼다.

```python
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
```

`compile_solution`은 `mount` keyword를 받아 `_stage_sources`, `compile.sh`/`run.sh` 호출의
`WORK_MOUNT` 자리와 bind target에 전부 사용한다:

```python
def compile_solution(
    solution: Solution,
    work_dir: Path,
    memory_mib: int,
    options: CompileOptions,
    mount: str = WORK_MOUNT,
) -> CompileOutcome:
    ...
    sources = _stage_sources(solution, work_dir, mount)
    binds = ((work_dir, mount, "rw"),)
    ...
            argv=(
                "/usr/local/lib/icpc/compile.sh",
                solution.language.value,
                mount,
                solution.entry,
                flags,
                "--",
                *sources,
            ),
    ...  # run.sh 호출도 WORK_MOUNT 대신 mount
```

- [ ] **Step 4: staging 테스트가 통과하는지 확인한다**

Run: `PYTHONPATH=src python3 -m pytest tests/unit/test_compile_staging.py tests/unit -q`
Expected: 전부 PASS

- [ ] **Step 5: validators.py에 빌드·호출을 구현한다**

`src/icpc_verify/validators.py`에 추가:

```python
import shlex
import shutil
from collections.abc import Sequence

from .compile import CompileOptions, compile_solution
from .sandbox import SandboxSpec, host_user, run_sandbox

VALIDATOR_MOUNT = "/validator"
VALIDATOR_MEMORY_MIB = 2048
BUILD_TIMEOUT = 120.0


@dataclass(frozen=True)
class BuiltValidator:
    dir: Path
    argv: tuple[str, ...]
    log: str = ""


def build_validator(
    validator_dir: Path, build_root: Path, *, image: str, cpuset: int
) -> BuiltValidator:
    plan = plan_validator_build(validator_dir)

    build_dir = build_root / "validator"
    shutil.rmtree(build_dir, ignore_errors=True)
    shutil.copytree(validator_dir, build_dir)
    build_dir.chmod(0o755)

    if plan.kind == "run-script":
        (build_dir / "run").chmod(0o755)
        return BuiltValidator(dir=build_dir, argv=(f"{VALIDATOR_MOUNT}/run",))

    if plan.kind == "build-script":
        (build_dir / "build").chmod(0o755)
        result = run_sandbox(
            SandboxSpec(
                image=image,
                cpuset=cpuset,
                memory_mib=VALIDATOR_MEMORY_MIB,
                binds=((build_dir, VALIDATOR_MOUNT, "rw"),),
                argv=(f"{VALIDATOR_MOUNT}/build",),
                timeout=BUILD_TIMEOUT,
                user=host_user(),
            )
        )
        log = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        if result.timed_out or result.exit_code != 0:
            raise ValidatorError(f"validator build 스크립트가 실패했습니다:\n{log}")
        run_path = build_dir / "run"
        if not run_path.is_file():
            raise ValidatorError("build 스크립트가 run 실행 파일을 만들지 않았습니다")
        run_path.chmod(0o755)
        return BuiltValidator(dir=build_dir, argv=(f"{VALIDATOR_MOUNT}/run",), log=log)

    # kind == "sources": solution 과 같은 파이프라인으로 컴파일한다
    assert plan.solution is not None
    outcome = compile_solution(
        plan.solution,
        build_dir,
        VALIDATOR_MEMORY_MIB,
        CompileOptions(image=image, cpuset=cpuset),
        mount=VALIDATOR_MOUNT,
    )
    if not outcome.ok:
        raise ValidatorError(f"validator 컴파일에 실패했습니다:\n{outcome.log}")
    return BuiltValidator(dir=build_dir, argv=outcome.run_argv, log=outcome.log)


def run_custom_validator(
    built: BuiltValidator,
    *,
    input_path: Path,
    answer_path: Path,
    team_output_path: Path,
    feedback_dir: Path,
    flags: Sequence[str],
    image: str,
    cpuset: int,
    timeout: float,
) -> tuple[str, str]:
    data_dir = feedback_dir.parent / "vdata"
    shutil.rmtree(data_dir, ignore_errors=True)
    data_dir.mkdir(parents=True)
    data_dir.chmod(0o755)
    shutil.copy2(input_path, data_dir / "tc.in")
    shutil.copy2(answer_path, data_dir / "tc.ans")
    shutil.copy2(team_output_path, data_dir / "tc.out")

    shutil.rmtree(feedback_dir, ignore_errors=True)
    feedback_dir.mkdir(parents=True)
    feedback_dir.chmod(0o755)

    result = run_sandbox(
        SandboxSpec(
            image=image,
            cpuset=cpuset,
            memory_mib=VALIDATOR_MEMORY_MIB,
            binds=(
                (built.dir, VALIDATOR_MOUNT, "ro"),
                (data_dir, "/data", "ro"),
                (feedback_dir, "/feedback", "rw"),
            ),
            argv=(
                "sh",
                "-c",
                'exec "$@" < /data/tc.out',
                "sh",
                *built.argv,
                "/data/tc.in",
                "/data/tc.ans",
                "/feedback",
                *flags,
            ),
            timeout=timeout,
            user=host_user(),
        )
    )

    message = read_judgemessage(feedback_dir)
    if result.timed_out:
        return verdicts.JUDGE_ERROR, "validator 가 시간 안에 끝나지 않았습니다"
    verdict = validator_verdict(result.exit_code)
    if verdict == verdicts.JUDGE_ERROR:
        detail = result.stderr[:JUDGEMESSAGE_CAP].decode("utf-8", errors="replace")
        message = f"validator exit code {result.exit_code}\n{detail}".strip()
    return verdict, message
```

`shlex` import는 쓰지 않으면 넣지 않는다.

- [ ] **Step 6: docker 테스트를 쓴다**

`tests/docker/test_validators.py`:

```python
from pathlib import Path

import pytest

from icpc_verify import verdicts
from icpc_verify.validators import (
    ValidatorError,
    build_validator,
    run_custom_validator,
)

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
IMAGE = (ROOT / "image" / "IMAGE_DIGEST").read_text().strip()

CHECKER_CPP = r"""
#include <cstdio>
#include <cstdlib>
#include <string>
// sum checker: input 은 목표합 s, team 출력은 "a b". a+b==s 면 42, 아니면 43.
int main(int argc, char** argv) {
    FILE* in = fopen(argv[1], "r");
    long long s, a, b;
    if (fscanf(in, "%lld", &s) != 1) return 1;
    if (scanf("%lld %lld", &a, &b) != 2) {
        std::string path = std::string(argv[3]) + "/judgemessage.txt";
        FILE* fb = fopen(path.c_str(), "w");
        fprintf(fb, "two integers expected\n");
        fclose(fb);
        return 43;
    }
    if (a + b == s) return 42;
    std::string path = std::string(argv[3]) + "/judgemessage.txt";
    FILE* fb = fopen(path.c_str(), "w");
    fprintf(fb, "%lld + %lld != %lld\n", a, b, s);
    fclose(fb);
    return 43;
}
"""


def make_validator_dir(tmp_path):
    d = tmp_path / "output_validators" / "check"
    d.mkdir(parents=True)
    (d / "check.cpp").write_text(CHECKER_CPP, encoding="utf-8")
    return d


def make_case(tmp_path, team_text):
    (tmp_path / "tc.in").write_text("5\n", encoding="utf-8")
    (tmp_path / "tc.ans").write_text("2 3\n", encoding="utf-8")
    (tmp_path / "team.out").write_text(team_text, encoding="utf-8")


def run(tmp_path, built, team_text):
    make_case(tmp_path, team_text)
    return run_custom_validator(
        built,
        input_path=tmp_path / "tc.in",
        answer_path=tmp_path / "tc.ans",
        team_output_path=tmp_path / "team.out",
        feedback_dir=tmp_path / "feedback",
        flags=(),
        image=IMAGE,
        cpuset=0,
        timeout=60.0,
    )


def test_compiled_checker_accepts_alternative_answer(tmp_path):
    built = build_validator(
        make_validator_dir(tmp_path), tmp_path / "build", image=IMAGE, cpuset=0
    )
    verdict, _ = run(tmp_path, built, "1 4\n")
    assert verdict == verdicts.ACCEPTED


def test_compiled_checker_rejects_wrong_sum(tmp_path):
    built = build_validator(
        make_validator_dir(tmp_path), tmp_path / "build", image=IMAGE, cpuset=0
    )
    verdict, message = run(tmp_path, built, "1 5\n")
    assert verdict == verdicts.WRONG_ANSWER
    assert "!=" in message                      # judgemessage.txt 가 전달된다


def test_run_script_validator(tmp_path):
    d = tmp_path / "output_validators" / "always"
    d.mkdir(parents=True)
    (d / "run").write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
    built = build_validator(d, tmp_path / "build", image=IMAGE, cpuset=0)
    verdict, _ = run(tmp_path, built, "anything\n")
    assert verdict == verdicts.ACCEPTED


def test_build_script_validator(tmp_path):
    d = tmp_path / "output_validators" / "built"
    d.mkdir(parents=True)
    (d / "build").write_text(
        "#!/bin/sh\nprintf '#!/bin/sh\\nexit 43\\n' > \"$(dirname \"$0\")/run\"\n"
        "chmod +x \"$(dirname \"$0\")/run\"\n",
        encoding="utf-8",
    )
    built = build_validator(d, tmp_path / "build_out", image=IMAGE, cpuset=0)
    verdict, _ = run(tmp_path, built, "anything\n")
    assert verdict == verdicts.WRONG_ANSWER


def test_bad_exit_code_is_judge_error(tmp_path):
    d = tmp_path / "output_validators" / "broken"
    d.mkdir(parents=True)
    (d / "run").write_text("#!/bin/sh\necho boom >&2\nexit 1\n", encoding="utf-8")
    built = build_validator(d, tmp_path / "build", image=IMAGE, cpuset=0)
    verdict, message = run(tmp_path, built, "x\n")
    assert verdict == verdicts.JUDGE_ERROR
    assert "exit code 1" in message


def test_compile_failure_raises(tmp_path):
    d = tmp_path / "output_validators" / "bad"
    d.mkdir(parents=True)
    (d / "check.cpp").write_text("this is not c++", encoding="utf-8")
    with pytest.raises(ValidatorError, match="컴파일"):
        build_validator(d, tmp_path / "build", image=IMAGE, cpuset=0)


def test_header_only_helper_is_staged(tmp_path):
    d = tmp_path / "output_validators" / "with_header"
    d.mkdir(parents=True)
    (d / "check.cpp").write_text(
        '#include "verdict.h"\nint main(){ return OK; }\n', encoding="utf-8"
    )
    (d / "verdict.h").write_text("#define OK 42\n", encoding="utf-8")
    built = build_validator(d, tmp_path / "build", image=IMAGE, cpuset=0)
    verdict, _ = run(tmp_path, built, "x\n")
    assert verdict == verdicts.ACCEPTED
```

- [ ] **Step 7: 로컬에서 검증 가능한 것을 돌린다**

Run: `ruff check . && ruff format --check . && PYTHONPATH=src python3 -m pytest tests/unit -q`
Expected: 전부 PASS

- [ ] **Step 8: 커밋 후 push하고 CI를 본다**

```bash
git add -A && git commit -m "feat: build and invoke custom output validators in containers"
git push -u origin <branch>
gh run watch <id> --repo Suckzoo/problem-verifier --exit-status
```

Expected: 두 job 모두 녹색. docker-test에 새 validator 테스트 8개 포함

---

### Task 3: judge/CLI에 custom validation 연결 + fixture

**Files:**
- Modify: `src/icpc_verify/judge.py`
- Modify: `src/icpc_verify/cli.py`
- Create: `tests/fixtures/custom/problem.yaml`
- Create: `tests/fixtures/custom/data/01.in` `01.ans` `02.in` `02.ans`
- Create: `tests/fixtures/custom/output_validators/check/check.cpp` (Task 2의 CHECKER_CPP와 같은 sum checker)
- Create: `tests/fixtures/custom/solutions/accepted/main.cpp`
- Create: `tests/fixtures/custom/solutions/accepted/alt.py`
- Create: `tests/fixtures/custom/solutions/wrong_answer/bad.cpp`
- Test: `tests/docker/test_judge_custom.py`
- Modify: `tests/docker/test_cli.py` (custom 거부 테스트가 있으면 통과 테스트로 교체)

**Interfaces:**
- Consumes: Task 2의 `build_validator`, `run_custom_validator`, `ValidatorError`;
  기존 `judge_solution` 흐름, `problemcfg.ValidationMode`
- Produces:
  - `judge_solution`이 `config.validation is ValidationMode.CUSTOM`일 때 validator로 채점한다.
    시그니처는 그대로다 (이미 `problem_dir`, `config`를 받는다 — `problem_dir`이 이제 실제로 쓰인다).
  - CLI에서 `validation: custom` 거부가 사라진다 (`custom interactive`는 Task 5까지 계속 거부).

- [ ] **Step 1: fixture를 만든다**

`tests/fixtures/custom/problem.yaml`:

```yaml
problem_format_version: 2023-07-draft
name: Sum Pair
type: pass-fail
limits:
  time_limit: 1.0
  memory: 512
```

주의: 2023-07 형식은 `output_validator/`(단수)를 우선 찾지만 이 fixture는 legacy 위치
`output_validators/check/`를 쓴다 — `problemcfg._find_validator_dir`가 둘 다 지원하므로
`validation` key 없이도 validator 존재로 CUSTOM이 된다. 이 조합이 실제로 동작하는지가
이 fixture의 검증 포인트 중 하나다.

`data/01.in`: `5\n` / `data/01.ans`: `2 3\n`
`data/02.in`: `100\n` / `data/02.ans`: `50 50\n`

`output_validators/check/check.cpp`: Task 2의 `CHECKER_CPP` 내용 그대로.

`solutions/accepted/main.cpp` — ans와 **다른** 유효 답을 낸다 (checker가 쓰임을 증명):

```cpp
#include <cstdio>
int main() {
    long long s;
    if (scanf("%lld", &s) != 1) return 1;
    printf("%lld %lld\n", 1LL, s - 1);
    return 0;
}
```

`solutions/accepted/alt.py`:

```python
s = int(input())
print(0, s)
```

`solutions/wrong_answer/bad.cpp`:

```cpp
#include <cstdio>
int main() {
    long long s;
    if (scanf("%lld", &s) != 1) return 1;
    printf("%lld %lld\n", 1LL, s);
    return 0;
}
```

- [ ] **Step 2: 실패하는 docker 테스트를 쓴다**

`tests/docker/test_judge_custom.py`:

```python
from pathlib import Path

import pytest

from icpc_verify import verdicts
from icpc_verify.judge import JudgeOptions, judge_solution
from icpc_verify.problemcfg import load_problem_config
from icpc_verify.solutions import discover_solutions
from icpc_verify.testdata import collect_testcases
from icpc_verify.timelimits import make_time_limits

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
IMAGE = (ROOT / "image" / "IMAGE_DIGEST").read_text().strip()
FIXTURE = ROOT / "tests" / "fixtures" / "custom"


def judge(tmp_path, rel_path, **kwargs):
    config = load_problem_config(FIXTURE, default_time_limit=1.0, default_memory_mib=2048)
    limits = make_time_limits(config.time_limit, "2s|20%")
    cases = collect_testcases(FIXTURE)
    sols, _ = discover_solutions(FIXTURE)
    solution = next(s for s in sols if s.rel_path == rel_path)
    options = JudgeOptions(image=IMAGE, cpuset=0, memory_mib=config.memory_mib, **kwargs)
    return judge_solution(FIXTURE, config, solution, cases, limits, tmp_path, options)


def test_alternative_answer_is_accepted(tmp_path):
    result = judge(tmp_path, "accepted/main.cpp")
    assert result.verdict == verdicts.ACCEPTED
    assert [c.verdict for c in result.testcases] == [verdicts.ACCEPTED] * 2


def test_python_alternative_answer_is_accepted(tmp_path):
    result = judge(tmp_path, "accepted/alt.py")
    assert result.verdict == verdicts.ACCEPTED


def test_wrong_sum_is_rejected_with_judgemessage(tmp_path):
    result = judge(tmp_path, "wrong_answer/bad.cpp")
    assert result.verdict == verdicts.WRONG_ANSWER
    first = result.testcases[0]
    assert "!=" in first.message                # judgemessage 가 결과에 실린다
    assert result.testcases[1].verdict == verdicts.NOT_RUN   # lazy judging 유지


def test_broken_validator_is_judge_error(tmp_path):
    import shutil

    problem = tmp_path / "problem"
    shutil.copytree(FIXTURE, problem)
    check = problem / "output_validators" / "check"
    shutil.rmtree(check)
    check.mkdir()
    (check / "run").write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")

    config = load_problem_config(problem, default_time_limit=1.0, default_memory_mib=2048)
    limits = make_time_limits(config.time_limit, "2s|20%")
    cases = collect_testcases(problem)
    sols, _ = discover_solutions(problem)
    solution = next(s for s in sols if s.rel_path == "accepted/main.cpp")
    options = JudgeOptions(image=IMAGE, cpuset=0, memory_mib=config.memory_mib)
    result = judge_solution(problem, config, solution, cases, limits, tmp_path / "w", options)
    assert result.verdict == verdicts.JUDGE_ERROR


def test_validator_build_failure_is_judge_error_without_running(tmp_path):
    import shutil

    problem = tmp_path / "problem"
    shutil.copytree(FIXTURE, problem)
    (problem / "output_validators" / "check" / "check.cpp").write_text(
        "not c++", encoding="utf-8"
    )

    config = load_problem_config(problem, default_time_limit=1.0, default_memory_mib=2048)
    limits = make_time_limits(config.time_limit, "2s|20%")
    cases = collect_testcases(problem)
    sols, _ = discover_solutions(problem)
    solution = next(s for s in sols if s.rel_path == "accepted/main.cpp")
    options = JudgeOptions(image=IMAGE, cpuset=0, memory_mib=config.memory_mib)
    result = judge_solution(problem, config, solution, cases, limits, tmp_path / "w", options)
    assert result.verdict == verdicts.JUDGE_ERROR
    assert all(c.verdict == verdicts.NOT_RUN for c in result.testcases)
    assert "[validator]" in result.compile_log      # 빌드 실패 사유가 compile_log 에 남는다
```

- [ ] **Step 3: judge.py를 수정한다**

`judge_solution`에서 compile 성공 이후를 이렇게 바꾼다:

```python
from .problemcfg import ProblemConfig, ValidationMode
from .validators import ValidatorError, build_validator, run_custom_validator

    ...
    validator = None
    if config.validation is ValidationMode.CUSTOM:
        assert config.validator_dir is not None
        try:
            validator = build_validator(
                config.validator_dir,
                work_root,
                image=options.image,
                cpuset=options.cpuset,
            )
        except ValidatorError as exc:
            result.verdict = verdicts.JUDGE_ERROR
            result.compile_log = f"{result.compile_log}\n[validator] {exc}".strip()
            result.testcases = [
                TestCaseResult(c.id, c.group, verdicts.NOT_RUN, 0.0, 0.0, 0, 0, "")
                for c in testcases
            ]
            return result

    compare_flags = (
        parse_compare_flags(config.validator_flags)
        if config.validation is ValidationMode.DEFAULT
        else None
    )
```

testcase 루프 안, measurement를 얻은 뒤의 비교 부분:

```python
먼저 `_run_one_testcase`의 반환값을
`(measurement, team_output_bytes, team_output_path, stderr_text)` 4-tuple로 넓힌다.
`team_output_path`는 `out_dir / "stdout"`이고, 파일이 없으면(출력 없이 종료) 빈 파일을
만들어서라도 항상 존재하는 경로를 돌려준다. 기존 호출부를 같이 고친다.

```python
        if validator is not None:
            # 실행 자체의 건강 상태(TLE/RTE/OLE)를 먼저 판정하고,
            # 깨끗할 때만 validator 에게 출력을 묻는다 (spec §6.3 의 순서).
            verdict, message = classify_run(measurement, limits, True, "")
            if verdict == verdicts.ACCEPTED:
                verdict, message = run_custom_validator(
                    validator,
                    input_path=case.input_path,
                    answer_path=case.answer_path,
                    team_output_path=team_output_path,
                    feedback_dir=io_dir / "feedback",
                    flags=config.validator_flags,
                    image=options.image,
                    cpuset=options.cpuset,
                    timeout=limits.hard_kill + 30.0,
                )
        else:
            compare_ok, compare_message = compare_output(
                team_output, case.answer_path.read_bytes(), compare_flags
            )
            verdict, message = classify_run(measurement, limits, compare_ok, compare_message)
```

`verdict == JUDGE_ERROR`이고 validator가 원인이면 message에 그 사실이 남는다
(`run_custom_validator`가 만들어 준다).

- [ ] **Step 4: cli.py의 거부 조건을 좁힌다**

```python
    if config.validation is ValidationMode.CUSTOM_INTERACTIVE:
        raise ProblemConfigError(
            f"validation: {config.validation.value} 는 아직 지원하지 않습니다 (계획 2 Task 5)"
        )
```

`tests/docker/test_cli.py`에 custom 거부를 확인하는 테스트가 있으면
(`test_custom_validation_exits_two_before_any_docker_work`), **interactive 거부** 테스트로
바꾸고, custom fixture에 대한 CLI 성공 테스트를 추가한다:

```python
def test_custom_problem_judges_through_cli(tmp_path):
    proc, payload = run_cli(
        tmp_path, "accepted/main.cpp", problem_dir=ROOT / "tests" / "fixtures" / "custom"
    )
    assert proc.returncode == 0, proc.stderr
    assert payload["verdict"] == "accepted"
```

(`run_cli`가 `problem_dir` keyword를 이미 받는다. 아니라면 맞춰 수정한다.)

- [ ] **Step 5: 로컬 검증**

Run: `ruff check . && ruff format --check . && PYTHONPATH=src python3 -m pytest tests/unit -q`
Expected: 전부 PASS

- [ ] **Step 6: 커밋 후 push하고 CI를 본다**

```bash
git add -A && git commit -m "feat: judge problems with custom output validators"
git push && gh run watch <id> --repo Suckzoo/problem-verifier --exit-status
```

Expected: 두 job 녹색. `test_judge_custom.py` 5개 + CLI 테스트 포함

---

### Task 4: interactive runner (host 단위 테스트)

**Files:**
- Create: `image/interactive_runner.py`
- Test: `tests/unit/test_interactive_runner.py`

**Interfaces:**
- Consumes: 없음 (stdlib 단독. `icpc_verify` import 금지)
- Produces: CLI

```
python3 interactive_runner.py \
  --result <path> --hard-kill <sec> --pair-timeout <sec> \
  --validator-json '["<argv0>", ...]' -- <solution argv...>
```

`--result` JSON:

```json
{"solution": {"wall": 0.1, "cpu": 0.1, "max_rss_kib": 1234,
              "exit_code": 0, "signal": 0, "timed_out": false},
 "validator_exit": 42, "validator_signal": 0, "pair_timed_out": false}
```

동작 규약:
- pipe A: solution stdout → validator stdin / pipe B: validator stdout → solution stdin
- validator를 먼저 띄우고 solution을 띄운다. 둘 다 각자 process group (`setsid`).
- solution만 측정한다: wall은 `CLOCK_MONOTONIC`, cpu/max RSS는 `os.wait4` rusage.
- solution wall이 `--hard-kill`을 넘으면 solution pgroup에 SIGKILL → `timed_out: true`.
- 전체가 `--pair-timeout`을 넘으면 둘 다 SIGKILL → `pair_timed_out: true`.
- 한쪽이 끝나면 그쪽 pipe end를 닫고 다른 쪽을 계속 기다린다 (validator가 끝나면
  solution은 다음 write에서 SIGPIPE를 받는다).
- validator에는 `RLIMIT` 제한을 걸지 않는다. solution에는 runner.py와 같은
  `RLIMIT_CPU`/`RLIMIT_CORE`를 건다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/unit/test_interactive_runner.py`:

```python
import json
import signal
import subprocess
import sys
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[2] / "image" / "interactive_runner.py"

# 검증자: stdin 에서 guess 를 읽고 secret(=42) 과 비교해 higher/lower/correct 를 답한다.
VALIDATOR = r"""
import sys
secret = 42
for line in sys.stdin:
    guess = int(line)
    if guess == secret:
        print("correct", flush=True)
        raise SystemExit(42)
    print("higher" if guess < secret else "lower", flush=True)
raise SystemExit(43)
"""

BINARY_SEARCH = r"""
import sys
lo, hi = 1, 100
while True:
    mid = (lo + hi) // 2
    print(mid, flush=True)
    resp = input()
    if resp == "correct":
        break
    if resp == "higher":
        lo = mid + 1
    else:
        hi = mid - 1
"""

WRONG_GUESSER = r"""
print(1, flush=True)
input()
raise SystemExit(0)
"""

CRASHER = r"""
import os, signal
os.kill(os.getpid(), signal.SIGSEGV)
"""

SLEEPER = r"""
import time
time.sleep(30)
"""

SPAMMER = r"""
import sys
while True:
    print(1, flush=True)
    try:
        input()
    except EOFError:
        # validator 가 이미 죽었다. 다음 print 에서 SIGPIPE 가 나야 한다.
        pass
"""

STRICT_VALIDATOR = r"""
import sys
line = sys.stdin.readline()
print("done", flush=True)
raise SystemExit(43)
"""


def run(tmp_path, validator_code, solution_code, *, hard_kill=10.0, pair_timeout=15.0):
    vfile = tmp_path / "validator.py"
    vfile.write_text(validator_code, encoding="utf-8")
    sfile = tmp_path / "solution.py"
    sfile.write_text(solution_code, encoding="utf-8")
    result_path = tmp_path / "result.json"
    subprocess.run(
        [
            sys.executable, str(RUNNER),
            "--result", str(result_path),
            "--hard-kill", str(hard_kill),
            "--pair-timeout", str(pair_timeout),
            "--validator-json", json.dumps([sys.executable, str(vfile)]),
            "--", sys.executable, str(sfile),
        ],
        check=True,
        timeout=60,
    )
    return json.loads(result_path.read_text(encoding="utf-8"))


def test_correct_interaction_gets_42(tmp_path):
    r = run(tmp_path, VALIDATOR, BINARY_SEARCH)
    assert r["validator_exit"] == 42
    assert r["solution"]["exit_code"] == 0
    assert not r["solution"]["timed_out"]
    assert not r["pair_timed_out"]
    # wall 은 solution 이 끝난 시각 기준이어야 한다. validator 종료를 기다린 시간이
    # 섞이면 이 상한이 잡아낸다.
    assert 0 < r["solution"]["wall"] < 5.0


def test_wrong_interaction_gets_43(tmp_path):
    r = run(tmp_path, VALIDATOR, WRONG_GUESSER)
    assert r["validator_exit"] == 43


def test_solution_crash_is_recorded(tmp_path):
    r = run(tmp_path, VALIDATOR, CRASHER)
    assert r["solution"]["signal"] == signal.SIGSEGV


def test_solution_hard_kill(tmp_path):
    r = run(tmp_path, VALIDATOR, SLEEPER, hard_kill=0.5, pair_timeout=30.0)
    assert r["solution"]["timed_out"]
    assert r["solution"]["wall"] >= 0.5


def test_pair_timeout_kills_both(tmp_path):
    # validator 도 solution 도 서로를 기다리며 영원히 산다 -> pair timeout 만이 끊는다.
    deadlock_validator = "import time\ntime.sleep(60)\n"
    r = run(tmp_path, deadlock_validator, SLEEPER, hard_kill=30.0, pair_timeout=1.0)
    assert r["pair_timed_out"]


def test_sigpipe_after_validator_verdict(tmp_path):
    r = run(tmp_path, STRICT_VALIDATOR, SPAMMER, hard_kill=10.0, pair_timeout=15.0)
    assert r["validator_exit"] == 43
    assert r["solution"]["signal"] == signal.SIGPIPE


def test_result_shape(tmp_path):
    r = run(tmp_path, VALIDATOR, BINARY_SEARCH)
    assert set(r) == {"solution", "validator_exit", "validator_signal", "pair_timed_out"}
    assert set(r["solution"]) == {"wall", "cpu", "max_rss_kib", "exit_code", "signal", "timed_out"}
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `PYTHONPATH=src python3 -m pytest tests/unit/test_interactive_runner.py -v`
Expected: FAIL. `image/interactive_runner.py` 가 없다

- [ ] **Step 3: 최소 구현을 쓴다**

`image/interactive_runner.py`:

```python
#!/usr/bin/env python3
"""interactive 문제용: solution 과 validator 를 양방향 pipe 로 묶어 실행한다.

시간과 메모리는 solution 만 측정한다. icpc_verify 에 의존하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import signal
import subprocess
import sys
import time


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--result", required=True)
    p.add_argument("--hard-kill", type=float, required=True)
    p.add_argument("--pair-timeout", type=float, required=True)
    p.add_argument("--validator-json", required=True)
    p.add_argument("argv", nargs=argparse.REMAINDER)
    args = p.parse_args()
    if args.argv and args.argv[0] == "--":
        args.argv = args.argv[1:]
    if not args.argv:
        p.error("solution 명령이 없습니다")
    args.validator_argv = json.loads(args.validator_json)
    return args


def kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def main() -> int:
    args = parse_args()

    sol_to_val_read, sol_to_val_write = os.pipe()
    val_to_sol_read, val_to_sol_write = os.pipe()

    validator = subprocess.Popen(
        args.validator_argv,
        stdin=sol_to_val_read,
        stdout=val_to_sol_write,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid,
    )

    def set_solution_limits() -> None:
        os.setsid()
        soft = int(args.hard_kill) + 2
        resource.setrlimit(resource.RLIMIT_CPU, (soft, soft + 1))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        # subprocess 는 SIGPIPE 를 SIG_IGN 으로 물려주므로 기본값으로 되돌린다.
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    started = time.monotonic()
    solution = subprocess.Popen(
        args.argv,
        stdin=val_to_sol_read,
        stdout=sol_to_val_write,
        stderr=subprocess.DEVNULL,
        preexec_fn=set_solution_limits,
    )

    # 부모는 pipe 끝을 전부 닫는다. 안 닫으면 EOF 가 전달되지 않는다.
    for fd in (sol_to_val_read, sol_to_val_write, val_to_sol_read, val_to_sol_write):
        os.close(fd)

    sol_status = None
    sol_usage = None
    val_status = None
    sol_timed_out = False
    pair_timed_out = False
    deadline = started + args.hard_kill
    pair_deadline = started + args.pair_timeout

    while sol_status is None or val_status is None:
        now = time.monotonic()

        if sol_status is None:
            pid, status, usage = os.wait4(solution.pid, os.WNOHANG)
            if pid != 0:
                sol_status, sol_usage = status, usage
                solution.returncode = 0  # Popen 의 이중 wait 방지
        if val_status is None:
            vpid, vstatus = os.waitpid(validator.pid, os.WNOHANG)
            if vpid != 0:
                val_status = vstatus
                validator.returncode = 0

        if sol_status is None and now >= deadline:
            sol_timed_out = True
            kill_group(solution.pid)
            pid, status, usage = os.wait4(solution.pid, 0)
            sol_status, sol_usage = status, usage
            solution.returncode = 0
            continue

        if now >= pair_deadline:
            pair_timed_out = True
            if sol_status is None:
                kill_group(solution.pid)
                pid, status, usage = os.wait4(solution.pid, 0)
                sol_status, sol_usage = status, usage
                solution.returncode = 0
            if val_status is None:
                kill_group(validator.pid)
                _, val_status = os.waitpid(validator.pid, 0)
                validator.returncode = 0
            break

        # solution 이 끝났는데 validator 가 안 끝나면: solution 쪽 pipe 는 이미
        # 닫혔으므로 validator 는 EOF 를 보고 스스로 끝나야 한다. pair timeout 이 백스톱이다.
        time.sleep(0.005)

    wall = time.monotonic() - started
    kill_group(solution.pid)
    kill_group(validator.pid)
    if val_status is None:
        _, val_status = os.waitpid(validator.pid, 0)
        validator.returncode = 0

    result = {
        "solution": {
            "wall": round(wall, 6),
            "cpu": round(sol_usage.ru_utime + sol_usage.ru_stime, 6),
            "max_rss_kib": int(sol_usage.ru_maxrss),
            "exit_code": os.waitstatus_to_exitcode(sol_status)
            if os.WIFEXITED(sol_status)
            else -1,
            "signal": os.WTERMSIG(sol_status) if os.WIFSIGNALED(sol_status) else 0,
            "timed_out": sol_timed_out,
        },
        "validator_exit": os.waitstatus_to_exitcode(val_status)
        if os.WIFEXITED(val_status)
        else -1,
        "validator_signal": os.WTERMSIG(val_status) if os.WIFSIGNALED(val_status) else 0,
        "pair_timed_out": pair_timed_out,
    }
    with open(args.result, "w", encoding="utf-8") as f:
        json.dump(result, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

구현 시 주의:
- `wall`은 **solution이 끝난 시각**이어야 한다. 위 골격은 루프 종료 시각을 쓰고 있어
  validator가 늦게 끝나면 wall이 과대측정된다. **solution의 wait 성공 시점에
  `wall = time.monotonic() - started`를 기록**하도록 고쳐서 구현하라.
  `test_correct_interaction_gets_42`에 `r["solution"]["wall"] < 5.0` 같은 상한을
  추가해 이를 검증한다.
- macOS에서 `ru_maxrss`는 byte 단위다 (runner.py와 같은 정책: Linux 기준으로 두고
  변환하지 않는다).

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `PYTHONPATH=src python3 -m pytest tests/unit/test_interactive_runner.py -v`
Expected: PASS. 7개 전부. 타이밍 테스트는 3회 재실행으로 flake 여부를 확인한다

- [ ] **Step 5: 전체 단위 테스트와 lint**

Run: `ruff check . && ruff format --check . && PYTHONPATH=src python3 -m pytest tests/unit -q`
Expected: 전부 PASS

- [ ] **Step 6: 커밋**

```bash
git add image/interactive_runner.py tests/unit/test_interactive_runner.py
git commit -m "feat: add interactive runner pairing solution with validator"
```

---

### Task 5: interactive 채점 연결 + fixture + 이미지/README

**Files:**
- Modify: `image/Dockerfile` (`COPY runner.py` 옆에 `COPY interactive_runner.py /usr/local/bin/interactive_runner.py`, `chmod +x` 목록에 추가)
- Modify: `src/icpc_verify/judge.py` (interactive 분기)
- Modify: `src/icpc_verify/cli.py` (interactive 거부 제거)
- Modify: `README.md` (custom/interactive 지원 언급, 계획 2 범위로 갱신)
- Create: `tests/fixtures/interactive/problem.yaml`
- Create: `tests/fixtures/interactive/data/01.in` `01.ans`
- Create: `tests/fixtures/interactive/output_validators/guess/run`
- Create: `tests/fixtures/interactive/solutions/accepted/main.cpp`
- Create: `tests/fixtures/interactive/solutions/wrong_answer/gives_up.py`
- Create: `tests/fixtures/interactive/solutions/time_limit_exceeded/sleepy.py`
- Create: `tests/fixtures/interactive/solutions/run_time_error/crash.c`
- Test: `tests/docker/test_judge_interactive.py`

**Interfaces:**
- Consumes: Task 2의 `build_validator`(interactive validator도 같은 방식으로 빌드),
  Task 4의 `interactive_runner.py` CLI와 result JSON
- Produces:
  - `judge_solution`이 `ValidationMode.CUSTOM_INTERACTIVE`를 처리한다
  - interactive verdict 매핑 함수 `judge._classify_interactive(raw: dict, limits: TimeLimits, memory_mib: int) -> tuple[str, str]` — 단위 테스트 가능한 순수 함수

verdict 우선순위 (Global Constraints의 규약을 코드로):

```
1. pair_timed_out or solution.timed_out or solution.wall > limit  -> time_limit_exceeded
2. solution.max_rss_kib > memory_mib * 1024                       -> run_time_error (메모리)
3. solution.signal not in (0, SIGPIPE)                            -> run_time_error
   solution.signal == 0 and solution.exit_code != 0               -> run_time_error
4. validator_exit == 42 -> accepted    (SIGPIPE 는 여기 도달하므로 자동으로 용서된다)
   validator_exit == 43 -> wrong_answer
   그 외                 -> judge_error
```

- [ ] **Step 1: 순수 매핑의 실패하는 테스트를 쓴다**

`tests/unit/test_judge_interactive_mapping.py` (Test 파일 Create 목록에 추가):

```python
import signal

import pytest

from icpc_verify import verdicts
from icpc_verify.judge import _classify_interactive
from icpc_verify.timelimits import make_time_limits

LIMITS = make_time_limits(1.0, "2s|20%")


def raw(**kwargs):
    base = {
        "solution": {
            "wall": 0.1, "cpu": 0.1, "max_rss_kib": 1000,
            "exit_code": 0, "signal": 0, "timed_out": False,
        },
        "validator_exit": 42, "validator_signal": 0, "pair_timed_out": False,
    }
    sol = kwargs.pop("solution", {})
    base["solution"].update(sol)
    base.update(kwargs)
    return base


def test_clean_accept():
    assert _classify_interactive(raw(), LIMITS, 512)[0] == verdicts.ACCEPTED


def test_validator_43_is_wrong_answer():
    assert _classify_interactive(raw(validator_exit=43), LIMITS, 512)[0] == verdicts.WRONG_ANSWER


def test_tle_beats_validator_verdict():
    r = raw(solution={"wall": 1.5}, validator_exit=43)
    assert _classify_interactive(r, LIMITS, 512)[0] == verdicts.TIME_LIMIT_EXCEEDED


def test_pair_timeout_is_tle():
    r = raw(pair_timed_out=True)
    assert _classify_interactive(r, LIMITS, 512)[0] == verdicts.TIME_LIMIT_EXCEEDED


def test_rss_over_limit_is_rte():
    r = raw(solution={"max_rss_kib": 600 * 1024})
    verdict, message = _classify_interactive(r, LIMITS, 512)
    assert verdict == verdicts.RUN_TIME_ERROR
    assert "메모리" in message


def test_crash_beats_validator_43():
    r = raw(solution={"signal": signal.SIGSEGV, "exit_code": -1}, validator_exit=43)
    assert _classify_interactive(r, LIMITS, 512)[0] == verdicts.RUN_TIME_ERROR


def test_sigpipe_is_forgiven():
    r = raw(solution={"signal": signal.SIGPIPE, "exit_code": -1}, validator_exit=43)
    assert _classify_interactive(r, LIMITS, 512)[0] == verdicts.WRONG_ANSWER


def test_nonzero_exit_is_rte():
    r = raw(solution={"exit_code": 3})
    assert _classify_interactive(r, LIMITS, 512)[0] == verdicts.RUN_TIME_ERROR


def test_validator_error_exit_is_judge_error():
    r = raw(validator_exit=1)
    assert _classify_interactive(r, LIMITS, 512)[0] == verdicts.JUDGE_ERROR
```

- [ ] **Step 2: 매핑 테스트가 실패하는지 확인한다**

Run: `PYTHONPATH=src python3 -m pytest tests/unit/test_judge_interactive_mapping.py -v`
Expected: FAIL. `_classify_interactive` 가 없다

- [ ] **Step 3: judge.py에 매핑과 interactive 분기를 구현한다**

`_classify_interactive`:

```python
import signal as signal_module

def _classify_interactive(
    raw: dict, limits: TimeLimits, memory_mib: int
) -> tuple[str, str]:
    sol = raw["solution"]
    if raw["pair_timed_out"] or sol["timed_out"] or sol["wall"] > limits.limit:
        return (
            verdicts.TIME_LIMIT_EXCEEDED,
            f"wall {sol['wall']:.3f}s 가 시간제한 {limits.limit:.3f}s 를 넘었습니다",
        )
    if sol["max_rss_kib"] > memory_mib * 1024:
        return verdicts.RUN_TIME_ERROR, "메모리 제한을 넘었습니다 (max RSS 기준)"
    if sol["signal"] not in (0, int(signal_module.SIGPIPE)):
        return verdicts.RUN_TIME_ERROR, f"signal {sol['signal']} 로 종료했습니다"
    if sol["signal"] == 0 and sol["exit_code"] != 0:
        return verdicts.RUN_TIME_ERROR, f"exit code {sol['exit_code']} 로 종료했습니다"
    verdict = {42: verdicts.ACCEPTED, 43: verdicts.WRONG_ANSWER}.get(
        raw["validator_exit"], verdicts.JUDGE_ERROR
    )
    message = ""
    if verdict == verdicts.JUDGE_ERROR:
        message = f"validator exit code {raw['validator_exit']}"
    return verdict, message
```

interactive 분기 (`judge_solution` 안):

- validator는 custom과 동일하게 `build_validator`로 빌드한다 (실패 → judge_error 전체 NOT_RUN, custom과 같은 처리).
- testcase마다 container 하나. data 디렉토리에 `tc.in`/`tc.ans`를 staging하고 (custom과 동일 패턴), feedback 디렉토리를 만들고, 다음을 실행한다. interactive에서 solution의 stdin은 validator의 stdout이므로 **입력 파일 리다이렉트는 없다** — testcase 입력은 validator가 argv[1]로 받은 `/data/tc.in`을 직접 읽는다:

```python
        container_memory = options.memory_mib + 512
        result = run_sandbox(
            SandboxSpec(
                image=options.image,
                cpuset=options.cpuset,
                memory_mib=container_memory,
                binds=(
                    (work_dir, WORK_MOUNT, "ro"),
                    (validator.dir, VALIDATOR_MOUNT, "ro"),
                    (data_dir, "/data", "ro"),
                    (feedback_dir, "/feedback", "rw"),
                    (out_dir, OUT_MOUNT, "rw"),
                ),
                argv=(
                    "python3", "/usr/local/bin/interactive_runner.py",
                    "--result", f"{OUT_MOUNT}/run.json",
                    "--hard-kill", f"{limits.hard_kill:.3f}",
                    "--pair-timeout", f"{limits.hard_kill + 5.0:.3f}",
                    "--validator-json", json.dumps(
                        [*validator.argv, "/data/tc.in", "/data/tc.ans", "/feedback",
                         *config.validator_flags]
                    ),
                    "--", *outcome.run_argv,
                ),
                timeout=limits.hard_kill + 60.0,
                user=host_user(),
            )
        )
```

- `run.json`이 없으면 custom/default와 같은 `judge_error` 처리 (`_describe_missing_run_result` 재사용).
- `run.json`을 파싱해 `_classify_interactive`로 verdict을 얻고, `read_judgemessage(feedback_dir)`가
  비어 있지 않으면 message에 덧붙인다.
- OOMKilled(`result.oom_killed`)는 container 전체 기준이라 누가 죽었는지 모른다 —
  `run.json`이 없고 OOMKilled면 message에 그 사실을 적는다 (verdict은 judge_error 유지).
- `TestCaseResult`의 wall/cpu/mem은 `raw["solution"]`에서 채운다.

- [ ] **Step 4: cli.py 거부를 제거하고 Dockerfile을 수정한다**

- `cli.py`: `ValidationMode` 거부 블록을 완전히 제거한다 (import가 안 쓰이게 되면 정리).
- `image/Dockerfile`: `COPY runner.py /usr/local/bin/runner.py` 옆에
  `COPY interactive_runner.py /usr/local/bin/interactive_runner.py`를 추가하고
  `chmod +x` 대상에 포함한다.

- [ ] **Step 5: fixture를 만든다**

`tests/fixtures/interactive/problem.yaml`:

```yaml
name: Guess The Number
validation: custom interactive
limits:
  memory: 512
```

(legacy 형식. 절대 시간제한이 없으므로 `default-time-limit` 1초가 쓰인다 — legacy 경로 검증을 겸한다.)

`data/01.in`: `42\n` / `data/01.ans`: `ok\n` (interactive에서는 ans가 의례적이다)

`output_validators/guess/run` (실행 가능해야 한다. build_validator가 chmod한다):

```python
#!/usr/bin/env python3
import sys

secret = int(open(sys.argv[1]).read())
feedback = sys.argv[3]
count = 0
for line in sys.stdin:
    count += 1
    if count > 100:
        print("too many guesses", file=open(f"{feedback}/judgemessage.txt", "w"))
        raise SystemExit(43)
    try:
        guess = int(line)
    except ValueError:
        print("malformed guess", file=open(f"{feedback}/judgemessage.txt", "w"))
        raise SystemExit(43)
    if guess == secret:
        print("correct", flush=True)
        raise SystemExit(42)
    print("higher" if guess < secret else "lower", flush=True)
print("gave up before guessing", file=open(f"{feedback}/judgemessage.txt", "w"))
raise SystemExit(43)
```

`solutions/accepted/main.cpp`:

```cpp
#include <cstdio>
#include <cstring>
int main() {
    long long lo = 1, hi = 100;
    char resp[32];
    while (lo <= hi) {
        long long mid = (lo + hi) / 2;
        printf("%lld\n", mid);
        fflush(stdout);
        if (scanf("%31s", resp) != 1) return 1;
        if (strcmp(resp, "correct") == 0) return 0;
        if (strcmp(resp, "higher") == 0) lo = mid + 1;
        else hi = mid - 1;
    }
    return 0;
}
```

`solutions/wrong_answer/gives_up.py`:

```python
print(1, flush=True)
input()
```

`solutions/time_limit_exceeded/sleepy.py`:

```python
import time
time.sleep(30)
```

`solutions/run_time_error/crash.c`:

```c
#include <stdlib.h>
int main(void) { abort(); }
```

- [ ] **Step 6: docker 테스트를 쓴다**

`tests/docker/test_judge_interactive.py`:

```python
from pathlib import Path

import pytest

from icpc_verify import verdicts
from icpc_verify.judge import JudgeOptions, judge_solution
from icpc_verify.problemcfg import load_problem_config
from icpc_verify.solutions import discover_solutions
from icpc_verify.testdata import collect_testcases
from icpc_verify.timelimits import make_time_limits

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]
IMAGE = (ROOT / "image" / "IMAGE_DIGEST").read_text().strip()
FIXTURE = ROOT / "tests" / "fixtures" / "interactive"


def judge(tmp_path, rel_path):
    config = load_problem_config(FIXTURE, default_time_limit=1.0, default_memory_mib=2048)
    limits = make_time_limits(config.time_limit, "2s|20%")
    cases = collect_testcases(FIXTURE)
    sols, _ = discover_solutions(FIXTURE)
    solution = next(s for s in sols if s.rel_path == rel_path)
    options = JudgeOptions(image=IMAGE, cpuset=0, memory_mib=config.memory_mib)
    return judge_solution(FIXTURE, config, solution, cases, limits, tmp_path, options)


@pytest.mark.parametrize(
    ("rel_path", "expected"),
    [
        ("accepted/main.cpp", verdicts.ACCEPTED),
        ("wrong_answer/gives_up.py", verdicts.WRONG_ANSWER),
        ("time_limit_exceeded/sleepy.py", verdicts.TIME_LIMIT_EXCEEDED),
        ("run_time_error/crash.c", verdicts.RUN_TIME_ERROR),
    ],
)
def test_interactive_verdicts(tmp_path, rel_path, expected):
    result = judge(tmp_path, rel_path)
    assert result.verdict == expected, result.testcases[0].message


def test_judgemessage_reaches_result(tmp_path):
    result = judge(tmp_path, "wrong_answer/gives_up.py")
    assert "gave up" in result.testcases[0].message


def test_runtime_is_solution_only(tmp_path):
    result = judge(tmp_path, "accepted/main.cpp")
    first = result.testcases[0]
    assert 0 < first.wall <= 1.0
```

- [ ] **Step 7: README를 갱신한다**

`README.md`의 범위 문구를 계획 2까지로 바꾼다: `validation: default / custom /
custom interactive` 지원, validator 규약(42/43), interactive 측정 규칙(solution만 측정,
pair timeout) 요약을 추가한다. 기존 설치/사용 문구는 유지한다.

- [ ] **Step 8: 로컬 검증**

Run: `ruff check . && ruff format --check . && PYTHONPATH=src python3 -m pytest tests/unit -q`
Expected: 전부 PASS

- [ ] **Step 9: 커밋 후 push하고 CI를 본다**

```bash
git add -A && git commit -m "feat: judge interactive problems with paired validator"
git push && gh run watch <id> --repo Suckzoo/problem-verifier --exit-status
```

Expected: 두 job 녹색 (docker-test가 image를 새로 build하므로 interactive_runner 포함)

---

## 계획 2 완료 조건

- [ ] `ruff check .`와 `ruff format --check .`가 통과한다
- [ ] 단위 테스트가 전부 통과한다 (기존 115 + Task 1: 15 + Task 2: 3 + Task 4: 7 + Task 5: 9 = 149 근방)
- [ ] CI docker-test가 통과한다 (기존 38 + validator 8 + custom 6 + interactive 6 = 58 근방)
- [ ] `tests/fixtures/custom`의 `accepted/main.cpp`가 ans와 다른 답으로 AC를 받는다 (checker 사용 증명)
- [ ] `tests/fixtures/interactive`의 4개 verdict이 디렉토리 이름과 일치한다
- [ ] merge 후 publish-image가 새 digest를 내면 `image/IMAGE_DIGEST`를 재고정한다 (운영 단계)

## 다음 계획

- **계획 3**: `discover.py` 변경 감지, action 3개(discover/judge/report), reusable workflow,
  Job Summary + HTML 리포트, 권장 시간제한 계산(spec §10.5), selftest workflow.
