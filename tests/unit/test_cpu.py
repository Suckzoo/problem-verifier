import pytest

from icpc_verify.cpu import CpuError, check_arch_and_flags, plan_cpu, read_topology

TWO_VCPU = {0: (0, 1), 1: (0, 1)}
FOUR_VCPU = {0: (0, 1), 1: (0, 1), 2: (2, 3), 3: (2, 3)}
NO_SMT_FOUR = {0: (0,), 1: (1,), 2: (2,), 3: (3,)}


def test_read_topology(tmp_path):
    for cpu, siblings in (("cpu0", "0-1"), ("cpu1", "0-1"), ("cpu2", "2,3"), ("cpu3", "2,3")):
        d = tmp_path / "cpu" / cpu / "topology"
        d.mkdir(parents=True)
        (d / "thread_siblings_list").write_text(siblings + "\n", encoding="utf-8")
    assert read_topology(tmp_path / "cpu") == FOUR_VCPU


def test_two_vcpu_pins_highest_and_does_not_offline():
    plan = plan_cpu(TWO_VCPU, requested=None, offline_sibling=True)
    assert plan.judge_cpu == 1
    assert plan.offline == ()
    assert plan.isolated is False
    assert any("best-effort" in w for w in plan.warnings)


def test_four_vcpu_uses_last_core_and_offlines_sibling():
    plan = plan_cpu(FOUR_VCPU, requested=None, offline_sibling=True)
    assert plan.judge_cpu == 2
    assert plan.offline == (3,)
    assert plan.isolated is True


def test_offline_sibling_disabled():
    plan = plan_cpu(FOUR_VCPU, requested=None, offline_sibling=False)
    assert plan.judge_cpu == 2
    assert plan.offline == ()
    assert plan.isolated is False


def test_no_smt_needs_no_offline():
    plan = plan_cpu(NO_SMT_FOUR, requested=None, offline_sibling=True)
    assert plan.judge_cpu == 3
    assert plan.offline == ()
    assert plan.isolated is True


def test_requested_cpu_wins():
    plan = plan_cpu(FOUR_VCPU, requested=1, offline_sibling=True)
    assert plan.judge_cpu == 1
    assert plan.offline == ()


def test_requested_cpu_out_of_range():
    with pytest.raises(CpuError):
        plan_cpu(FOUR_VCPU, requested=9, offline_sibling=True)


def test_empty_topology():
    with pytest.raises(CpuError):
        plan_cpu({}, requested=None, offline_sibling=True)


def test_arch_check_rejects_arm():
    with pytest.raises(CpuError, match="x86_64"):
        check_arch_and_flags("aarch64", {"neon"}, ["avx2"])


def test_flag_check_rejects_missing_avx2():
    with pytest.raises(CpuError, match="avx2"):
        check_arch_and_flags("x86_64", {"sse2"}, ["avx2"])


def test_arch_and_flags_pass():
    check_arch_and_flags("x86_64", {"sse2", "avx2", "avx512f"}, ["avx2"])
