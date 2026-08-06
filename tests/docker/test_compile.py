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
    "accepted/Main.java": (
        'public class Main{public static void main(String[] a){System.out.println("hi");}}\n'
    ),
    "accepted/s.py": 'print("hi")\n',
}


def make_problem(tmp_path, rel, text):
    p = tmp_path / "solutions" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def make_work(tmp_path):
    # pytest's tmp_path defaults to 0700; --cap-drop ALL removes CAP_DAC_OVERRIDE, so the
    # containerized root can't bypass host directory permissions. This bind mount is rw and
    # the container writes new files (binaries, .class, __pycache__) directly into it, so
    # "other" needs write access too, not just read/traverse.
    work = tmp_path / "work"
    work.mkdir()
    work.chmod(0o777)
    return work


@pytest.mark.parametrize("rel", sorted(HELLO))
def test_each_language_compiles_and_runs(tmp_path, rel):
    make_problem(tmp_path, rel, HELLO[rel])
    sols, _ = discover_solutions(tmp_path)
    work = make_work(tmp_path)
    outcome = compile_solution(sols[0], work, 2048, OPTIONS)
    assert outcome.ok, outcome.log
    assert outcome.run_argv


def test_compile_error_is_reported(tmp_path):
    make_problem(tmp_path, "accepted/bad.cpp", "int main(){ this is not c++ }\n")
    sols, _ = discover_solutions(tmp_path)
    work = make_work(tmp_path)
    outcome = compile_solution(sols[0], work, 2048, OPTIONS)
    assert not outcome.ok
    assert "error" in outcome.log.lower()


def test_avx2_pragma_compiles(tmp_path):
    make_problem(
        tmp_path,
        "accepted/simd.cpp",
        '#pragma GCC target("avx2")\n'
        "#include <immintrin.h>\n#include <cstdio>\n"
        'int main(){__m256i v=_mm256_set1_epi32(7);printf("%d\\n",_mm256_extract_epi32(v,0));}\n',
    )
    sols, _ = discover_solutions(tmp_path)
    work = make_work(tmp_path)
    assert compile_solution(sols[0], work, 2048, OPTIONS).ok


def test_discovery_error_becomes_compile_failure(tmp_path):
    make_problem(tmp_path, "accepted/Helper.java", "public class Helper {}\n")
    sols, _ = discover_solutions(tmp_path)
    work = make_work(tmp_path)
    outcome = compile_solution(sols[0], work, 2048, OPTIONS)
    assert not outcome.ok
    assert "main" in outcome.log
