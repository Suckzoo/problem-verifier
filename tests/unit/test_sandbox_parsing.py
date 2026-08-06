from pathlib import Path

from icpc_verify.sandbox import SandboxSpec, _build_run_argv, _parse_oom_killed


def _spec(**overrides):
    base = dict(
        image="icpc-judge:test",
        cpuset=0,
        memory_mib=256,
        binds=(),
        argv=("true",),
        timeout=5.0,
        user=None,
        workdir=None,
    )
    base.update(overrides)
    return SandboxSpec(**base)


def test_workdir_none_omits_dash_w():
    argv = _build_run_argv(_spec(), "test-name")
    assert "-w" not in argv


def test_workdir_set_adds_dash_w_flag():
    argv = _build_run_argv(_spec(workdir="/validator"), "test-name")
    assert "-w" in argv
    assert argv[argv.index("-w") + 1] == "/validator"


def test_binds_and_image_argv_come_after_workdir(tmp_path: Path):
    argv = _build_run_argv(
        _spec(workdir="/validator", binds=((tmp_path, "/validator", "ro"),)), "test-name"
    )
    assert argv.index("-w") < argv.index("-v")
    assert argv[-2:] == ["icpc-judge:test", "true"]


def test_true_when_oom_killed_is_true():
    assert _parse_oom_killed(b'{"OOMKilled": true, "ExitCode": 137}') is True


def test_false_when_oom_killed_is_false():
    assert _parse_oom_killed(b'{"OOMKilled": false, "ExitCode": 0}') is False


def test_false_when_key_is_missing():
    assert _parse_oom_killed(b'{"ExitCode": 0}') is False


def test_false_when_empty():
    assert _parse_oom_killed(b"") is False
    assert _parse_oom_killed(b"   \n") is False


def test_false_when_not_json():
    assert _parse_oom_killed(b"not json at all") is False


def test_false_when_json_is_null():
    assert _parse_oom_killed(b"null") is False


def test_false_when_json_is_a_list():
    assert _parse_oom_killed(b"[]") is False


def test_false_when_json_is_a_scalar():
    assert _parse_oom_killed(b"123") is False
