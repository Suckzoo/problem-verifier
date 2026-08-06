from icpc_verify.sandbox import _parse_oom_killed


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
