"""solutions/ 아래에서 채점 대상을 찾고 언어와 entry point 를 정한다.

solution 단위는 solutions/<verdict>/<이름>.<ext> 또는 solutions/<verdict>/<이름>/ 이다.
문제가 있는 solution 은 예외 대신 error 필드를 채워 돌려준다.
judge 단계가 그것을 compiler_error 로 바꾼다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatch
from pathlib import Path

from .verdicts import EXPECTED_VERDICTS

JAVA_MAIN_RE = re.compile(r"public\s+static\s+void\s+main\s*\(\s*String")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class Language(StrEnum):
    CPP = "cpp"
    C = "c"
    JAVA = "java"
    PYTHON = "python"


EXTENSIONS: dict[str, Language] = {
    ".cpp": Language.CPP,
    ".cc": Language.CPP,
    ".cxx": Language.CPP,
    ".C": Language.CPP,
    ".c": Language.C,
    ".java": Language.JAVA,
    ".py": Language.PYTHON,
}


@dataclass(frozen=True)
class Solution:
    name: str
    rel_path: str
    path: Path
    expected: str
    language: Language | None
    sources: tuple[Path, ...]
    entry: str
    error: str | None


def sanitize_name(rel_path: str) -> str:
    return _UNSAFE.sub("_", rel_path)


def _language_of(path: Path) -> Language | None:
    return EXTENSIONS.get(path.suffix)


def _java_entry(sources: tuple[Path, ...]) -> tuple[str, str | None]:
    mains = [
        p for p in sources if JAVA_MAIN_RE.search(p.read_text(encoding="utf-8", errors="replace"))
    ]
    if not mains:
        return "", "java main 메서드를 가진 파일을 찾지 못했습니다"
    if len(mains) > 1:
        names = ", ".join(p.name for p in mains)
        return "", f"java main 메서드가 여러 파일에 있습니다: {names}"
    return mains[0].stem, None


def _python_entry(sources: tuple[Path, ...], root: Path) -> tuple[str, str | None]:
    if len(sources) == 1:
        return sources[0].name, None
    for p in sources:
        if p.name == "main.py":
            return p.relative_to(root).as_posix(), None
    return "", "python 소스가 여러 개면 main.py 가 있어야 합니다"


def _build_solution(
    unit: Path, expected: str, problem_dir: Path
) -> tuple[Solution | None, str | None]:
    """(solution, warning) 을 돌려준다. 건너뛸 대상이면 solution 이 None 이다."""
    solutions_root = problem_dir / "solutions"
    rel_path = unit.relative_to(solutions_root).as_posix()

    if unit.is_dir():
        sources = tuple(sorted(p for p in unit.rglob("*") if p.is_file() and _language_of(p)))
        source_root = unit
    else:
        if _language_of(unit) is None:
            return None, f"지원하지 않는 확장자입니다. 건너뜁니다: solutions/{rel_path}"
        sources = (unit,)
        source_root = unit.parent

    if not sources:
        return None, f"소스 파일이 없습니다. 건너뜁니다: solutions/{rel_path}"

    languages = {_language_of(p) for p in sources}
    name = sanitize_name(rel_path)

    if len(languages) > 1:
        found = ", ".join(sorted(lang.value for lang in languages))
        return (
            Solution(
                name=name,
                rel_path=rel_path,
                path=unit,
                expected=expected,
                language=None,
                sources=sources,
                entry="",
                error=f"한 solution 에 두 언어가 섞였습니다: {found}",
            ),
            None,
        )

    language = next(iter(languages))
    entry, error = "", None
    if language is Language.JAVA:
        entry, error = _java_entry(sources)
    elif language is Language.PYTHON:
        entry, error = _python_entry(sources, source_root)

    return (
        Solution(
            name=name,
            rel_path=rel_path,
            path=unit,
            expected=expected,
            language=language,
            sources=sources,
            entry=entry,
            error=error,
        ),
        None,
    )


def discover_solutions(
    problem_dir: Path, *, filter_glob: str = ""
) -> tuple[list[Solution], list[str]]:
    solutions_root = problem_dir / "solutions"
    warnings: list[str] = []
    if not solutions_root.is_dir():
        return [], [f"solutions/ 디렉토리가 없습니다: {solutions_root}"]

    found: list[Solution] = []
    for child in sorted(solutions_root.iterdir()):
        if not child.is_dir():
            warnings.append(f"solutions/ 바로 아래의 파일은 무시합니다: {child.name}")
            continue
        if child.name not in EXPECTED_VERDICTS:
            warnings.append(
                f"알 수 없는 verdict 디렉토리입니다. 건너뜁니다: solutions/{child.name}"
            )
            continue

        for unit in sorted(child.iterdir()):
            solution, warning = _build_solution(unit, child.name, problem_dir)
            if warning:
                warnings.append(warning)
            if solution is None:
                continue
            if filter_glob and not fnmatch(solution.rel_path, filter_glob):
                continue
            found.append(solution)

    return found, warnings
