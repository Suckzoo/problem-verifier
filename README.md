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
