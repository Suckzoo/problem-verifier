import pytest

from icpc_verify.compare import CompareFlagError, compare_output, parse_compare_flags

NONE = parse_compare_flags([])


def ok(team, answer, flags=NONE):
    accepted, message = compare_output(team.encode(), answer.encode(), flags)
    return accepted, message


def test_identical_output():
    assert ok("1 2 3\n", "1 2 3\n")[0]


def test_trailing_newline_is_ignored():
    assert ok("1 2 3", "1 2 3\n")[0]


def test_whitespace_amount_is_ignored_by_default():
    assert ok("1   2\n\n3\n", "1 2 3\n")[0]


def test_case_is_ignored_by_default():
    assert ok("YES\n", "yes\n")[0]


def test_case_sensitive_flag():
    flags = parse_compare_flags(["case_sensitive"])
    assert not ok("YES\n", "yes\n", flags)[0]
    assert ok("yes\n", "yes\n", flags)[0]


def test_space_change_sensitive_flag():
    flags = parse_compare_flags(["space_change_sensitive"])
    assert not ok("1  2\n", "1 2\n", flags)[0]
    assert ok("1 2\n", "1 2\n", flags)[0]


def test_token_count_mismatch_reports_position():
    accepted, message = ok("1 2\n", "1 2 3\n")
    assert not accepted
    assert "3" in message


def test_float_tolerance_sets_both():
    flags = parse_compare_flags(["float_tolerance", "1e-6"])
    assert flags.float_absolute_tolerance == pytest.approx(1e-6)
    assert flags.float_relative_tolerance == pytest.approx(1e-6)
    assert ok("1.0000001\n", "1.0\n", flags)[0]
    assert not ok("1.1\n", "1.0\n", flags)[0]


def test_absolute_tolerance_only():
    flags = parse_compare_flags(["float_absolute_tolerance", "0.5"])
    assert ok("1000000.4\n", "1000000.0\n", flags)[0]
    assert not ok("2.0\n", "1.0\n", flags)[0]


def test_relative_tolerance_only():
    flags = parse_compare_flags(["float_relative_tolerance", "0.01"])
    assert ok("101.0\n", "100.0\n", flags)[0]
    assert not ok("110.0\n", "100.0\n", flags)[0]


def test_either_tolerance_passing_is_enough():
    flags = parse_compare_flags(["float_tolerance", "0.01"])
    assert ok("0.005\n", "0.0\n", flags)[0]


def test_non_numeric_tokens_compare_as_text_even_with_float_flags():
    flags = parse_compare_flags(["float_tolerance", "1e-6"])
    assert ok("abc\n", "abc\n", flags)[0]
    assert not ok("abc\n", "abd\n", flags)[0]


def test_nan_never_matches():
    flags = parse_compare_flags(["float_tolerance", "1e-6"])
    assert not ok("nan\n", "1.0\n", flags)[0]


def test_unknown_flag_raises():
    with pytest.raises(CompareFlagError):
        parse_compare_flags(["no_such_flag"])


def test_tolerance_without_value_raises():
    with pytest.raises(CompareFlagError):
        parse_compare_flags(["float_tolerance"])


def test_invalid_utf8_is_tolerated():
    accepted, _ = compare_output(b"\xff\xfe\n", b"\xff\xfe\n", NONE)
    assert accepted
