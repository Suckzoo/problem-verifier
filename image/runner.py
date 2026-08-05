#!/usr/bin/env python3
"""judge container 안에서 solution 하나를 돌리고 시간과 메모리를 잰다.

icpc_verify package 에 의존하지 않는다. image 에 단독으로 들어간다.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import signal
import subprocess
import sys
import threading
import time


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--stdout", required=True)
    p.add_argument("--stderr", required=True)
    p.add_argument("--result", required=True)
    p.add_argument("--hard-kill", type=float, required=True)
    p.add_argument("--output-limit", type=int, required=True)
    p.add_argument("argv", nargs=argparse.REMAINDER)
    args = p.parse_args()
    if args.argv and args.argv[0] == "--":
        args.argv = args.argv[1:]
    if not args.argv:
        p.error("실행할 명령이 없습니다")
    return args


def watch_output_size(path: str, limit: int, stop: threading.Event) -> bool:
    """출력이 limit 을 넘으면 True 를 돌려준다."""
    while not stop.wait(0.05):
        try:
            if os.path.getsize(path) > limit:
                return True
        except OSError:
            pass
    return False


def main() -> int:
    args = parse_args()

    def set_child_limits() -> None:
        os.setsid()
        soft = int(args.hard_kill) + 2
        resource.setrlimit(resource.RLIMIT_CPU, (soft, soft + 1))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    exceeded = False
    stop = threading.Event()
    watcher_result: list[bool] = []

    with (
        open(args.input, "rb") as stdin_file,
        open(args.stdout, "wb") as stdout_file,
        open(args.stderr, "wb") as stderr_file,
    ):
        started = time.monotonic()
        child = subprocess.Popen(
            args.argv,
            stdin=stdin_file,
            stdout=stdout_file,
            stderr=stderr_file,
            preexec_fn=set_child_limits,
        )

        def watch() -> None:
            watcher_result.append(watch_output_size(args.stdout, args.output_limit, stop))

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()

        timed_out = False
        deadline = started + args.hard_kill
        while True:
            pid, status, usage = os.wait4(child.pid, os.WNOHANG)
            if pid != 0:
                break
            now = time.monotonic()
            if watcher_result and watcher_result[0]:
                exceeded = True
                os.killpg(child.pid, signal.SIGKILL)
                pid, status, usage = os.wait4(child.pid, 0)
                break
            if now >= deadline:
                timed_out = True
                os.killpg(child.pid, signal.SIGKILL)
                pid, status, usage = os.wait4(child.pid, 0)
                break
            time.sleep(0.002)

        wall = time.monotonic() - started
        stop.set()
        watcher.join(timeout=1.0)
        # os.wait4 로 직접 거둬들였으므로 Popen 이 다시 wait 하지 않게 한다
        child.returncode = 0

    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    if not exceeded:
        try:
            exceeded = os.path.getsize(args.stdout) > args.output_limit
        except OSError:
            exceeded = False

    result = {
        "wall": round(wall, 6),
        "cpu": round(usage.ru_utime + usage.ru_stime, 6),
        "max_rss_kib": int(usage.ru_maxrss),
        "exit_code": os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else -1,
        "signal": os.WTERMSIG(status) if os.WIFSIGNALED(status) else 0,
        "timed_out": timed_out,
        "output_limit_exceeded": exceeded,
    }
    with open(args.result, "w", encoding="utf-8") as f:
        json.dump(result, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
