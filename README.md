# icpc-verify

Kattis / DOMjudge 호환 ICPC 문제 package 검증 도구.

계획 2 범위: 로컬 CLI. `validation: default` / `custom` / `custom interactive`
문제를 모두 채점한다. GitHub Action 통합은 계획 3 이다.

## validation 지원

- `default`: team 출력을 답과 token 단위로 비교한다 (`validator_flags` 로
  `--case-sensitive`, `--space-change-sensitive` 같은 비교 규칙을 준다).
- `custom`: `output_validator(s)/` 아래 build 스크립트, run 스크립트, 소스 중
  하나로 판정 프로그램을 빌드해 `<validator> <input> <judge_ans> <feedback_dir>
  [flags] < team_output` 규약으로 부른다. exit 42 는 accepted, 43 은
  wrong_answer, 그 외는 judge_error 다. `feedback_dir/judgemessage.txt` 가
  있으면 그 내용이 결과 message 에 실린다.
- `custom interactive`: solution 과 validator 를 양방향 pipe 로 묶어 같은
  container 안에서 동시에 돌린다. 시간/메모리는 solution 만 측정한다 (validator
  는 채점 인프라의 일부로 취급한다). solution 이 시간 안에 못 끝내거나 두
  프로세스가 pair timeout(= hard kill + 5초) 을 넘기면 time_limit_exceeded 다.
  validator 로 이어지는 pipe 가 끊겨 solution 이 SIGPIPE 로 죽는 경우는
  용서한다 (validator 가 먼저 42/43 으로 끝난 뒤 solution 이 계속 쓰려다
  죽는 정상적인 경로이기 때문이다) - 그 외 signal 이나 비정상 exit code 는
  run_time_error 다. 깨끗하게 끝났으면 validator 의 exit code (42/43/그 외)
  로 accepted/wrong_answer/judge_error 를 정한다.

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
