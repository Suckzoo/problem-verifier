# ICPC Problem Verifier — 설계

- 날짜: 2026-07-31
- 상태: 승인 대기
- 저장소: `problem-verifier` (action 전용 repo)

## 1. 목적

Kattis / DOMjudge 호환 ICPC 문제 package를 검증하는 GitHub Action을 만든다.
문제 repo가 이 action을 `uses:`로 갖다 쓴다. 문제 데이터는 이 repo에 들어오지 않는다.

검증 내용은 다음과 같다.

- `solutions/` 아래 각 소스코드가 **의도한 verdict**을 내는가
- 각 testcase의 런타임과 메모리가 얼마인가
- (부수) 현재 데이터 기준으로 적절한 시간제한이 얼마인가

## 2. 대상 문제 package 구조

```
<problem-dir>/
├── problem.yaml
├── data/                       # 평평한 구조와 Kattis 중첩 구조를 모두 지원
│   ├── 01.in / 01.ans
│   └── secret/ 03.in / 03.ans
├── output_validators/<name>/   # legacy. custom validator
├── output_validator/           # 2023-07-draft. custom validator
├── include/                    # 있으면 solution 빌드에 포함
└── solutions/
    ├── accepted/
    ├── wrong_answer/
    ├── time_limit_exceeded/
    └── run_time_error/
```

- testcase 수집: `data/**/*.in`을 재귀로 훑고, **같은 디렉토리**의 같은 이름 `.ans`와 짝짓는다.
  경로 순으로 정렬한다. 상대 디렉토리를 group label로 리포트에 표시한다.
- `.in`에 대응하는 `.ans`가 없으면 discover 단계에서 실패한다.
- solution 단위는 `solutions/<verdict>/<이름>.<ext>` (단일 파일) 또는
  `solutions/<verdict>/<이름>/` (multi-file) 이다.
- `solutions/` 아래의 알 수 없는 디렉토리, 지원하지 않는 확장자는 경고 후 건너뛴다.

## 3. Repo 구성

```
problem-verifier/
├── discover/action.yml              # 무엇을 채점할지 결정
├── judge/action.yml                 # solution 1개 채점
├── report/action.yml                # 결과 병합 + 발행
├── .github/workflows/
│   ├── verify.yml                   # reusable workflow. 사용자 진입점
│   ├── publish-image.yml            # judge image build/push
│   └── selftest.yml                 # fixture 대상 자체 검증
├── image/
│   ├── Dockerfile                   # ghcr.io/suckzoo/icpc-judge
│   ├── bench/bench.c                # machine factor benchmark
│   └── languages/{cpp,c,java,python}.sh
├── src/icpc_verify/                 # python 본체
│   ├── problemcfg.py                # problem.yaml 파싱 (legacy + 2023-07)
│   ├── discover.py
│   ├── judge.py
│   ├── runner.py                    # container 안에서 도는 실행 감시자
│   ├── compare.py                   # default validator
│   ├── validate.py                  # custom / interactive validator
│   ├── cpu.py                       # topology, SIMD, machine factor
│   └── report.py
└── tests/
    ├── fixtures/{plain,float,interactive}/
    └── unit/
```

### 3.1 사용자 repo 진입점

```yaml
# .github/workflows/verify.yml
on:
  push:
  pull_request:
  workflow_dispatch:
    inputs:
      full: { type: boolean, default: false }

jobs:
  verify:
    uses: suckzoo/problem-verifier/.github/workflows/verify.yml@v1
    with:
      full: ${{ inputs.full == true }}
```

action 3개를 직접 조립하는 것도 지원한다. reusable workflow는 그 조립을 미리 해둔 것이다.

## 4. 실행 흐름

```
discover (1 job)
  ├─ problem.yaml 파싱, 시간/메모리 제한 확정
  ├─ data/ 짝 검사
  ├─ 변경 감지 -> 채점 대상 결정
  └─ outputs: matrix, count, full, problem(json)
        |
judge (N jobs, matrix, fail-fast: false)
  ├─ arch/SIMD flag 확인
  ├─ CPU topology 파악 -> judge CPU 선택 -> sibling offline (best-effort)
  ├─ machine factor 측정
  ├─ compile
  ├─ testcase 순차 실행 (testcase 1회 = container 1개)
  └─ artifact: icpc-verify-result-<name> / result.json
        |
report (1 job, if: always())
  ├─ artifact 전부 다운로드 + 병합
  ├─ $GITHUB_STEP_SUMMARY 작성
  ├─ index.html artifact 업로드
  └─ mismatch 또는 누락이 있으면 job 실패
```

## 5. 변경 감지 (discover)

| 상황 | 대상 |
|---|---|
| `full: true` | 전체 |
| `workflow_dispatch`, `schedule` | 전체 |
| `problem.yaml`, `data/**`, `output_validator(s)/**`, `include/**` 변경 | 전체 |
| `push` | `event.before..sha`의 solution diff |
| `pull_request` | `merge-base(base, head)..head`의 solution diff |
| `event.before`가 0으로 채워짐 (신규 branch), shallow clone, git 명령 실패 | 전체 (fallback) |

- checkout은 `fetch-depth: 0`으로 한다. reusable workflow가 처리한다.
- 대상이 0개면 judge job을 건너뛴다 (`if: needs.discover.outputs.count != '0'`).
  report는 "변경 없음"을 남기고 성공으로 끝낸다.
- matrix 항목은 `{ name, path, expected, lang }` 이다. `name`은 artifact 이름에 쓸 수 있게
  `[^A-Za-z0-9._-]`를 `_`로 바꾼 값이다.

## 6. 판정 규칙

### 6.1 시간

```
limit      = problem.yaml 의 limits.time_limit (없으면 input default-time-limit)
overshoot  = max(2s, limit * 0.20)      # "2s|20%". DOMjudge 표기법을 따른다
hard_kill  = limit + overshoot

verdict:  wall_time <= limit  ->  통과
          wall_time >  limit  ->  time_limit_exceeded
```

- overshoot는 판정 경계가 아니다. 실제 런타임을 리포트에 남기려고 더 돌려보는 시간이다.
- `wall`과 `cpu` 시간을 둘 다 기록한다. 판정은 `wall` 기준이다.
- 백스톱으로 `RLIMIT_CPU = ceil(hard_kill) + 1`을 건다.
- `timelimit-overshoot` input은 `"Xs"`, `"Y%"`, `"Xs|Y%"`(최대값), `"Xs&Y%"`(최소값)를 받는다.
  기본값은 `"2s|20%"`이다.

### 6.2 메모리

- 기본 2 GiB. `problem.yaml`의 `limits.memory` (MiB 단위)가 있으면 그 값을 쓴다.
- container `--memory` / `--memory-swap`으로 강제한다. swap은 0이다.
- OOM은 `docker inspect --format '{{.State.OOMKilled}}'`로 판정한다.
- Java는 heap 밖 메모리를 쓰므로 `-Xmx = limit - 256MiB`로 잡는다 (최소 256MiB).

### 6.3 verdict 매핑

| 상황 | verdict |
|---|---|
| compile 실패 | `compiler_error` |
| `wall > limit` 또는 hard kill로 SIGKILL | `time_limit_exceeded` |
| OOMKilled | `run_time_error` |
| signal 종료 또는 exit code != 0 | `run_time_error` |
| stdout > `output-limit-mib` (기본 8 MiB) | `wrong_answer` (리포트에 `OLE` 표기) |
| validator exit 42 | AC |
| validator exit 43 | `wrong_answer` |
| validator 그 외 exit | `judge_error` -> job 실패 |

DOMjudge / Kattis에는 MLE verdict이 없다. 그래서 OOM은 `run_time_error`로 매핑한다.

### 6.4 solution 단위 verdict

- 첫 비 AC testcase의 verdict이 최종 verdict이다 (lazy judging. DOMjudge와 동일).
- 전부 AC면 `accepted`이다.
- `judge-all: true`면 모든 testcase를 돌린다. 그래도 최종 verdict 계산은 위와 같다
  (실행 순서상 첫 비 AC).
- `accepted` 기대 solution은 lazy 여부와 무관하게 전 testcase를 돈다 (통과하면 자연히 전수 실행).

### 6.5 기대값 대조

- `verdict-match: exact` (기본): 최종 verdict이 디렉토리 이름과 정확히 같아야 한다.
- `verdict-match: any-rejected`: `accepted/`는 정확히 `accepted`여야 하고,
  나머지 디렉토리는 `accepted`가 아니기만 하면 된다.
- 하나라도 어긋나면 report job이 실패한다.

## 7. CPU 격리

judge job 시작 시 순서대로 수행한다.

1. `uname -m`이 `x86_64`가 아니면 실패한다.
2. `/proc/cpuinfo`의 flags에 `required-cpu-flags` (기본 `avx2`)가 없으면 실패한다.
3. `/sys/devices/system/cpu/cpu*/topology/thread_siblings_list`로 topology를 파악한다.
4. judge CPU를 고른다. `judge-cpu` input이 있으면 그 값을 그대로 쓴다.
   - physical core가 **2개 이상**이면: 마지막 core의 첫 thread를 쓴다.
     그 core의 나머지 sibling thread를
     `echo 0 | sudo tee /sys/devices/system/cpu/cpuN/online`으로 offline한다.
     runner agent와 docker daemon은 앞쪽 core에 남는다.
   - physical core가 **1개뿐**이면 (hosted 2 vCPU): offline을 **하지 않는다**.
     끄면 runner agent와 judge가 같은 thread로 몰려 오히려 나빠진다.
     번호가 가장 큰 thread를 judge CPU로 쓰고, 격리가 best-effort임을 경고한다.
5. `offline-sibling: false`면 4의 offline 단계를 건너뛴다.
   offline이 실패해도 경고만 내고 계속한다.
6. container를 `--cpuset-cpus=<judge cpu>`로 띄운다.

| runner | 결과 |
|---|---|
| 2 vCPU (hosted 기본) | 두 vCPU가 같은 core다. offline을 하지 않고 `cpu1`에 pin만 한다. HT 간섭이 남으므로 best-effort다. 리포트에 경고를 남긴다. |
| 4 vCPU 이상 | `cpu2`를 judge용으로 쓰고 `cpu3`를 끈다. runner agent는 `cpu0/1`에 남는다. 실질적 격리가 된다. |
| self-hosted | 위와 같다. host에서 SMT를 꺼두면 더 깨끗하다. 설정 가이드를 문서에 넣는다. |

hypervisor 레벨의 noisy neighbor는 guest에서 제거할 수 없다. 이 한계는 문서에 명시한다.

### 7.1 Machine factor

- image에 `bench.c`를 `-O2`로 미리 컴파일해 넣는다. 정수·부동소수·메모리 접근이 섞인 고정 루프다.
- image build 때 기준 실행 시간을 재서 image에 상수로 박는다.
- judge job에서 3회 돌려 중앙값을 낸다. `factor = 측정 중앙값 / 기준값`.
- 리포트에 job별로 표시한다. `1.3`을 넘으면 경고한다.
- solution마다 다른 VM에서 돌기 때문에 런타임 비교에는 이 factor를 같이 봐야 한다.

## 8. Sandbox

**testcase 1회 = container 1개**로 한다. OOM 판정이 정확해지고 testcase 간 오염이 없다.
기동 비용은 약 0.2초이며 측정 구간 밖이다. compile도 별도 container에서 한다.

```
docker run --rm \
  --cpuset-cpus=<judge cpu> --cpuset-mems=0 \
  --memory=<limit> --memory-swap=<limit> \
  --pids-limit=256 --network=none \
  --cap-drop=ALL --security-opt=no-new-privileges \
  --read-only --tmpfs /work:rw,size=512m,exec \
  -v <run dir>:/run:ro -v <out dir>:/out:rw \
  ghcr.io/suckzoo/icpc-judge@sha256:...
  /usr/local/bin/runner.py ...
```

`runner.py`가 하는 일:

- `fork`/`exec`으로 solution을 띄운다.
- `CLOCK_MONOTONIC`으로 wall time을, `wait4`의 rusage로 cpu time과 max RSS를 잰다.
- stdin은 `<tc>.in`, stdout은 파일, stderr는 파일이다.
- stdout이 `output-limit-mib`를 넘으면 즉시 kill하고 OLE로 표시한다.
- `hard_kill`에 도달하면 프로세스 그룹에 `SIGKILL`을 보낸다.
- 결과를 JSON 한 줄로 `/out`에 쓴다.
- stderr는 앞뒤 합쳐 8 KiB만 남긴다.

## 9. Toolchain (judge image)

base는 `ubuntu:24.04`이며 버전을 image에 고정한다.

| 언어 | 확장자 | 도구 | 기본 compile |
|---|---|---|---|
| C++ | `.cpp .cc .cxx .C` | g++ 13 | `g++ -x c++ -Wall -O2 -static -pipe -std=gnu++20 -o bin SRC -lm` |
| C | `.c` | gcc 13 | `gcc -x c -Wall -O2 -static -pipe -std=gnu11 -o bin SRC -lm` |
| Java | `.java` | OpenJDK 21 | `javac -encoding UTF-8 -sourcepath . -d . SRC` |
| Python | `.py` | CPython 3.9 | `python3.9 -m py_compile SRC` |

실행 명령:

- C / C++: `./bin`
- Java: `java -Xrs -XX:+UseSerialGC -Xss64m -Xmx<limit-256MiB> -cp . <MainClass>`
- Python: `python3.9 <main>.py`

세부 사항:

- `-static`은 DOMjudge 기본을 따른다. `compile-flags-cpp` / `compile-flags-c` /
  `compile-flags-java` input으로 바꿀 수 있다.
- SIMD는 막지 않는다. `#pragma GCC target("avx2")`와 intrinsic이 그대로 동작한다.
  `-march=native`는 쓰지 않는다. runner마다 결과가 달라지기 때문이다.
- Ubuntu 24.04에는 python3.9 패키지가 없다. `python-build-standalone`의
  CPython 3.9 x86_64 릴리스 tarball을 image build 때 받아 고정한다.
  URL과 sha256을 Dockerfile에 박는다.
- Java entry point는 `public static void main(String` 을 가진 파일에서 찾는다.
  0개이거나 2개 이상이면 `compiler_error`로 처리하고 이유를 리포트에 적는다.
- Python entry point는 파일이 1개면 그 파일, 아니면 `main.py`, 없으면 `compiler_error`다.
- multi-file solution은 디렉토리 안의 해당 언어 소스를 전부 넘긴다.
  `include/` 가 있으면 그 내용을 build 디렉토리에 함께 복사한다.
- 언어 판별은 solution 디렉토리 안 소스 확장자로 한다. 두 언어가 섞이면 `compiler_error`다.

image는 `.github/workflows/publish-image.yml`이 `ghcr.io/suckzoo/icpc-judge`에 push한다.
action은 tag가 아닌 **digest**로 pull한다. digest는 action repo에 커밋된 파일에 박아둔다.
`judge-image` input으로 교체할 수 있다.

## 10. Validator

### 10.1 default validator (`validation: default`)

| flag | 동작 |
|---|---|
| (없음) | 공백으로 자른 token 단위 비교. 대소문자 무시 |
| `case_sensitive` | 대소문자를 구분한다 |
| `space_change_sensitive` | 공백까지 정확히 일치해야 한다 |
| `float_tolerance T` | 절대 오차와 상대 오차 둘 다 T |
| `float_absolute_tolerance T` | 절대 오차 T |
| `float_relative_tolerance T` | 상대 오차 T |

- float 관련 flag가 하나라도 있으면 숫자로 해석되는 token은 수치 비교한다.
  절대 또는 상대 중 하나만 만족해도 통과다.
- float flag가 없으면 모든 token을 문자열로 비교한다.
- 끝의 개행과 뒤쪽 공백은 `space_change_sensitive`가 아닐 때 무시한다.

### 10.2 custom validator (`validation: custom`)

- 위치: legacy는 `output_validators/<name>/`, 2023-07은 `output_validator/`.
- 빌드: 디렉토리에 `build` 스크립트가 있으면 그것을 실행한다. 결과 실행 파일은 `run`이다.
  `run` 스크립트만 있으면 그대로 쓴다. 둘 다 없으면 확장자로 언어를 추론해 빌드한다.
- 호출:

```
./validator <input> <judge_ans> <feedback_dir> [validator_flags] < team_output
exit 42 -> AC
exit 43 -> wrong_answer
그 외    -> judge_error
```

- `feedback_dir/judgemessage.txt`를 읽어 리포트에 넣는다 (최대 4 KiB).
- validator에는 solution과 별개의 timeout을 건다 (`hard_kill + 30s`).

container 배치는 이렇게 나눈다. solution의 OOM 판정이 container 단위이기 때문이다.

| validator 종류 | 어디서 도는가 | testcase당 container 수 |
|---|---|---|
| default | judge action의 python. container 없이 host에서 비교한다 | 1 |
| custom | solution container가 끝난 뒤 **별도 container** | 2 |
| custom interactive | solution과 **같은 container**. 10.3 참고 | 1 |

custom validator container는 solution과 같은 격리 설정을 쓰되 메모리는 따로 2 GiB를 준다.
solution의 메모리 제한과 섞이지 않는다.

### 10.3 interactive validator (`validation: custom interactive`)

```
      +----------+                +-----------+
      | solution |<---- pipe A ---| validator |
      |          |----- pipe B -->|           |
      +----------+                +-----------+
```

- 시간과 메모리는 solution만 측정한다.
- validator가 먼저 끝나면 그 exit code가 최종 판정이다.
- solution이 `SIGPIPE`를 받아도 validator 판정을 우선한다.
- 쌍 전체에 `hard_kill + 5s`의 안전 timeout을 건다. 넘으면 둘 다 kill하고
  solution의 wall time으로 verdict을 정한다 (대개 TLE).
- solution이 먼저 끝나면 그 stdout 파이프를 닫고 validator의 종료를 기다린다.
- 두 프로세스를 같은 container 안에서 띄운다. 이때만 container 하나에 프로세스가 2개다.
  메모리 제한은 `solution limit + validator 여유(512 MiB)`로 잡고,
  solution의 max RSS로 별도 판정한다.

같은 container를 공유하므로 solution과 validator는 uid가 같고, `/data/tc.in`
(비밀 입력)과 `/data/tc.ans`를 solution도 읽을 수 있으며 `/feedback/judgemessage.txt`도
solution이 덮어쓸 수 있다. verdict 위조는 안 된다 (runner가 PID 1이고 `run.json`은
두 프로세스가 다 끝난 뒤에 기록된다). 이 설계는 출제자가 자기 문제를 검증하는
용도로만 안전하다 - 신뢰하지 않는 제출물을 채점하는 데는 쓰지 말 것.

### 10.4 problem.yaml 파싱

새 key를 먼저 보고 없으면 legacy key로 내려간다.

| 항목 | 2023-07-draft 이후 | legacy |
|---|---|---|
| 형식 판별 | `problem_format_version` | 없음 |
| 채점 방식 | `type: pass-fail` | 없음 |
| validator | `output_validator/` 존재 여부 | `validation: default\|custom\|custom interactive` |
| validator 인자 | `output_validator.args` | `validator_flags` |
| 시간제한 | `limits.time_limit` (초) | 없음 |
| 시간 배수 | `limits.time_multiplier` | `limits.time_multiplier` (기본 5) |
| 메모리 | `limits.memory` (MiB) | `limits.memory` (MiB) |

- `type`이 `pass-fail`이 아니면 (예: `scoring`) 명확한 메시지로 실패한다. 이번 범위 밖이다.
- 절대 시간제한이 없으면 `default-time-limit` input을 쓴다 (기본 1초).

### 10.5 권장 시간제한 계산

legacy `problem.yaml`에는 절대 시간제한이 없다. 그래서 리포트에 권장값을 계산해 넣는다.

```
slowest_ac  = accepted 기대 solution들의 testcase 최대 wall time 중 최댓값
normalized  = slowest_ac / machine_factor      # 해당 job 의 factor 로 보정
suggested   = ceil(normalized * time_multiplier * 10) / 10
```

판정에는 쓰지 않는다. 리포트에만 표시한다.

## 11. 리포트

### 11.1 Job Summary

GitHub이 step summary를 1 MiB로 자른다. 그래서 크기를 스스로 관리한다.

```
# ICPC problem verify

문제: <problem name>  ·  testcase 47개  ·  시간제한 1.000s  ·  메모리 2048MiB
권장 시간제한: 2.1s   (가장 느린 accepted 0.412s x multiplier 5)

| solution | 언어 | 기대 | 실제 | max wall | machine factor |
|---|---|---|---|---|---|
| accepted/main.cpp | cpp | accepted | ✅ accepted | 0.412s (41%) | 1.02 |
| wrong_answer/greedy.cpp | cpp | wrong_answer | ✅ wrong_answer | 0.088s | 0.98 |
| time_limit_exceeded/brute.cpp | cpp | time_limit_exceeded | ❌ accepted | 0.910s | 1.31 ⚠ |

## ✅ accepted/main.cpp        cpp · 47/47 · max 0.412s / 1.000s (41%)
🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩
🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩
🟩🟩🟩🟩🟩🟩🟩

| tc | verdict | wall | cpu | mem | |
|----|---------|------|-----|-----|--|
| 01 | AC | 0.102 | 0.098 | 12MB | ███░░░░░░░░░░░░░░░ |
| 02 | AC | 0.412 | 0.405 | 48MB | ████████████████░░ |
```

색상 표기:

| 기호 | 뜻 |
|---|---|
| 🟩 | AC |
| 🟥 | wrong answer |
| 🟨 | time limit exceeded |
| 🟧 | run time error |
| 🟪 | judge error |
| ⬜ | 미실행 (lazy judging으로 건너뜀) |

크기 관리:

- testcase가 200개를 넘으면 띠 대신 요약으로 바꾼다 (verdict별 개수 + 실패 index 목록 최대 50개).
- 런타임 표는 `accepted` 기대 solution과 기대값이 어긋난 solution에만 넣는다.
  표 행도 최대 100개까지만 넣고 나머지는 생략 문구를 적는다.
- 전체 markdown이 900 KiB를 넘으면 뒤쪽 solution 섹션부터 잘라내고
  "HTML artifact를 보라"는 문구를 남긴다.

### 11.2 HTML artifact

단일 `index.html`이다. CSS와 JS를 inline하고 외부 의존이 없다.
artifact 이름은 `icpc-verify-report`다.

- solution x testcase 매트릭스. hover하면 tc id, verdict, wall/cpu, memory, exit code가 뜬다.
- 런타임 차트. 시간제한 기준선과 hard kill 기준선을 같이 그린다.
- solution별 machine factor와 경고.
- 권장 시간제한.
- 실패 testcase의 diff. 실패한 것 중 앞에서 `diff-max-cases` (기본 3)개만 넣는다.
  expected와 actual 각각 `diff-max-bytes` (기본 4096) 이하일 때만 내용을 넣는다.
  넘으면 양쪽 크기와 첫 불일치 byte offset / 줄 번호만 적는다.
- validator의 `judgemessage.txt`, compile 에러 로그 (각 4 KiB까지).

### 11.3 실패 조건

report job은 다음 중 하나라도 있으면 실패한다.

- 기대 verdict과 실제 verdict이 어긋난 solution이 있다
- `judge_error`가 있다
- matrix에 있었는데 결과 artifact가 없는 solution이 있다 (judge job이 죽은 경우)

## 12. 오류 처리

| 상황 | 동작 |
|---|---|
| `problem.yaml` 없음 / 파싱 실패 | discover에서 즉시 실패 |
| `type`이 `pass-fail`이 아님 | discover에서 실패. 지원 범위 밖임을 명시 |
| `.in`에 대응하는 `.ans` 없음 | discover에서 실패 |
| `data/`가 비어 있음 | discover에서 실패 |
| `solutions/` 아래 알 수 없는 디렉토리 | 경고 후 건너뜀 |
| 지원하지 않는 확장자 | 경고 후 건너뜀 |
| solution 디렉토리에 두 언어가 섞임 | `compiler_error` |
| Java main class가 0개 또는 2개 이상 | `compiler_error` |
| validator가 42/43이 아닌 값으로 종료 | `judge_error`. 해당 job 실패 |
| judge job 하나가 죽음 | `fail-fast: false`로 나머지는 계속. report가 "미실행"으로 표시하고 실패 처리 |
| `uname -m != x86_64` 또는 SIMD flag 없음 | judge 시작 시 명확한 메시지로 실패 |
| docker 없음 | judge 시작 시 실패 |
| sibling offline 실패 | 경고만 내고 계속 |
| ghcr pull 실패 | 실패. 네트워크 문제임을 명시 |

## 13. Action 인터페이스

### 13.1 reusable workflow `verify.yml`

| input | 타입 | 기본값 | 뜻 |
|---|---|---|---|
| `full` | boolean | `false` | 전체 재채점 |
| `runs-on` | string | `ubuntu-latest` | judge job runner |
| `problem-dir` | string | `.` | 문제 package 위치 |
| `judge-image` | string | (repo에 박힌 digest) | judge image 교체 |
| `judge-all` | boolean | `false` | 첫 실패에서 멈추지 않음 |
| `verdict-match` | string | `exact` | `exact` 또는 `any-rejected` |
| `max-parallel` | number | `0` | matrix 동시 실행 수. 0은 제한 없음 |
| `solutions-filter` | string | `` | glob. 채점 대상을 더 좁힌다 |
| `default-time-limit` | number | `1` | problem.yaml에 없을 때 쓸 시간제한 (초) |
| `default-memory-mib` | number | `2048` | problem.yaml에 없을 때 쓸 메모리 제한 |
| `timelimit-overshoot` | string | `2s\|20%` | hard kill 여유 |
| `output-limit-mib` | number | `8` | stdout 상한 |
| `required-cpu-flags` | string | `avx2` | 없으면 실패 |
| `judge-cpu` | string | `` | 비우면 자동 선택 |
| `offline-sibling` | boolean | `true` | sibling thread offline 시도 |
| `diff-max-cases` | number | `3` | diff를 담을 실패 testcase 수 |
| `diff-max-bytes` | number | `4096` | 한쪽 출력이 이보다 크면 diff 생략 |
| `compile-flags-cpp` | string | `` | 비우면 기본값 |
| `compile-flags-c` | string | `` | 비우면 기본값 |
| `compile-flags-java` | string | `` | 비우면 기본값 |

### 13.2 `discover/action.yml`

- inputs: `problem-dir`, `full`, `base-ref`, `solutions-filter`,
  `default-time-limit`, `default-memory-mib`, `timelimit-overshoot`
- outputs: `matrix` (JSON), `count`, `full`, `problem` (JSON. 제한과 validator 설정)

### 13.3 `judge/action.yml`

- inputs: `problem-dir`, `problem` (discover의 JSON), `solution` (matrix 항목 JSON),
  `judge-image`, `judge-cpu`, `offline-sibling`, `judge-all`, `required-cpu-flags`,
  `output-limit-mib`, `diff-max-cases`, `diff-max-bytes`, `compile-flags-*`
- outputs: `result-path`, `verdict`
- artifact `icpc-verify-result-<name>` 을 업로드한다

### 13.4 `report/action.yml`

- inputs: `verdict-match`, `expected-matrix` (누락 검출용), `problem`
- outputs: `passed`
- artifact `icpc-verify-report` 를 업로드하고 Job Summary를 쓴다

## 14. 자체 테스트

### 14.1 fixture

`tests/fixtures/` 아래에 미니 문제 3개를 둔다.

| fixture | 검증 대상 |
|---|---|
| `plain` | `validation: default`. 평평한 `data/`. 4개 verdict 전부 |
| `float` | `validation: default` + `float_tolerance`. Kattis 중첩 `data/sample`, `data/secret`. 2023-07 형식 |
| `interactive` | `validation: custom interactive`. custom validator 빌드 경로 |

각 fixture에 다음 solution을 둔다.

- 4개 verdict 각각에 대해 기대와 실제가 맞는 solution
- 언어 4종(cpp, c, java, python) 각각 최소 1개
- **일부러 기대값을 틀리게 붙인 solution** (예: `wrong_answer/`에 정답을 넣음)

### 14.2 selftest workflow

- reusable workflow를 fixture에 돌린다.
- 결과 JSON을 기대값 표와 대조한다. "틀리게 붙인 solution"이 실패로 잡히는지도 확인한다.
- `full: true`와 diff 기반 두 경로를 모두 돈다.

### 14.3 단위 테스트 (pytest)

- `problem.yaml` 파싱: legacy와 2023-07 양쪽. 누락 key의 기본값
- overshoot 계산: `Xs`, `Y%`, `Xs|Y%`, `Xs&Y%`
- default validator: flag 조합별 동작. float 절대/상대 오차 경계
- 변경 감지: push / pull_request / force push / 문제 파일 변경 / 대상 0개
- 언어와 entry point 판별
- 리포트 절단: 200 testcase 초과, 900 KiB 초과, diff 크기 초과
- verdict 매핑과 `verdict-match` 두 모드

## 15. 알려진 한계

- hosted runner의 hypervisor 레벨 간섭은 제거할 수 없다. machine factor로 드러내기만 한다.
- 2 vCPU runner에서는 격리가 best-effort다. 4 vCPU 이상을 권장한다.
- solution마다 다른 VM에서 돌기 때문에 solution 간 런타임 절대 비교는 machine factor 보정이 필요하다.
- `scoring` 타입 문제는 지원하지 않는다.
- 지원 언어는 C++(gnu++20), C(gnu11), Java 21, Python 3.9 네 가지다.
