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
    built = build_validator(make_validator_dir(tmp_path), tmp_path / "build", image=IMAGE, cpuset=0)
    verdict, _ = run(tmp_path, built, "1 4\n")
    assert verdict == verdicts.ACCEPTED


def test_compiled_checker_rejects_wrong_sum(tmp_path):
    built = build_validator(make_validator_dir(tmp_path), tmp_path / "build", image=IMAGE, cpuset=0)
    verdict, message = run(tmp_path, built, "1 5\n")
    assert verdict == verdicts.WRONG_ANSWER
    assert "!=" in message  # judgemessage.txt 가 전달된다


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
        '#!/bin/sh\nprintf \'#!/bin/sh\\nexit 43\\n\' > "$(dirname "$0")/run"\n'
        'chmod +x "$(dirname "$0")/run"\n',
        encoding="utf-8",
    )
    built = build_validator(d, tmp_path / "build_out", image=IMAGE, cpuset=0)
    verdict, _ = run(tmp_path, built, "anything\n")
    assert verdict == verdicts.WRONG_ANSWER


def test_canonical_build_script_with_relative_paths(tmp_path):
    # 실제 Kattis/DOMjudge 패키지의 build 스크립트는 자기 디렉토리가 cwd 라고 가정하고
    # 상대경로를 쓴다 (I2). $(dirname "$0") 을 쓰지 않는, 이 형태가 흔하다.
    d = tmp_path / "output_validators" / "canonical"
    d.mkdir(parents=True)
    (d / "build").write_text("#!/bin/sh\ng++ -O2 -o run check.cpp\n", encoding="utf-8")
    (d / "check.cpp").write_text(CHECKER_CPP, encoding="utf-8")
    built = build_validator(d, tmp_path / "build_out", image=IMAGE, cpuset=0)
    verdict, _ = run(tmp_path, built, "1 4\n")
    assert verdict == verdicts.ACCEPTED


def test_run_script_with_relative_exec(tmp_path):
    # run 스크립트가 자기 디렉토리의 다른 실행 파일을 상대경로로 exec 하는 형태도 흔하다.
    d = tmp_path / "output_validators" / "canonical_run"
    d.mkdir(parents=True)
    (d / "run_inner").write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
    (d / "run_inner").chmod(0o755)
    (d / "run").write_text('#!/bin/sh\nexec ./run_inner "$@"\n', encoding="utf-8")
    built = build_validator(d, tmp_path / "build_out", image=IMAGE, cpuset=0)
    verdict, _ = run(tmp_path, built, "anything\n")
    assert verdict == verdicts.ACCEPTED


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
