import pytest

from icpc_verify.testdata import TestDataError, collect_testcases


def make_case(root, rel, ans=True):
    p = root / "data" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.with_suffix(".in").write_text("1\n", encoding="utf-8")
    if ans:
        p.with_suffix(".ans").write_text("1\n", encoding="utf-8")


def test_flat_layout(tmp_path):
    make_case(tmp_path, "02")
    make_case(tmp_path, "01")
    cases = collect_testcases(tmp_path)
    assert [c.id for c in cases] == ["01", "02"]
    assert [c.group for c in cases] == ["", ""]


def test_kattis_nested_layout(tmp_path):
    make_case(tmp_path, "sample/01")
    make_case(tmp_path, "secret/03")
    cases = collect_testcases(tmp_path)
    assert [c.id for c in cases] == ["sample/01", "secret/03"]
    assert [c.group for c in cases] == ["sample", "secret"]


def test_answer_must_be_in_same_directory(tmp_path):
    make_case(tmp_path, "secret/03", ans=False)
    (tmp_path / "data" / "03.ans").write_text("1\n", encoding="utf-8")
    with pytest.raises(TestDataError, match="secret/03"):
        collect_testcases(tmp_path)


def test_missing_data_dir(tmp_path):
    with pytest.raises(TestDataError, match="data"):
        collect_testcases(tmp_path)


def test_empty_data_dir(tmp_path):
    (tmp_path / "data").mkdir()
    with pytest.raises(TestDataError, match="testcase"):
        collect_testcases(tmp_path)
