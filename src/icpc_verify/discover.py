"""무엇을 채점할지 결정한다 (spec §5).

순수 함수만 둔다. git 호출과 이벤트 파싱은 cli.py 가 한다.
"""

from __future__ import annotations

from .solutions import Solution

FULL_EVENTS = ("workflow_dispatch", "schedule")
PROBLEM_GLOBAL_PREFIXES = ("data/", "output_validators/", "output_validator/", "include/")


def _relativize(path: str, problem_dir_rel: str) -> str | None:
    """repo 기준 경로를 문제 디렉토리 기준으로 바꾼다. 문제 밖이면 None."""
    if not problem_dir_rel or problem_dir_rel == ".":
        return path
    prefix = problem_dir_rel.rstrip("/") + "/"
    if path.startswith(prefix):
        return path[len(prefix) :]
    return None


def decide_scope(
    *,
    full_flag: bool,
    event_name: str,
    changed_files: list[str] | None,
    problem_dir_rel: str,
) -> tuple[bool, str]:
    if full_flag:
        return True, "full input 이 켜져 있습니다"
    if event_name in FULL_EVENTS:
        return True, f"{event_name} 이벤트는 전체를 재채점합니다"
    if changed_files is None:
        return True, "변경 목록(diff)을 계산할 수 없어 전체로 fallback 합니다"

    for path in changed_files:
        rel = _relativize(path, problem_dir_rel)
        if rel is None:
            continue
        if rel == "problem.yaml" or rel.startswith(PROBLEM_GLOBAL_PREFIXES):
            return True, f"문제 전역 파일이 바뀌었습니다: {path}"
    return False, "solution 변경만 감지되었습니다"


def changed_solution_units(changed_files: list[str], problem_dir_rel: str) -> set[str]:
    """변경 파일을 solution 단위 rel_path 로 사상한다.

    solutions/<verdict>/<file> 은 그 파일이, solutions/<verdict>/<dir>/... 은
    첫 단계 디렉토리가 단위다. 둘 다 parts[1]/parts[2] 로 같다.
    """
    units: set[str] = set()
    for path in changed_files:
        rel = _relativize(path, problem_dir_rel)
        if rel is None or not rel.startswith("solutions/"):
            continue
        parts = rel.split("/")
        if len(parts) < 3:
            continue
        units.add(f"{parts[1]}/{parts[2]}")
    return units


def build_matrix(solutions: list[Solution], *, full: bool, changed_units: set[str]) -> list[dict]:
    entries: list[dict] = []
    for solution in solutions:
        if not full and solution.rel_path not in changed_units:
            continue
        entries.append(
            {
                "name": solution.name,
                "path": solution.rel_path,
                "expected": solution.expected,
                "lang": solution.language.value if solution.language else "",
            }
        )
    return entries
