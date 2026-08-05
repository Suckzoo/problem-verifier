import pytest

from icpc_verify.problemcfg import (
    ProblemConfigError,
    ValidationMode,
    load_problem_config,
)

DEFAULTS = {"default_time_limit": 1.0, "default_memory_mib": 2048}


def write_problem(tmp_path, yaml_text, *, validator_dir=None):
    (tmp_path / "problem.yaml").write_text(yaml_text, encoding="utf-8")
    if validator_dir:
        (tmp_path / validator_dir).mkdir(parents=True)
        (tmp_path / validator_dir / "check.cpp").write_text("int main(){}", encoding="utf-8")
    return tmp_path


def test_legacy_defaults(tmp_path):
    write_problem(tmp_path, "name: Hello\n")
    cfg = load_problem_config(tmp_path, **DEFAULTS)
    assert cfg.name == "Hello"
    assert cfg.time_limit == 1.0
    assert cfg.memory_mib == 2048
    assert cfg.time_multiplier == 5.0
    assert cfg.validation is ValidationMode.DEFAULT
    assert cfg.validator_flags == ()
    assert cfg.validator_dir is None
    assert cfg.format_version == "legacy"


def test_legacy_custom_validator(tmp_path):
    write_problem(
        tmp_path,
        "name: Hello\nvalidation: custom\nvalidator_flags: float_tolerance 1e-6\n",
        validator_dir="output_validators/check",
    )
    cfg = load_problem_config(tmp_path, **DEFAULTS)
    assert cfg.validation is ValidationMode.CUSTOM
    assert cfg.validator_flags == ("float_tolerance", "1e-6")
    assert cfg.validator_dir.name == "check"


def test_legacy_interactive(tmp_path):
    write_problem(
        tmp_path,
        "name: Hello\nvalidation: custom interactive\n",
        validator_dir="output_validators/inter",
    )
    cfg = load_problem_config(tmp_path, **DEFAULTS)
    assert cfg.validation is ValidationMode.CUSTOM_INTERACTIVE


def test_legacy_limits(tmp_path):
    write_problem(tmp_path, "name: Hello\nlimits:\n  memory: 512\n  time_multiplier: 3\n")
    cfg = load_problem_config(tmp_path, **DEFAULTS)
    assert cfg.memory_mib == 512
    assert cfg.time_multiplier == 3.0


def test_new_format(tmp_path):
    write_problem(
        tmp_path,
        "problem_format_version: 2023-07-draft\n"
        "name: Hello\n"
        "type: pass-fail\n"
        "limits:\n  time_limit: 2.5\n  memory: 1024\n",
    )
    cfg = load_problem_config(tmp_path, **DEFAULTS)
    assert cfg.format_version == "2023-07"
    assert cfg.time_limit == 2.5
    assert cfg.memory_mib == 1024
    assert cfg.validation is ValidationMode.DEFAULT


def test_new_format_singular_validator_dir(tmp_path):
    write_problem(
        tmp_path,
        "problem_format_version: 2023-07-draft\nname: Hello\ntype: pass-fail\n",
        validator_dir="output_validator",
    )
    cfg = load_problem_config(tmp_path, **DEFAULTS)
    assert cfg.validation is ValidationMode.CUSTOM
    assert cfg.validator_dir.name == "output_validator"


def test_scoring_type_is_rejected(tmp_path):
    write_problem(
        tmp_path,
        "problem_format_version: 2023-07-draft\nname: Hello\ntype: scoring\n",
    )
    with pytest.raises(ProblemConfigError, match="pass-fail"):
        load_problem_config(tmp_path, **DEFAULTS)


def test_missing_file(tmp_path):
    with pytest.raises(ProblemConfigError, match="problem.yaml"):
        load_problem_config(tmp_path, **DEFAULTS)


def test_broken_yaml(tmp_path):
    (tmp_path / "problem.yaml").write_text("name: [unclosed\n", encoding="utf-8")
    with pytest.raises(ProblemConfigError):
        load_problem_config(tmp_path, **DEFAULTS)


def test_custom_validation_without_validator_dir(tmp_path):
    write_problem(tmp_path, "name: Hello\nvalidation: custom\n")
    with pytest.raises(ProblemConfigError, match="output_validator"):
        load_problem_config(tmp_path, **DEFAULTS)


def test_multiple_legacy_validator_dirs_is_rejected(tmp_path):
    write_problem(
        tmp_path,
        "name: Hello\nvalidation: custom\n",
        validator_dir="output_validators/a",
    )
    (tmp_path / "output_validators" / "b").mkdir()
    with pytest.raises(ProblemConfigError, match="1개"):
        load_problem_config(tmp_path, **DEFAULTS)
