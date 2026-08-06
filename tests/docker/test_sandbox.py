from pathlib import Path

import pytest

from icpc_verify.sandbox import SandboxSpec, run_sandbox

pytestmark = pytest.mark.docker

IMAGE = (Path(__file__).resolve().parents[2] / "image" / "IMAGE_DIGEST").read_text().strip()


def spec(argv, **kwargs):
    defaults = dict(image=IMAGE, cpuset=0, memory_mib=512, binds=(), timeout=30.0)
    defaults.update(kwargs)
    return SandboxSpec(argv=tuple(argv), **defaults)


def test_runs_and_captures_stdout():
    r = run_sandbox(spec(["echo", "hello"]))
    assert r.exit_code == 0
    assert r.stdout.strip() == b"hello"
    assert not r.oom_killed


def test_nonzero_exit():
    r = run_sandbox(spec(["sh", "-c", "exit 7"]))
    assert r.exit_code == 7


def test_oom_is_detected():
    r = run_sandbox(
        spec(
            ["python3", "-c", "x = bytearray(400 * 1024 * 1024); print(len(x))"],
            memory_mib=64,
        )
    )
    assert r.oom_killed


def test_network_is_disabled():
    r = run_sandbox(
        spec(["python3", "-c", "import socket; socket.create_connection(('1.1.1.1', 80), 2)"])
    )
    assert r.exit_code != 0


def test_bind_mount_is_readable(tmp_path):
    # pytest's tmp_path defaults to 0700; --cap-drop ALL removes CAP_DAC_OVERRIDE, so the
    # containerized root can't bypass that. Open up traversal so the ro bind mount is
    # actually exercised instead of failing on host directory permissions.
    tmp_path.chmod(0o755)
    (tmp_path / "f.txt").write_text("bound\n", encoding="utf-8")
    r = run_sandbox(spec(["cat", "/mnt/f.txt"], binds=((tmp_path, "/mnt", "ro"),)))
    assert r.stdout.strip() == b"bound"


def test_bind_mount_ro_is_not_writable(tmp_path):
    tmp_path.chmod(0o755)
    r = run_sandbox(spec(["sh", "-c", "echo x > /mnt/new"], binds=((tmp_path, "/mnt", "ro"),)))
    assert r.exit_code != 0


def test_cpuset_is_applied():
    r = run_sandbox(spec(["cat", "/sys/fs/cgroup/cpuset.cpus.effective"], cpuset=0))
    assert r.stdout.strip() == b"0"


def test_timeout(tmp_path):
    r = run_sandbox(spec(["sleep", "30"], timeout=2.0))
    assert r.timed_out
