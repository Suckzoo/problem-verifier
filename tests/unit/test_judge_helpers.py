"""docker 없이도 테스트할 수 있는 judge.py 의 순수 함수들이다."""

from icpc_verify.judge import _describe_missing_run_result


def test_missing_run_result_includes_sandbox_stderr():
    message = _describe_missing_run_result(b"docker: Error response from daemon: xyz\n")
    assert "run.json" in message
    assert "docker: Error response from daemon: xyz" in message


def test_missing_run_result_without_stderr_is_still_informative():
    message = _describe_missing_run_result(b"")
    assert "run.json" in message
    assert "stderr" not in message


def test_missing_run_result_trims_to_keep_bytes():
    huge = b"x" * (9 * 1024)
    message = _describe_missing_run_result(huge)
    # STDERR_KEEP_BYTES 는 8 KiB 다
    assert message.count("x") <= 8 * 1024
