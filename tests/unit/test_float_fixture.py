from pathlib import Path

from icpc_verify.compare import compare_output, parse_compare_flags
from icpc_verify.problemcfg import load_problem_config
from icpc_verify.testdata import collect_testcases

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "float"


def test_fixture_parses_with_nested_data():
    config = load_problem_config(FIXTURE, default_time_limit=1.0, default_memory_mib=2048)
    assert config.validator_flags == ("float_tolerance", "1e-4")
    cases = collect_testcases(FIXTURE)
    assert [c.id for c in cases] == ["sample/01", "secret/02"]
    assert [c.group for c in cases] == ["sample", "secret"]


def test_accepted_output_within_tolerance():
    flags = parse_compare_flags(["float_tolerance", "1e-4"])
    ok, _ = compare_output(b"3.1416\n", b"3.14159265\n", flags)
    assert ok


def test_rough_output_outside_tolerance():
    flags = parse_compare_flags(["float_tolerance", "1e-4"])
    ok, _ = compare_output(b"3.14\n", b"3.14159265\n", flags)
    assert not ok
