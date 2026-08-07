"""result.json 들을 병합해 Job Summary(markdown)와 HTML 리포트를 만든다 (spec §11)."""

from __future__ import annotations

import html
import math
from dataclasses import dataclass

from . import verdicts

STRIPE_WIDTH = 20
MAX_STRIPE_CASES = 200
MAX_FAIL_IDS = 50
MAX_TABLE_ROWS = 100
MARKDOWN_CAP = 900 * 1024
MACHINE_FACTOR_WARN = 1.3


@dataclass(frozen=True)
class Report:
    markdown: str
    html: str
    passed: bool
    failures: list[str]


def _icon(verdict: str) -> str:
    return verdicts.SUMMARY_ICON.get(verdict, "⬜")


def _stripes(cases: list[dict]) -> str:
    icons = [_icon(c["verdict"]) for c in cases]
    lines = ["".join(icons[i : i + STRIPE_WIDTH]) for i in range(0, len(icons), STRIPE_WIDTH)]
    return "\n".join(lines)


def _case_summary(cases: list[dict]) -> str:
    counts: dict[str, int] = {}
    for c in cases:
        counts[c["verdict"]] = counts.get(c["verdict"], 0) + 1
    parts = [f"{_icon(v)} {v}: {n}" for v, n in sorted(counts.items())]
    failed = [c["id"] for c in cases if c["verdict"] not in (verdicts.ACCEPTED, verdicts.NOT_RUN)]
    text = f"testcase {len(cases)}개 — " + ", ".join(parts)
    if failed:
        shown = failed[:MAX_FAIL_IDS]
        more = f" 외 {len(failed) - len(shown)}개" if len(failed) > len(shown) else ""
        text += f"\n실패: {', '.join(shown)}{more}"
    return text


def _suggested_limit(results: list[dict], multiplier: float) -> float | None:
    slowest = 0.0
    for r in results:
        if r["expected"] != verdicts.ACCEPTED or r["verdict"] != verdicts.ACCEPTED:
            continue
        factor = r.get("machine_factor") or 1.0
        for c in r["testcases"]:
            if c["verdict"] == verdicts.ACCEPTED:
                slowest = max(slowest, c["wall"] / factor)
    if slowest <= 0.0:
        return None
    return math.ceil(slowest * multiplier * 10) / 10


def _runtime_table(cases: list[dict], time_limit: float) -> str:
    rows = ["| tc | verdict | wall | cpu | mem |", "|---|---|---|---|---|"]
    for c in cases[:MAX_TABLE_ROWS]:
        if c["verdict"] == verdicts.NOT_RUN:
            continue
        mem = f"{c['mem_kib'] // 1024}MB" if c["mem_kib"] else "-"
        rows.append(
            f"| {c['id']} | {_icon(c['verdict'])} {c['verdict']} "
            f"| {c['wall']:.3f} | {c['cpu']:.3f} | {mem} |"
        )
    if len(cases) > MAX_TABLE_ROWS:
        rows.append(f"| … | {len(cases) - MAX_TABLE_ROWS}개 생략 | | | |")
    return "\n".join(rows)


def _solution_section(r: dict) -> str:
    ok = r.get("expectation_met", False)
    mark = "✅" if ok else "❌"
    max_wall = max((c["wall"] for c in r["testcases"]), default=0.0)
    limit = r.get("time_limit", 0.0) or 0.0
    pct = f" ({max_wall / limit * 100:.0f}%)" if limit else ""
    factor = r.get("machine_factor", 1.0)
    factor_note = f" · factor {factor:.2f}" + (" ⚠" if factor > MACHINE_FACTOR_WARN else "")

    lines = [
        f"## {mark} {r['rel_path']}",
        f"{r['language']} · 기대 {r['expected']} · 실제 {r['verdict']}"
        f" · max {max_wall:.3f}s{pct}{factor_note}",
        "",
    ]
    cases = r["testcases"]
    if len(cases) > MAX_STRIPE_CASES:
        lines.append(_case_summary(cases))
    else:
        lines.append(_stripes(cases))
    if r["expected"] == verdicts.ACCEPTED or not ok:
        lines += ["", _runtime_table(cases, limit)]
    if r.get("compile_log") and r["verdict"] in (verdicts.COMPILER_ERROR, verdicts.JUDGE_ERROR):
        log = r["compile_log"][:4096]
        lines += ["", "```", log, "```"]
    # 브리프 코드는 verdict != accepted 인 케이스의 첫 메시지만 보였는데, 이러면
    # accepted 케이스에도 (예: validator 경고) 메시지가 달린 경우 리포트에서 사라진다.
    # verdict 와 무관하게 비어있지 않은 메시지를 전부 보여준다.
    messages = [c["message"] for c in cases if c["message"]]
    if messages:
        lines += [""] + [f"> {m[:500].replace(chr(10), ' / ')}" for m in messages]
    return "\n".join(lines)


def _overview_table(results: list[dict]) -> str:
    rows = [
        "| solution | 언어 | 기대 | 실제 | max wall | factor |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        mark = "✅" if r.get("expectation_met") else "❌"
        max_wall = max((c["wall"] for c in r["testcases"]), default=0.0)
        factor = r.get("machine_factor", 1.0)
        warn = " ⚠" if factor > MACHINE_FACTOR_WARN else ""
        rows.append(
            f"| {r['rel_path']} | {r['language']} | {r['expected']} "
            f"| {mark} {r['verdict']} | {max_wall:.3f}s | {factor:.2f}{warn} |"
        )
    return "\n".join(rows)


def generate_report(
    results: list[dict],
    problem: dict,
    *,
    expected_matrix: list[dict] | None,
    verdict_match: str,
) -> Report:
    results = sorted(results, key=lambda r: r["rel_path"])
    failures: list[str] = []
    for r in results:
        if not r.get("expectation_met"):
            failures.append(f"{r['rel_path']}: 기대 {r['expected']}, 실제 {r['verdict']}")

    missing: list[dict] = []
    if expected_matrix:
        seen = {r["rel_path"] for r in results}
        for entry in expected_matrix:
            if entry["path"] not in seen:
                missing.append(entry)
                failures.append(f"{entry['path']}: 결과 누락 (judge job 미완료)")

    header = [
        "# ICPC problem verify",
        "",
        f"문제: {problem['name']} · 시간제한 {problem['time_limit']:.3f}s"
        f" · 메모리 {problem['memory_mib']}MiB · validation {problem['validation']}",
    ]
    suggested = _suggested_limit(results, problem.get("time_multiplier", 5.0))
    if suggested is not None:
        header.append(
            f"권장 시간제한: **{suggested:.1f}s**"
            f" (가장 느린 accepted 기준, multiplier {problem.get('time_multiplier', 5.0):g})"
        )
    if missing:
        header.append(f"⚠ 결과 누락(미실행): {', '.join(e['path'] for e in missing)}")
    header += ["", _overview_table(results), ""]

    sections = [_solution_section(r) for r in results]
    markdown = "\n".join(header) + "\n" + "\n\n".join(sections)

    if len(markdown.encode()) > MARKDOWN_CAP:
        kept: list[str] = []
        size = len("\n".join(header).encode()) + 200
        for section in sections:
            size += len(section.encode()) + 2
            if size > MARKDOWN_CAP:
                kept.append("\n_(길이 제한으로 이하 생략 — HTML artifact 를 보세요)_")
                break
            kept.append(section)
        markdown = "\n".join(header) + "\n" + "\n\n".join(kept)

    html_doc = _render_html(results, problem, failures, suggested, missing)
    return Report(markdown=markdown, html=html_doc, passed=not failures, failures=failures)


_CSS = """
body{font-family:sans-serif;margin:2em;max-width:70em}
table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.3em .6em}
.grid span{display:inline-block;width:14px;height:14px;margin:1px;border-radius:2px}
.v-accepted{background:#2da44e}.v-wrong_answer{background:#cf222e}
.v-time_limit_exceeded{background:#bf8700}.v-run_time_error{background:#e16f24}
.v-compiler_error,.v-judge_error{background:#8250df}.v-not_run{background:#d0d7de}
.time-bar{display:inline-block;height:10px;background:#54aeff}
.limit{color:#cf222e}pre{background:#f6f8fa;padding:.6em;overflow-x:auto}
.fail{color:#cf222e}.ok{color:#2da44e}
"""


def _render_html(
    results: list[dict],
    problem: dict,
    failures: list[str],
    suggested: float | None,
    missing: list[dict],
) -> str:
    e = html.escape
    parts = [
        "<!doctype html><meta charset='utf-8'>",
        f"<title>{e(problem['name'])} — icpc-verify</title>",
        f"<style>{_CSS}</style>",
        f"<h1>{e(problem['name'])}</h1>",
        f"<p>시간제한 {problem['time_limit']:.3f}s · 메모리 {problem['memory_mib']}MiB"
        f" · validation {e(str(problem['validation']))}</p>",
    ]
    if suggested is not None:
        parts.append(f"<p>권장 시간제한: <b>{suggested:.1f}s</b></p>")
    if failures:
        items = "".join(f"<li>{e(f)}</li>" for f in failures)
        parts.append(f"<h2 class='fail'>실패 {len(failures)}건</h2><ul>{items}</ul>")
    else:
        parts.append("<h2 class='ok'>전부 기대대로입니다</h2>")

    for r in results:
        ok = r.get("expectation_met", False)
        parts.append(
            f"<h2>{'✅' if ok else '❌'} {e(r['rel_path'])}"
            f" <small>{e(r['language'])} · 기대 {e(r['expected'])}"
            f" · 실제 {e(r['verdict'])} · factor {r.get('machine_factor', 1):.2f}</small></h2>"
        )
        cells = "".join(
            f"<span class='v-{e(c['verdict'])}' title=\"{e(c['id'])}: {e(c['verdict'])}"
            f" wall {c['wall']:.3f}s cpu {c['cpu']:.3f}s mem {c['mem_kib']}KiB"
            f' exit {c["exit_code"]}"></span>'
            for c in r["testcases"]
        )
        parts.append(f"<div class='grid'>{cells}</div>")

        limit = r.get("time_limit", 0.0) or 0.0
        hard = r.get("hard_kill", 0.0) or 0.0
        scale = max(hard, limit, 0.001)
        bars = []
        for c in r["testcases"]:
            if c["verdict"] == verdicts.NOT_RUN:
                continue
            width = max(1, int(c["wall"] / scale * 300))
            bars.append(
                f"<div>{e(c['id'])} <span class='time-bar' style='width:{width}px'></span>"
                f" {c['wall']:.3f}s</div>"
            )
        if bars:
            limit_px = int(limit / scale * 300)
            parts.append(
                f"<p><small>기준선: <span class='limit'>|</span> 시간제한 {limit:.3f}s"
                f" (약 {limit_px}px 지점) · hard kill {hard:.3f}s (300px)</small></p>"
            )
            parts.extend(bars)

        for c in r["testcases"]:
            if c.get("expected_excerpt") or c.get("actual_excerpt"):
                parts.append(
                    f"<h3>{e(c['id'])} diff</h3>"
                    f"<b>expected</b><pre>{e(c['expected_excerpt'])}</pre>"
                    f"<b>actual</b><pre>{e(c['actual_excerpt'])}</pre>"
                )
            if c["message"] and c["verdict"] != verdicts.NOT_RUN:
                parts.append(f"<pre>{e(c['message'][:4096])}</pre>")

        if r.get("compile_log") and r["verdict"] in (verdicts.COMPILER_ERROR, verdicts.JUDGE_ERROR):
            parts.append(f"<h3>log</h3><pre>{e(r['compile_log'][:4096])}</pre>")

        for warning in r.get("warnings", []):
            parts.append(f"<p>⚠ {e(warning)}</p>")

    return "\n".join(parts)
