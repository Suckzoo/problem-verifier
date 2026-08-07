from icpc_verify.judge import _make_excerpt
from icpc_verify.results import TestCaseResult


def test_excerpt_fields_default_empty():
    case = TestCaseResult(
        id="01",
        group="",
        verdict="accepted",
        wall=0.1,
        cpu=0.1,
        mem_kib=1,
        exit_code=0,
        message="",
    )
    assert case.expected_excerpt == ""
    assert case.actual_excerpt == ""


def test_make_excerpt_short_passthrough():
    assert _make_excerpt(b"1 2 3\n", 100) == "1 2 3\n"


def test_make_excerpt_caps_and_marks():
    text = _make_excerpt(b"x" * 50, 10)
    assert text.startswith("x" * 10)
    assert text.endswith("(잘림)")


def test_make_excerpt_tolerates_invalid_utf8():
    text = _make_excerpt(b"\xff\xfeok", 100)
    assert "ok" in text
