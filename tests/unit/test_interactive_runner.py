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
import signal
# CPython 은 시작할 때 SIGPIPE 를 SIG_IGN 으로 재설정한다 (interactive_runner.py 가
# exec 전에 SIG_DFL 로 되돌려도 exec 된 인터프리터가 다시 덮어쓴다). 컴파일된 solution
# 이라면 이 문제가 없지만, 이 테스트는 solution 을 파이썬으로 흉내내므로 여기서 직접
# SIG_DFL 로 되돌려야 실제로 SIGPIPE 로 죽는 상황을 재현할 수 있다.
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
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

BROKEN_VALIDATOR = r"""
raise RuntimeError("boom")
"""


def run(tmp_path, validator_code, solution_code, *, hard_kill=10.0, pair_timeout=15.0):
    vfile = tmp_path / "validator.py"
    vfile.write_text(validator_code, encoding="utf-8")
    sfile = tmp_path / "solution.py"
    sfile.write_text(solution_code, encoding="utf-8")
    result_path = tmp_path / "result.json"
    sol_stderr_path = tmp_path / "sol.stderr"
    val_stderr_path = tmp_path / "val.stderr"
    subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--result",
            str(result_path),
            "--hard-kill",
            str(hard_kill),
            "--pair-timeout",
            str(pair_timeout),
            "--validator-json",
            json.dumps([sys.executable, str(vfile)]),
            "--sol-stderr",
            str(sol_stderr_path),
            "--val-stderr",
            str(val_stderr_path),
            "--",
            sys.executable,
            str(sfile),
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


def test_validator_traceback_reaches_val_stderr(tmp_path):
    run(tmp_path, BROKEN_VALIDATOR, WRONG_GUESSER)
    val_stderr = (tmp_path / "val.stderr").read_text(encoding="utf-8")
    assert "RuntimeError" in val_stderr
    assert "boom" in val_stderr
