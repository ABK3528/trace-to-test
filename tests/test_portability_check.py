import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "portability_check.sh"


def run_check() -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, capture_output=True, text=True)


def test_passes_on_clean_tree():
    assert run_check().returncode == 0


def test_fails_when_a_business_word_is_injected():
    planted = ROOT / "core" / "_planted_business_word.py"
    planted.write_text("SERVICE = 'modelgo'\n", encoding="utf-8")
    try:
        result = run_check()
        assert result.returncode == 1
        assert "portability check FAILED" in result.stderr
        assert "_planted_business_word.py" in result.stderr
    finally:
        planted.unlink()


def test_whitelisted_placeholder_is_allowed():
    planted = ROOT / "core" / "_planted_placeholder.py"
    planted.write_text("TARGET = '<target>'\n", encoding="utf-8")
    try:
        assert run_check().returncode == 0
    finally:
        planted.unlink()
