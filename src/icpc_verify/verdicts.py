"""verdict 이름과 표시용 기호.

이름은 Kattis 의 solutions/ 하위 디렉토리 이름과 같다.
DOMjudge/Kattis 에 MLE verdict 이 없으므로 OOM 은 run_time_error 로 매핑한다.
"""

from __future__ import annotations

ACCEPTED = "accepted"
WRONG_ANSWER = "wrong_answer"
TIME_LIMIT_EXCEEDED = "time_limit_exceeded"
RUN_TIME_ERROR = "run_time_error"
COMPILER_ERROR = "compiler_error"
JUDGE_ERROR = "judge_error"
NOT_RUN = "not_run"

EXPECTED_VERDICTS: tuple[str, ...] = (
    ACCEPTED,
    WRONG_ANSWER,
    TIME_LIMIT_EXCEEDED,
    RUN_TIME_ERROR,
)

SUMMARY_ICON: dict[str, str] = {
    ACCEPTED: "\U0001f7e9",
    WRONG_ANSWER: "\U0001f7e5",
    TIME_LIMIT_EXCEEDED: "\U0001f7e8",
    RUN_TIME_ERROR: "\U0001f7e7",
    COMPILER_ERROR: "\U0001f7ea",
    JUDGE_ERROR: "\U0001f7ea",
    NOT_RUN: "⬜",
}
