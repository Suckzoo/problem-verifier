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
            sys.executable,
            str(RUNNER),
            "--input",
            str(stdin_path),
            "--stdout",
            str(tmp_path / "out"),
            "--stderr",
            str(tmp_path / "err"),
            "--result",
            str(result_path),
            "--hard-kill",
            str(hard_kill),
            "--output-limit",
            str(output_limit),
            "--",
            *argv,
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
    r = run(
        tmp_path,
        [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"],
        stdin_text="abc",
    )
    assert r["exit_code"] == 0
    assert (tmp_path / "out").read_text() == "abc"


def test_nonzero_exit_is_recorded(tmp_path):
    r = run(tmp_path, [sys.executable, "-c", "raise SystemExit(3)"])
    assert r["exit_code"] == 3
    assert r["signal"] == 0


def test_signal_is_recorded(tmp_path):
    r = run(
        tmp_path, [sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGSEGV)"]
    )
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
