import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ci_bootstrap.sh"


def run(venv: Path, req: Path, check: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    return subprocess.run([str(SCRIPT), str(venv), str(req)], env=env, capture_output=True, text=True, check=check)


def site_packages(venv: Path) -> Path:
    return next((venv / "lib").glob("python*/site-packages"))


def test_unchanged_requirements_reuse_the_environment(tmp_path: Path) -> None:
    venv, req = tmp_path / "venv", tmp_path / "req.txt"
    req.write_text("# none\n")
    run(venv, req)
    marker = site_packages(venv) / "kept_marker.py"
    marker.write_text("")
    run(venv, req)
    assert marker.exists()


def test_changed_requirements_recreate_the_environment(tmp_path: Path) -> None:
    venv, req = tmp_path / "venv", tmp_path / "req.txt"
    req.write_text("# none\n")
    run(venv, req)
    stale = site_packages(venv) / "stale_dependency.py"
    stale.write_text("")
    req.write_text("# none, changed\n")
    run(venv, req)
    assert not stale.exists()


def test_missing_stamp_recreates_the_environment(tmp_path: Path) -> None:
    venv, req = tmp_path / "venv", tmp_path / "req.txt"
    req.write_text("# none\n")
    run(venv, req)
    stale = site_packages(venv) / "stale_dependency.py"
    stale.write_text("")
    (venv / ".requirements-sha256").unlink()
    run(venv, req)
    assert not stale.exists()


def test_failed_install_leaves_no_stamp_and_is_retried(tmp_path: Path) -> None:
    venv, req = tmp_path / "venv", tmp_path / "req.txt"
    req.write_text("# none\n")
    run(venv, req)
    req.write_text("definitely-not-a-real-package-xyz==1.0\n")
    assert run(venv, req, check=False).returncode != 0
    assert not (venv / ".requirements-sha256").exists()
    req.write_text("# none again\n")
    run(venv, req)
    assert (venv / ".requirements-sha256").exists()
