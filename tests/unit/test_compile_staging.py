from icpc_verify.compile import _stage_sources
from icpc_verify.solutions import describe_unit


def test_directory_unit_stages_all_files(tmp_path):
    unit = tmp_path / "multi"
    unit.mkdir()
    (unit / "a.cpp").write_text("int main(){}", encoding="utf-8")
    (unit / "helper.h").write_text("// header", encoding="utf-8")
    solution, _ = describe_unit(unit, tmp_path, "accepted")

    work = tmp_path / "work"
    work.mkdir()
    staged = _stage_sources(solution, work)

    assert (work / "a.cpp").is_file()
    assert (work / "helper.h").is_file()  # 소스가 아니어도 복사된다
    assert staged == ["/work/a.cpp"]  # 컴파일 대상은 소스만


def test_single_file_unit_stages_only_that_file(tmp_path):
    src = tmp_path / "sol.cpp"
    src.write_text("int main(){}", encoding="utf-8")
    (tmp_path / "neighbor.txt").write_text("x", encoding="utf-8")
    solution, _ = describe_unit(src, tmp_path, "accepted")

    work = tmp_path / "work"
    work.mkdir()
    staged = _stage_sources(solution, work)

    assert (work / "sol.cpp").is_file()
    assert not (work / "neighbor.txt").exists()  # 이웃 파일은 안 따라온다
    assert staged == ["/work/sol.cpp"]


def test_mount_parameter_changes_container_paths(tmp_path):
    src = tmp_path / "check.py"
    src.write_text("print(42)", encoding="utf-8")
    solution, _ = describe_unit(src, tmp_path, "validator")

    work = tmp_path / "work"
    work.mkdir()
    staged = _stage_sources(solution, work, mount="/validator")
    assert staged == ["/validator/check.py"]
