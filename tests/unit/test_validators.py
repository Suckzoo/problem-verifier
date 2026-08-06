import pytest

from icpc_verify import verdicts
from icpc_verify.solutions import Language
from icpc_verify.validators import (
    ValidatorError,
    plan_validator_build,
    read_judgemessage,
    validator_verdict,
)


def make_dir(tmp_path, files):
    d = tmp_path / "check"
    d.mkdir()
    for name, text in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return d


def test_build_script_wins(tmp_path):
    d = make_dir(tmp_path, {"build": "#!/bin/sh\n", "check.cpp": "int main(){}"})
    plan = plan_validator_build(d)
    assert plan.kind == "build-script"
    assert plan.solution is None


def test_run_script_without_build(tmp_path):
    d = make_dir(tmp_path, {"run": "#!/bin/sh\nexit 42\n"})
    plan = plan_validator_build(d)
    assert plan.kind == "run-script"


def test_sources_inferred(tmp_path):
    d = make_dir(tmp_path, {"check.cpp": "int main(){}", "validate.h": "// header"})
    plan = plan_validator_build(d)
    assert plan.kind == "sources"
    assert plan.solution is not None
    assert plan.solution.language is Language.CPP
    assert [p.name for p in plan.solution.sources] == ["check.cpp"]


def test_python_validator_entry(tmp_path):
    d = make_dir(tmp_path, {"grade.py": "print(42)"})
    plan = plan_validator_build(d)
    assert plan.solution.language is Language.PYTHON
    assert plan.solution.entry == "grade.py"


def test_empty_dir_raises(tmp_path):
    d = make_dir(tmp_path, {"README.md": "docs only"})
    with pytest.raises(ValidatorError, match="소스"):
        plan_validator_build(d)


def test_mixed_language_raises(tmp_path):
    d = make_dir(tmp_path, {"a.cpp": "int main(){}", "b.py": "pass"})
    with pytest.raises(ValidatorError, match="언어"):
        plan_validator_build(d)


def test_missing_dir_raises(tmp_path):
    with pytest.raises(ValidatorError, match="디렉토리"):
        plan_validator_build(tmp_path / "nope")


@pytest.mark.parametrize(
    ("code", "verdict"),
    [
        (42, verdicts.ACCEPTED),
        (43, verdicts.WRONG_ANSWER),
        (0, verdicts.JUDGE_ERROR),
        (1, verdicts.JUDGE_ERROR),
        (-11, verdicts.JUDGE_ERROR),
    ],
)
def test_validator_verdict(code, verdict):
    assert validator_verdict(code) == verdict


def test_read_judgemessage_caps_at_4096(tmp_path):
    (tmp_path / "judgemessage.txt").write_text("x" * 10000, encoding="utf-8")
    assert read_judgemessage(tmp_path) == "x" * 4096


def test_read_judgemessage_missing(tmp_path):
    assert read_judgemessage(tmp_path) == ""


def test_describe_unit_is_public(tmp_path):
    from icpc_verify.solutions import describe_unit

    src = tmp_path / "v"
    src.mkdir()
    (src / "main.cpp").write_text("int main(){}", encoding="utf-8")
    solution, warning = describe_unit(src, tmp_path, "validator")
    assert warning is None
    assert solution.rel_path == "v"
    assert solution.expected == "validator"
    assert solution.language is Language.CPP
