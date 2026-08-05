from icpc_verify import verdicts


def test_expected_verdicts_are_kattis_directory_names():
    assert verdicts.EXPECTED_VERDICTS == (
        "accepted",
        "wrong_answer",
        "time_limit_exceeded",
        "run_time_error",
    )


def test_every_verdict_has_an_icon():
    all_verdicts = {
        verdicts.ACCEPTED,
        verdicts.WRONG_ANSWER,
        verdicts.TIME_LIMIT_EXCEEDED,
        verdicts.RUN_TIME_ERROR,
        verdicts.COMPILER_ERROR,
        verdicts.JUDGE_ERROR,
        verdicts.NOT_RUN,
    }
    assert all_verdicts <= set(verdicts.SUMMARY_ICON)


def test_not_run_icon_is_white():
    assert verdicts.SUMMARY_ICON[verdicts.NOT_RUN] == "⬜"
