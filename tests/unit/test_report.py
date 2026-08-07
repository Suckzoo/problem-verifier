from icpc_verify.report import generate_report

PROBLEM = {
    "name": "Add Two Numbers",
    "time_limit": 1.0,
    "memory_mib": 512,
    "time_multiplier": 5.0,
    "validation": "default",
}


def case(id="01", verdict="accepted", wall=0.1, **kwargs):
    base = {
        "id": id,
        "group": "",
        "verdict": verdict,
        "wall": wall,
        "cpu": wall,
        "mem_kib": 1000,
        "exit_code": 0,
        "message": "",
        "expected_excerpt": "",
        "actual_excerpt": "",
    }
    base.update(kwargs)
    return base


def result(
    rel_path="accepted/main.cpp",
    expected="accepted",
    verdict="accepted",
    testcases=None,
    machine_factor=1.0,
    expectation_met=True,
    **kwargs,
):
    base = {
        "name": rel_path.replace("/", "_"),
        "rel_path": rel_path,
        "expected": expected,
        "language": "cpp",
        "verdict": verdict,
        "testcases": testcases if testcases is not None else [case()],
        "compile_log": "",
        "machine_factor": machine_factor,
        "cpu_isolated": True,
        "warnings": [],
        "expectation_met": expectation_met,
        "time_limit": 1.0,
        "hard_kill": 3.0,
    }
    base.update(kwargs)
    return base


def test_all_green_passes():
    r = generate_report([result()], PROBLEM, expected_matrix=None, verdict_match="exact")
    assert r.passed
    assert r.failures == []
    assert "Add Two Numbers" in r.markdown
    assert "🟩" in r.markdown


def test_mismatch_fails_and_is_listed():
    bad = result(
        rel_path="time_limit_exceeded/fast.cpp",
        expected="time_limit_exceeded",
        verdict="accepted",
        expectation_met=False,
    )
    r = generate_report([bad], PROBLEM, expected_matrix=None, verdict_match="exact")
    assert not r.passed
    assert any("time_limit_exceeded/fast.cpp" in f for f in r.failures)
    assert "❌" in r.markdown


def test_missing_result_fails():
    matrix = [
        {
            "name": "accepted_main.cpp",
            "path": "accepted/main.cpp",
            "expected": "accepted",
            "lang": "cpp",
        },
        {
            "name": "accepted_gone.py",
            "path": "accepted/gone.py",
            "expected": "accepted",
            "lang": "python",
        },
    ]
    r = generate_report([result()], PROBLEM, expected_matrix=matrix, verdict_match="exact")
    assert not r.passed
    assert any("accepted/gone.py" in f for f in r.failures)
    assert "미실행" in r.markdown or "누락" in r.markdown


def test_not_run_uses_white_square():
    cases = [case("01", "wrong_answer"), case("02", "not_run", wall=0.0)]
    bad = result(
        rel_path="wrong_answer/w.cpp",
        expected="wrong_answer",
        verdict="wrong_answer",
        testcases=cases,
    )
    r = generate_report([bad], PROBLEM, expected_matrix=None, verdict_match="exact")
    assert "🟥⬜" in r.markdown.replace("\n", "")


def test_stripes_wrap_at_20():
    cases = [case(f"{i:02d}") for i in range(1, 46)]
    r = generate_report(
        [result(testcases=cases)], PROBLEM, expected_matrix=None, verdict_match="exact"
    )
    lines = [ln for ln in r.markdown.splitlines() if ln and set(ln) <= {"🟩"}]
    assert [len(ln) for ln in lines] == [20, 20, 5]


def test_over_200_cases_collapses_to_summary():
    cases = [case(f"{i:03d}") for i in range(1, 202)]
    cases[100]["verdict"] = "wrong_answer"
    r = generate_report(
        [result(verdict="wrong_answer", expected="wrong_answer", testcases=cases)],
        PROBLEM,
        expected_matrix=None,
        verdict_match="exact",
    )
    assert "🟩🟩🟩" not in r.markdown  # 띠 없음
    assert "201" in r.markdown  # 개수 요약
    assert "101" in r.markdown  # 실패 id 목록


def test_suggested_time_limit():
    fast = result(testcases=[case(wall=0.2)], machine_factor=1.0)
    slow = result(
        rel_path="accepted/slow.py",
        language="python",
        testcases=[case(wall=0.42)],
        machine_factor=2.0,
    )
    r = generate_report([fast, slow], PROBLEM, expected_matrix=None, verdict_match="exact")
    # 보정 최저치: max(0.2/1.0, 0.42/2.0)=0.21 -> 0.21*5=1.05 -> ceil(10.5)/10=1.1
    assert "1.1" in r.markdown


def test_markdown_capped_under_900kib():
    cases = [case(f"{i:03d}", message="x" * 3000) for i in range(1, 150)]
    results = [result(rel_path=f"accepted/s{k}.cpp", testcases=list(cases)) for k in range(40)]
    r = generate_report(results, PROBLEM, expected_matrix=None, verdict_match="exact")
    assert len(r.markdown.encode()) <= 900 * 1024
    assert "HTML" in r.markdown  # 잘림 안내


def test_html_is_selfcontained_and_escapes():
    evil = result(
        rel_path="wrong_answer/evil.cpp",
        expected="wrong_answer",
        verdict="wrong_answer",
        testcases=[
            case(
                verdict="wrong_answer",
                message="<script>alert(1)</script>",
                expected_excerpt="<b>2 3</b>",
                actual_excerpt="1 & 4",
            )
        ],
    )
    r = generate_report([evil], PROBLEM, expected_matrix=None, verdict_match="exact")
    assert "<script>alert(1)" not in r.html
    assert "&lt;script&gt;" in r.html
    assert "&lt;b&gt;2 3&lt;/b&gt;" in r.html
    assert "http" not in r.html.lower() or "://" not in r.html  # 외부 참조 없음


def test_html_contains_runtime_bars():
    r = generate_report(
        [result(testcases=[case(wall=0.5)])],
        PROBLEM,
        expected_matrix=None,
        verdict_match="exact",
    )
    assert "time-bar" in r.html


def test_machine_factor_warning():
    r = generate_report(
        [result(machine_factor=1.5)], PROBLEM, expected_matrix=None, verdict_match="exact"
    )
    assert "1.50" in r.markdown
    assert "⚠" in r.markdown


def test_html_shows_accepted_message_but_not_not_run():
    cases = [
        case("01", "accepted", message="validator warning: trailing space"),
        case("02", "not_run", wall=0.0, message="skipped after earlier failure"),
    ]
    r = generate_report(
        [result(testcases=cases)], PROBLEM, expected_matrix=None, verdict_match="exact"
    )
    assert "validator warning: trailing space" in r.html
    assert "skipped after earlier failure" not in r.html
