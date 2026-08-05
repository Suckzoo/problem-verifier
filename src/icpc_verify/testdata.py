"""data/ 아래의 testcase 수집.

평평한 구조(data/01.in)와 Kattis 중첩 구조(data/secret/03.in)를 모두 지원한다.
.ans 는 같은 디렉토리에 같은 이름으로 있어야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class TestDataError(Exception):
    """data/ 구조가 잘못되었다."""


@dataclass(frozen=True)
class TestCase:
    id: str
    group: str
    input_path: Path
    answer_path: Path


def collect_testcases(problem_dir: Path) -> list[TestCase]:
    data_dir = problem_dir / "data"
    if not data_dir.is_dir():
        raise TestDataError(f"data/ 디렉토리가 없습니다: {data_dir}")

    cases: list[TestCase] = []
    for input_path in sorted(data_dir.rglob("*.in")):
        rel = input_path.relative_to(data_dir).with_suffix("")
        answer_path = input_path.with_suffix(".ans")
        if not answer_path.is_file():
            raise TestDataError(f"{rel.as_posix()} 의 .ans 파일이 없습니다: {answer_path}")
        cases.append(
            TestCase(
                id=rel.as_posix(),
                group=rel.parent.as_posix() if rel.parent != Path(".") else "",
                input_path=input_path,
                answer_path=answer_path,
            )
        )

    if not cases:
        raise TestDataError(f"testcase 를 찾지 못했습니다: {data_dir}")
    return cases
