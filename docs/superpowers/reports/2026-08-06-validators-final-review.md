# Final whole-branch review — plan 2 (validators)

> 이 리포트는 SDD workspace에서 작성된 원문을 보존한 것이다. fix wave(sdd/p2-final-fixes,
> bd97f19로 merge)가 I1–I5를 모두 해소했고 scoped 재리뷰가 ADDRESSED로 확정했다.
> Minor M1–M9와 future work는 후속 계획의 참고 목록으로 남는다.

- Branch: `feat/validators`, HEAD `a2727c6`, 13 commits from `b3015b1`.
- Verified state: CI run **31089018460** green on `feat/validators@a2727c6` (both jobs). Two red
  runs mid-branch (31087754997, 31088233719) both failed only on
  `tests/docker/test_sandbox.py::test_oom_is_detected` — a pre-existing plan-1 test that is flaky
  on `ubuntu-latest` (see future work).
- Local re-verification (arm64 host): ruff clean, 148 unit tests pass, 57 docker tests collect,
  and the 12 custom-validator docker tests pass locally against `icpc-judge:test`.
- Findings marked "reproduced" were executed end to end through the real
  `judge_solution`/`build_validator` code paths (interactive probes bind-injected
  `interactive_runner.py` over the pre-Dockerfile-change local image).

## Verdict: FINDINGS — 이후 fix wave로 전부 해소됨

| Severity | Count |
|---|---|
| Critical | 0 |
| Important | 5 (전부 수정됨) |
| Minor | 9 (deferred) |

## Important (전부 bd97f19에서 수정)

### I1. 고장난 interactive validator가 solution의 run_time_error로 보고됨
`_classify_interactive`가 validator_exit이 42/43이 아닐 때도 solution의 비정상 exit을 먼저
봤다. validator가 죽으면 pipe EOF 때문에 solution도 비정상 종료하므로 원인이 뒤바뀐다.
수정: 비-42/43 validator exit은 TLE 다음, RSS/signal/exit 검사 전에 judge_error로 지목.

### I2. build/run 스크립트의 cwd가 /validator가 아니라 image의 /work (read-only)
`SandboxSpec`에 workdir가 없어 상대 경로를 쓰는 표준형 Kattis build 스크립트
(`g++ -O2 -o run check.cpp`)가 전부 실패했다. 기존 fixture는 `$(dirname "$0")` 형태라
우연히 통과했다. 수정: `SandboxSpec.workdir` 추가, validator 관련 세 container에
`-w /validator` 적용, 표준형 상대 경로 fixture 테스트 추가.

### I3. interactive에서 submission이 /data/tc.in(비밀 입력)과 /data/tc.ans를 읽을 수 있음
단일 container 설계(spec §10.3)의 구조적 결과. 재현: 입력을 읽어 그대로 출력하는 "solution"이
accepted를 받았고, judgemessage.txt도 submission이 덮어쓸 수 있었다. verdict 위조는 불가
(runner가 PID 1, run.json은 사후 기록). 수정: 코드가 아니라 README와 spec §10.3에 신뢰 모델
명문화 — 이 도구는 출제자 자기검증용이며, 신뢰하지 않는 제출물을 interactive로 채점하지 말 것,
judgemessage는 신뢰할 수 없는 텍스트로 다룰 것.

### I4. interactive에서 양쪽 stderr가 DEVNULL
진단 불가 상태였다 (I1의 사례가 'exit code 1' 한 줄로만 남음). 수정: `--sol-stderr`/`--val-stderr`
필수 인자 추가, /out 파일로 capture, RTE에는 solution stderr, judge_error에는 validator stderr를
8 KiB 상한으로 메시지에 첨부.

### I5. validator가 멈추면 건강한 solution이 거짓 메시지와 함께 TLE
pair_timed_out이면 solution wall이 limit 안이어도 "wall X가 시간제한 Y를 넘었습니다"를 냈다.
수정: solution이 limit 안이면 judge_error로 validator를 지목, 실제 초과일 때만 TLE.

## Minor (deferred, 수정 안 함)

- M1. SIGPIPE 용서가 Python/Java solution에는 사실상 무효 (CPython은 exit 120, JVM은 IOException
  → exit != 0 경로로 RTE). 언어 의존적 verdict 가능성.
- M2. interactive runner의 poll 간격 5ms (runner.py는 2ms) — wall 과대측정 최대 5ms.
- M3. run_custom_validator의 judge_error 진단에 validator stdout이 빠짐 (stderr만).
- M4. Java interactive validator의 -Xmx가 잘못된 container 크기(2048 기준)로 산정됨.
- M5. run_custom_validator가 feedback_dir의 형제 디렉토리(vdata)를 임의로 소유.
- M6. validator가 solution마다 재빌드됨 + 빌드 시 소스가 두 번 복사됨 (비용 문제).
- M7. interactive_runner의 도달 불가능한 방어적 reap 코드 + 이미 reap된 pid에 killpg.
- M8. _run_one_testcase docstring이 missing-run.json 분기에서 과잉 주장 (문서만의 문제).
- M9. "/data", "/feedback"이 두 모듈에 문자열 리터럴로 중복.

## Interactive 신뢰 모델 (probe로 확인)

**submission이 할 수 있는 것**: /data/tc.in·tc.ans 읽기, /feedback/judgemessage.txt 쓰기(최후
기록자 승리), validator에 signal (자멸적 — judge_error), /out 쓰기.
**할 수 없는 것**: verdict 위조 (PID 1 + run.json 사후 기록, 재현으로 확인), 네트워크/권한
상승/영속화, /validator 변조 (ro), non-interactive custom 모드에서는 아무것도 — custom의
격리는 계획 1과 동일하게 유지된다 (solution container에 ans/validator/feedback 없음).

## Test-shape gaps (future work)

1. validator 쪽 결함 + 건강한 solution 조합의 테스트가 없다 (I1/I4/I5가 산 사분면).
2. build 스크립트 fixture가 cwd 무관형뿐이었다 (I2를 놓친 이유).
3. interactive container 안에서 submission이 접근 가능한 범위를 단언하는 테스트 없음.
4. 실제 runner JSON을 _classify_interactive에 넣는 합성 테스트 없음 (계획 1 I2와 같은 부류).
5. Java interactive 및 컴파일형(sources) validator의 interactive 커버리지 없음.
6. `test_sandbox.py::test_oom_is_detected`가 ubuntu-latest에서 flaky — oom_killed 검출이
   race라면 메모리 verdict도 race다. 독립적으로 볼 가치.

## Other future work

- validator 빌드를 judge_solution 밖으로 (계획 3에서 solution N개당 1회로).
- judgemessage를 result.json에 넣기 전 sanitize (custom은 validator 작성, interactive는
  submission 작성 가능).
- run_sandbox에 --rm 병행 (container 누수 창 축소).

## Confirmed conformant

validator 호출 규약(sh -c 'exec "$@" < ...' — flags가 argv 단어로 전달되어 shell injection
없음), 42/43/기타 매핑, 4096-byte judgemessage 상한, build > run > 소스 추론 우선순위,
legacy/2023-07 위치 혼용, custom container 2048 MiB + hard_kill+30, interactive pair timeout
hard_kill+5 + limit+512 MiB, custom의 run-health-first 순서, VALIDATOR_MOUNT 일관성,
비-default validation에서 parse_compare_flags 미호출(계획 1 I4 해소), lazy judging과 NOT_RUN
채움 유지, testcase 간 stale 출력/feedback 없음.
