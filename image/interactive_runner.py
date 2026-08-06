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
    p.add_argument("--sol-stderr", required=True)
    p.add_argument("--val-stderr", required=True)
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

    # 두 프로세스의 stderr 를 파일로 남긴다 (spec §8: 8 KiB 까지 진단에 쓴다).
    # DEVNULL 로 버리면 validator 가 죽었을 때 원인을 알 방법이 없어진다.
    val_stderr_f = open(args.val_stderr, "wb")
    sol_stderr_f = open(args.sol_stderr, "wb")

    validator = subprocess.Popen(
        args.validator_argv,
        stdin=sol_to_val_read,
        stdout=val_to_sol_write,
        stderr=val_stderr_f,
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
        stderr=sol_stderr_f,
        preexec_fn=set_solution_limits,
    )

    # 자식은 dup 된 fd 를 따로 들고 있으므로 부모 쪽 file object 는 바로 닫아도 된다.
    val_stderr_f.close()
    sol_stderr_f.close()

    # 부모는 pipe 끝을 전부 닫는다. 안 닫으면 EOF 가 전달되지 않는다.
    for fd in (sol_to_val_read, sol_to_val_write, val_to_sol_read, val_to_sol_write):
        os.close(fd)

    sol_status = None
    sol_usage = None
    val_status = None
    sol_timed_out = False
    pair_timed_out = False
    wall = None
    deadline = started + args.hard_kill
    pair_deadline = started + args.pair_timeout

    while sol_status is None or val_status is None:
        now = time.monotonic()

        if sol_status is None:
            pid, status, usage = os.wait4(solution.pid, os.WNOHANG)
            if pid != 0:
                sol_status, sol_usage = status, usage
                wall = time.monotonic() - started
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
            wall = time.monotonic() - started
            solution.returncode = 0
            continue

        if now >= pair_deadline:
            pair_timed_out = True
            if sol_status is None:
                kill_group(solution.pid)
                pid, status, usage = os.wait4(solution.pid, 0)
                sol_status, sol_usage = status, usage
                wall = time.monotonic() - started
                solution.returncode = 0
            if val_status is None:
                kill_group(validator.pid)
                _, val_status = os.waitpid(validator.pid, 0)
                validator.returncode = 0
            break

        # solution 이 끝났는데 validator 가 안 끝나면: solution 쪽 pipe 는 이미
        # 닫혔으므로 validator 는 EOF 를 보고 스스로 끝나야 한다. pair timeout 이 백스톱이다.
        time.sleep(0.005)

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
            "exit_code": os.waitstatus_to_exitcode(sol_status) if os.WIFEXITED(sol_status) else -1,
            "signal": os.WTERMSIG(sol_status) if os.WIFSIGNALED(sol_status) else 0,
            "timed_out": sol_timed_out,
        },
        "validator_exit": os.waitstatus_to_exitcode(val_status) if os.WIFEXITED(val_status) else -1,
        "validator_signal": os.WTERMSIG(val_status) if os.WIFSIGNALED(val_status) else 0,
        "pair_timed_out": pair_timed_out,
    }
    with open(args.result, "w", encoding="utf-8") as f:
        json.dump(result, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
