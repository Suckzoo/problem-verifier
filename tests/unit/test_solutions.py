from icpc_verify.solutions import Language, discover_solutions, sanitize_name

JAVA_MAIN = "public class Main { public static void main(String[] args) {} }\n"


def write(root, rel, text="x"):
    p = root / "solutions" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_sanitize_name():
    assert sanitize_name("accepted/main.cpp") == "accepted_main.cpp"
    assert sanitize_name("wrong_answer/a b.py") == "wrong_answer_a_b.py"


def test_single_file_solutions(tmp_path):
    write(tmp_path, "accepted/main.cpp")
    write(tmp_path, "wrong_answer/greedy.c")
    sols, warnings = discover_solutions(tmp_path)
    assert warnings == []
    assert [(s.rel_path, s.expected, s.language) for s in sols] == [
        ("accepted/main.cpp", "accepted", Language.CPP),
        ("wrong_answer/greedy.c", "wrong_answer", Language.C),
    ]


def test_multi_file_directory_solution(tmp_path):
    write(tmp_path, "accepted/multi/a.cpp")
    write(tmp_path, "accepted/multi/b.cpp")
    sols, _ = discover_solutions(tmp_path)
    assert len(sols) == 1
    assert sols[0].rel_path == "accepted/multi"
    assert len(sols[0].sources) == 2


def test_java_entry_point(tmp_path):
    write(tmp_path, "accepted/Main.java", JAVA_MAIN)
    sols, _ = discover_solutions(tmp_path)
    assert sols[0].language is Language.JAVA
    assert sols[0].entry == "Main"
    assert sols[0].error is None


def test_java_without_main_is_an_error(tmp_path):
    write(tmp_path, "accepted/Helper.java", "public class Helper {}\n")
    sols, _ = discover_solutions(tmp_path)
    assert sols[0].error is not None
    assert "main" in sols[0].error


def test_python_single_file_entry(tmp_path):
    write(tmp_path, "accepted/sol.py", "print(1)\n")
    sols, _ = discover_solutions(tmp_path)
    assert sols[0].language is Language.PYTHON
    assert sols[0].entry == "sol.py"


def test_python_multi_file_needs_main_py(tmp_path):
    write(tmp_path, "accepted/pkg/a.py")
    write(tmp_path, "accepted/pkg/b.py")
    sols, _ = discover_solutions(tmp_path)
    assert sols[0].error is not None
    assert "main.py" in sols[0].error


def test_mixed_languages_is_an_error(tmp_path):
    write(tmp_path, "accepted/mix/a.cpp")
    write(tmp_path, "accepted/mix/b.py")
    sols, _ = discover_solutions(tmp_path)
    assert sols[0].error is not None
    assert "언어" in sols[0].error


def test_unknown_directory_warns_and_is_skipped(tmp_path):
    write(tmp_path, "maybe_accepted/x.cpp")
    sols, warnings = discover_solutions(tmp_path)
    assert sols == []
    assert any("maybe_accepted" in w for w in warnings)


def test_unsupported_extension_warns_and_is_skipped(tmp_path):
    write(tmp_path, "accepted/notes.txt")
    sols, warnings = discover_solutions(tmp_path)
    assert sols == []
    assert any("notes.txt" in w for w in warnings)


def test_filter_glob(tmp_path):
    write(tmp_path, "accepted/main.cpp")
    write(tmp_path, "wrong_answer/greedy.cpp")
    sols, _ = discover_solutions(tmp_path, filter_glob="accepted/**")
    assert [s.rel_path for s in sols] == ["accepted/main.cpp"]


def test_missing_solutions_dir_returns_empty(tmp_path):
    sols, warnings = discover_solutions(tmp_path)
    assert sols == []
    assert any("solutions" in w for w in warnings)
