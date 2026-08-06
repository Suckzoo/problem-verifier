# Final whole-branch review — plan 1 (core judging)

- Branch: `feat/core-judging`, HEAD `3d8a4f2`, 32 commits from `0e6c76f`.
- Verified state: CI run **31081730821** on `feat/core-judging@3d8a4f2` is green — 108 unit tests and 38 docker tests on x86_64. (The brief cited run 31081464146 on `sdd/task-15@7b3ab35`; that tree is *not* content-identical to HEAD — it predates the Task 11 sandbox fix `b2fb385`. The later run 31081730821 covers the exact HEAD tree, so the verification claim holds; only the run number in the ledger was stale.)
- Local re-verification on this arm64 host: `ruff check .` clean, `ruff format --check .` clean, 108 unit tests pass, 38 docker tests collect.

## Verdict: FINDINGS

| Severity | Count |
|---|---|
| Critical | 1 |
| Important | 4 |
| Minor | 8 |

---

## Critical

### C1. Judging any Python solution through the CLI aborts with `PermissionError`; no `result.json` is written

`src/icpc_verify/cli.py:110-113`, `src/icpc_verify/judge.py:189`, `image/languages/python.sh:8`

`run_judge` wraps the whole judging run in `tempfile.TemporaryDirectory`. Inside it, `judge_solution` creates `work/`, `chmod`s it to `0o777`, and bind-mounts it read-write into the compile container. The container runs as **root** (no `USER` in the Dockerfile, no `--user` in `run_sandbox`), so everything it creates there is owned by uid 0 with umask 022. For C/C++ that is only `/work/bin`, a plain file inside a `0777` directory, which the host user can still unlink. For Python, `python3.9 -m py_compile /work/<entry>` creates **`/work/__pycache__/` as `drwxr-xr-x root:root`**. The host user cannot unlink the `.pyc` inside it, and `TemporaryDirectory._rmtree`'s `PermissionError` recovery path calls `os.chmod` on that directory, which returns `EPERM` for a non-owner and is not caught (only `FileNotFoundError` is). The exception escapes the `with` block **before** `args.output.write_text(...)` runs, is swallowed by `main`'s `except (..., OSError)`, and the CLI exits 2 with `error: [Errno 1] Operation not permitted: .../work/__pycache__`. The same applies to any Java solution declaring a `package`, since `javac -d /work` then creates a root-owned package directory.

Reproduced end to end in a Linux container (host user creates the temp dir and chmods `work` to 0777, container root creates `__pycache__` inside it, host user runs the identical cleanup):

```
CLEANUP FAILED: PermissionError [Errno 1] Operation not permitted:
  '/tmp/icpc-judge-0korzj95/work/__pycache__'
```

Failure scenario: `icpc-verify judge --solution accepted/alt.py --output result.json` on any Linux runner with rootful Docker (which is exactly GitHub's `ubuntu-latest`). The judging itself completes correctly; the process then dies during cleanup, so plan 3's workflow sees exit code 2 and a missing artifact for every Python submission. Why no test caught it: `tests/docker/test_judge.py` judges `accepted/alt.py` but passes pytest's `tmp_path` as `work_root`, and pytest's `rm_rf` downgrades cleanup permission errors to a warning; `tests/docker/test_cli.py` is the only test that goes through `TemporaryDirectory`, and it only judges C++.

Fix directions (any one is sufficient): run containers with `--user $(id -u):$(id -g)`; or replace `TemporaryDirectory` with an explicit directory plus `shutil.rmtree(..., ignore_errors=True)`; or `chmod -R 0777` the work dir from inside the container at the end of `compile.sh`.

---

## Important

### I2. OLE never produces `wrong_answer` — the verdict priority contradicts the runner's kill mechanism

`src/icpc_verify/results.py:60-75` vs `image/runner.py:88-92`

Spec §6.3 requires `stdout > output-limit-mib` → `wrong_answer` (reported as OLE). `classify_run` checks `m.signal` (→ `run_time_error`) **before** `m.output_limit_exceeded`. But the only way the runner detects an over-limit program mid-flight is to `killpg(SIGKILL)` it, which always sets `signal = 9`. So every runaway-output submission is classified `run_time_error`, never `wrong_answer`.

Verified by running `image/runner.py` directly against a program that writes stdout forever:

```json
{"wall": 0.058, "cpu": 0.052, "max_rss_kib": ..., "exit_code": -1,
 "signal": 9, "timed_out": false, "output_limit_exceeded": true}
```

Feeding that measurement to `classify_run` yields `run_time_error`. The only path that does produce `wrong_answer` is the post-hoc size check for a program that exceeded the limit but exited on its own within the 50 ms poll window — i.e. exactly the case that is *not* the interesting one. Failure scenario: a `solutions/wrong_answer/` submission with an unterminated print loop is judged `run_time_error`, and `verdict-match: exact` fails the package for a problem that is actually fine. Fix: move the `output_limit_exceeded` check above the `signal`/`exit_code` checks (it must stay below the time checks, since a hard-kill also SIGKILLs), or have the runner record *why* it killed.

### I3. A missing `run.json` fabricates `wall = hard_kill`, turning infrastructure failures into silent `time_limit_exceeded`

`src/icpc_verify/judge.py:141-151`

When `/out/run.json` is absent, `_run_one_testcase` synthesises a measurement with `wall=limits.hard_kill`. Since `hard_kill > limit` always, `classify_run` returns `time_limit_exceeded` before it ever looks at `oom_killed` or the exit code. `run.json` is absent whenever the run container did not reach the end of `runner.py`: `docker run` itself failed (invalid `--cpuset-cpus`, image gone, daemon restarted), the runner crashed (see M10), or the cgroup OOM killer picked the runner instead of the solution — the last of which is a direct spec violation, since §6.3 maps OOMKilled to `run_time_error`. Compounding it, `_run_one_testcase` discards `result.stdout` and `result.stderr` from the sandbox entirely, so docker's own error message is never recorded anywhere.

Failure scenario: the judge CPU is offlined by a concurrent step, so `docker run --cpuset-cpus=3` fails for every testcase. A `solutions/time_limit_exceeded/` solution then reports `time_limit_exceeded` with `expectation_met: true` and the CLI exits 0 — a green run in which nothing executed. Fix: treat a missing `run.json` as `judge_error` (the constant already exists and is currently unreachable) and attach the sandbox's stderr to the message.

### I4. `validation: custom` problems are silently judged with the default comparator

`src/icpc_verify/cli.py:67-72`, `src/icpc_verify/judge.py:205`

`load_problem_config` faithfully resolves `ValidationMode.CUSTOM` / `CUSTOM_INTERACTIVE` and even locates the validator directory, but nothing downstream ever reads `config.validation`. `judge_solution` unconditionally calls `parse_compare_flags(config.validator_flags)` and `compare_output`. Plan 1 is explicitly scoped to `validation: default`; the correct behaviour for the other modes is a clear refusal, not a wrong answer. Two distinct bad outcomes: (a) a custom-checker problem whose `validator_flags` happen to be default-validator flags (or empty) is judged token-by-token, so every solution to an any-valid-answer problem is reported `wrong_answer` with no indication the checker was ignored; (b) any other flag makes `parse_compare_flags` raise `CompareFlagError`, which is not caught (see I5). Fix: raise `ProblemConfigError` in `run_judge` when `config.validation is not ValidationMode.DEFAULT`.

### I5. Unhandled exception types exit 1, which the CLI's own contract defines as "verdict mismatch"

`src/icpc_verify/cli.py:132-140`

`main` catches only `ProblemConfigError`, `TestDataError`, `CpuError`, `OvershootSpecError`, and `OSError`. Everything else escapes, and an uncaught exception exits the process with status 1 — the same code as `EXIT_MISMATCH`. Reachable escapees, all on ordinary failure paths: `SandboxError` (docker binary not on PATH), `ValueError` from `float(reference_result.stdout.decode().strip())` in `measure_machine_factor` when the bench container fails, `json.JSONDecodeError`/`KeyError` from a truncated `run.json`, `CompareFlagError` from a non-default validator flag, and `UnicodeDecodeError` from `compile.py:104`'s strict decode of `run.sh` output. Failure scenario: the docker daemon is down; the CLI prints a Python traceback and exits 1; plan 3's reporting job reads that as "solution's verdict did not match its directory" and reports a bogus judging failure rather than an infrastructure error. Fix: add a catch-all that maps unexpected exceptions to `EXIT_CONFIG` (or a dedicated code) with the traceback on stderr.

---

## Minor

### M6. `cpu_isolated: true` is reported even when the sibling offline failed
`src/icpc_verify/cli.py:89,106` — `apply_cpu_plan` returns per-CPU failure warnings, but `options.cpu_isolated` is taken from `cpu_plan.isolated`, which was decided before the attempt. On a runner where `sudo tee` is unavailable, `result.json` claims isolated timing that was not achieved; the warning is present but a report consumer keying on `cpu_isolated` is misled.

### M7. `/proc/cpuinfo` is read before the architecture check
`src/icpc_verify/cli.py:82` — `read_cpu_flags()` is evaluated as an argument, so on a non-Linux or non-x86_64 host the user gets `No such file or directory: /proc/cpuinfo` instead of spec §7's step-1 message "x86_64 runner가 필요합니다". Ordering only; both exit 2.

### M8. stderr is kept head-only, spec asks for head+tail
`src/icpc_verify/judge.py:158` — spec §8 says "stderr는 앞뒤 합쳐 8 KiB만 남긴다"; the code keeps the first 8 KiB. For a crash whose diagnostic is the *last* line (the usual case), the useful part is the part dropped.

### M9. `RLIMIT_CPU` backstop is `int(hard_kill) + 2`, spec says `ceil(hard_kill) + 1`
`image/runner.py:53` — identical for fractional `hard_kill`, one second looser for integral values. Errs on the permissive side, so it cannot cause a false TLE; it is only a backstop behind the wall-clock kill.

### M10. The copied testcase input keeps its source file mode
`src/icpc_verify/judge.py:91-93` — `run_dir` is chmod'ed to `0755` but `shutil.copy2` preserves the mode of `<case>.in`. A package whose data files are `0600` (restrictive umask on a self-hosted runner) is unreadable by the cap-dropped container root; `runner.py` then dies opening it, and the run lands in the fabricated-TLE path of I3 with no diagnostic.

### M11. No cap on stderr, and the stdout cap can overshoot by one poll interval
`image/runner.py:37-45` — the watcher polls `getsize` every 50 ms, so a fast writer can put roughly 50 ms of output on the host disk past the limit before the kill (bounded, acceptable). stderr, however, has no limit at all inside the container; the 8 KiB truncation happens host-side after the fact. A submission that spams stderr can write for the entire `hard_kill` window straight onto the runner's disk. Spec only caps stdout, so this is a hardening gap rather than a deviation.

### M12. `--input -` from the documented runner interface is not implemented
`image/runner.py:62` — the Task 8 interface documents `--input <path|->`, but the value is always passed to `open()`, so `-` raises `FileNotFoundError`. `judge.py` always passes a real path, so nothing is broken today; the documented contract is simply wider than the code.

### M13. `rmtree(ignore_errors=True)` followed by `mkdir()` without `exist_ok`
`src/icpc_verify/judge.py:85-87` — if the per-case cleanup silently fails, the next line raises `FileExistsError` rather than a useful message. Today `out_dir` only ever receives root-owned *files* inside a `0777` directory, so removal succeeds; this is latent, not live.

---

## Deferred-minor triage

| # | Ledger line | Verdict | Reasoning |
|---|---|---|---|
| 1 | Task 1 — ruff excludes the whole `docs/` dir | OK-TO-DEFER | `docs/` holds prose and illustrative code blocks only; narrowing the pattern has no effect on shipped code. |
| 2 | Task 8 — no `RLIMIT_CPU` backstop test | OK-TO-DEFER | The backstop sits behind the wall-clock kill, which *is* tested (`test_hard_kill`); an untested backstop cannot produce a wrong verdict on its own. |
| 3 | Task 8 — `max_rss` units unverifiable on macOS | OK-TO-DEFER | CI on Linux exercises the KiB semantics and `test_runtime_is_recorded` asserts `mem_kib > 0`; the value is reported, never compared against a limit, so a unit error cannot change a verdict. |
| 4 | Task 6 — unsupported files inside multi-file solution dirs are silently dropped | OK-TO-DEFER | Matches DOMjudge behaviour for auxiliary files; a stray `.txt` in a solution directory should not fail discovery. |
| 5 | Task 9 — unused `xz-utils` in the Dockerfile | OK-TO-DEFER | The pinned CPython asset is `.tar.gz` and is extracted with `tar -xzf`, so the package is genuinely dead weight — image size only, no behaviour. |
| 6 | Task 12 — strict-vs-replace UTF-8 decode of `run.sh` stdout | OK-TO-DEFER | `run.sh` emits argv built from image-controlled strings plus the entry name, so a decode failure needs a non-UTF-8 filename. Note it is one of the escapees listed in I5; fixing I5 covers the blast radius. |
| 7 | Task 14 — unused `problem_dir` parameter on `judge_solution` | OK-TO-DEFER | Dead parameter, no behaviour. Plan 2 will need `problem_dir` for the validator directory anyway. |
| 8 | Task 14 — `/run` chosen as the testcase mount name | OK-TO-DEFER | `/run` is an FHS runtime directory, but the container has no systemd, a read-only rootfs, and no service needing it. Worth revisiting only because Java is never executed end-to-end today (see future work), so the JVM's behaviour under a shadowed `/run` is unverified — the JVM writes its perf data to `/tmp`, so the risk is low. |

All eight are OK-TO-DEFER; none is MUST-FIX-BEFORE-MERGE.

---

## What the 108 + 38 tests systematically cannot catch

Non-blocking, but this is the shape of the gap that produced C1, I2, and I3:

1. **Host-side consequences of container-root writes.** Every docker test receives pytest's `tmp_path`, whose cleanup downgrades permission errors to warnings. Production uses `TemporaryDirectory`, which raises. No test observes ownership or mode of what the container leaves behind.
2. **Verdict composition across the module boundary.** `test_results.py` feeds `classify_run` hand-built `RunMeasurement`s and `test_runner.py` checks `runner.py`'s JSON in isolation — but no test ever pipes a *real* runner measurement into `classify_run`. That is precisely where I2 lives: both halves are individually correct and their composition is not.
3. **Negative infrastructure paths.** Nothing exercises a failing `docker run`, a missing `run.json`, or a corrupt one; the fabricated-TLE fallback in I3 has never executed in a test.
4. **Language coverage past compilation.** Java is compiled and its argv is checked, but no Java program is ever *executed* through `_run_one_testcase` — so `-Xmx`, `-Xrs`, the shadowed `/run`, and JVM startup under `--cap-drop ALL --read-only` are unverified. Multi-file Python (`main.py`) and packaged Java are likewise never run.
5. **CLI coverage.** `test_cli.py` judges one C++ solution; the CLI path for the other three languages is untested, which is why C1 survived to HEAD.

## Future work (non-blocking)

- Run judge containers with `--user $(id -u):$(id -g)`. It removes the root-owned-file class entirely (C1, M13), drops container root, and makes the `0777` chmods unnecessary.
- Add `RLIMIT_FSIZE` in `runner.py` as a hard backstop for the output limit, and cap stderr the same way (M11).
- Add end-to-end docker tests for: OLE through `judge_solution` (would have caught I2), a deliberately broken image asserting `judge_error` rather than TLE (I3), Java execution, and the CLI on all four languages (C1).
- Make `judge_error` reachable for infrastructure failures; today only `solution_verdict([])` can produce it.
- Pin the real ghcr digest in `image/IMAGE_DIGEST`. The committed value `icpc-judge:test` is the local build tag the plan's README prescribes, so this satisfies plan 1's completion criterion, but `_default_image()` currently resolves to a tag that exists only on a machine that just built it; `publish-image.yml` prints the digest for manual commit.
- Containers leak if the CLI itself is SIGKILLed between `docker run` and the `finally` cleanup; `--rm` alongside the existing `rm -f` would narrow that.
- `_compare_exact` (space_change_sensitive) strips only `\n`, so a CRLF-authored `.ans` mismatches. Default token mode is unaffected.
- `time_multiplier` is parsed and stored but unused in plan 1 — expected, it belongs to plan 3's time-limit recommendation.

## Confirmed conformant

For the record, these were checked against the spec and are correct: overshoot arithmetic and `|`/`&` semantics (§6.1); `wall <= limit` as the pass boundary including the exact-boundary case; the hard-kill path yielding TLE ahead of the resulting SIGKILL; OOMKilled → `run_time_error` on the normal path; lazy judging with `not_run` fill and first-non-AC solution verdict (§6.4); `verdict-match` exact / any-rejected (§6.5); CPU planning for 1-core, multi-core, no-SMT, and explicitly requested CPUs (§7); machine factor as median-of-3 over the image-baked reference (§7.1); Java `-Xmx = limit - 256`, floor 256 (§6.2); the container flag set including `--cap-drop ALL`, `--network none`, `--pids-limit`, `--read-only`, and `--memory-swap` equal to `--memory` (§8); and the toolchain defaults with no `-march=native` and working AVX2 intrinsics. Answer files are never mounted into the container, so a submission cannot read the expected output — the central sandbox property holds.
