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
        "#include <immintrin.h>\n"
        "#include <cstdio>\n"
        '#pragma GCC target("avx2")\n'
        "int main(){ __m256i v = _mm256_set1_epi32(2); "
        'printf("%d\\n", _mm256_extract_epi32(v, 0)); }\n',
        encoding="utf-8",
    )
    out = sh(
        "docker",
        "run",
        "--rm",
        "-v",
        f"{tmp_path}:/w",
        IMAGE,
        "bash",
        "-c",
        "/usr/local/lib/icpc/compile.sh cpp /w '' '' -- /w/a.cpp && /w/bin",
    )
    assert out.strip() == "2"


def test_c_gnu11(tmp_path):
    src = tmp_path / "a.c"
    src.write_text(
        '#include <stdio.h>\nint main(void){ puts("ok"); return 0; }\n', encoding="utf-8"
    )
    out = sh(
        "docker",
        "run",
        "--rm",
        "-v",
        f"{tmp_path}:/w",
        IMAGE,
        "bash",
        "-c",
        "/usr/local/lib/icpc/compile.sh c /w '' '' -- /w/a.c && /w/bin",
    )
    assert out.strip() == "ok"


def test_java_21():
    version = subprocess.run(
        ["docker", "run", "--rm", IMAGE, "java", "-version"],
        capture_output=True,
        text=True,
        check=True,
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
