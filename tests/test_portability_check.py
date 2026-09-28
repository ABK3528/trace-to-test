import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "portability_check.sh"


def run_check() -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, capture_output=True, text=True)


def _fake_repo(tmp_path: Path, *, words: str, dirs: list[str]) -> Path:
    """在临时目录里搭一个最小"仓"，用来测脚本自身的配置错误分支。"""
    (tmp_path / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, tmp_path / "scripts" / "portability_check.sh")
    (tmp_path / "scripts" / "business_words.txt").write_text(words, encoding="utf-8")
    (tmp_path / "scripts" / "portability_whitelist.txt").write_text(
        "# path-regex\tterm-regex\treason\n", encoding="utf-8")
    for d in dirs:
        (tmp_path / d).mkdir()
    return tmp_path


def _run_in(repo: Path, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [shutil.which("bash"), str(repo / "scripts" / "portability_check.sh")],
        cwd=repo, capture_output=True, text=True, env=env,
    )


# —— 主路径 ——

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


# —— 🔴 白名单不许退化成"整行豁免" ——

def test_a_line_carrying_both_a_placeholder_and_a_business_word_is_still_a_hit(tmp_path):
    """整行豁免的经典漏法：占位符把同行的业务词一起带过去。"""
    repo = _fake_repo(tmp_path, words="modelgo\n", dirs=["core"])
    planted = repo / "core" / "_planted_mixed.py"
    planted.write_text("TARGET = '<target>'  # never say modelgo here\n", encoding="utf-8")
    (repo / "scripts" / "portability_whitelist.txt").write_text(
        "core/_planted_mixed\\.py\t<target>\tplaceholder occurrence is allowed\n",
        encoding="utf-8",
    )
    result = _run_in(repo)
    assert result.returncode == 1
    assert "modelgo" in result.stderr


def test_a_whitelisted_file_and_term_pair_is_exempt(tmp_path):
    repo = _fake_repo(tmp_path, words="modelgo\n", dirs=["core"])
    (repo / "core" / "allowed.py").write_text("# modelgo, discussed here on purpose\n", encoding="utf-8")
    (repo / "scripts" / "portability_whitelist.txt").write_text(
        "core/allowed\\.py\tmodelgo\tthis file discusses the neutral rename\n", encoding="utf-8")
    assert _run_in(repo).returncode == 0


def test_the_whitelist_does_not_exempt_the_same_term_in_a_different_file(tmp_path):
    repo = _fake_repo(tmp_path, words="modelgo\n", dirs=["core"])
    (repo / "core" / "allowed.py").write_text("# modelgo\n", encoding="utf-8")
    (repo / "core" / "other.py").write_text("# modelgo\n", encoding="utf-8")
    (repo / "scripts" / "portability_whitelist.txt").write_text(
        "core/allowed\\.py\tmodelgo\texempt only this file\n", encoding="utf-8")
    result = _run_in(repo)
    assert result.returncode == 1
    assert "other.py" in result.stderr


# —— 🔴 三条 fail-open 路径 ——

def test_no_scan_directory_at_all_is_a_configuration_error(tmp_path):
    repo = _fake_repo(tmp_path, words="modelgo\n", dirs=[])
    result = _run_in(repo)
    assert result.returncode == 2
    assert "wrong tree" in result.stderr


def test_an_empty_word_list_is_a_configuration_error(tmp_path):
    repo = _fake_repo(tmp_path, words="# nothing but comments\n", dirs=["core"])
    result = _run_in(repo)
    assert result.returncode == 2
    assert "vacuous" in result.stderr


def test_a_partial_set_of_scan_dirs_is_fine(tmp_path):
    """分阶段落地：只存在 core/ 是合法的，不该报错。"""
    repo = _fake_repo(tmp_path, words="modelgo\n", dirs=["core"])
    assert _run_in(repo).returncode == 0


def test_grep_error_is_a_configuration_error(tmp_path):
    repo = _fake_repo(tmp_path, words="modelgo\n", dirs=["core"])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in ["awk", "dirname", "mktemp", "cat"]:
        (bin_dir / command).symlink_to(shutil.which(command))
    fake_grep = bin_dir / "grep"
    fake_grep.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
    fake_grep.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(bin_dir)
    result = _run_in(repo, env=env)
    assert result.returncode == 2
    assert "grep failed with exit" in result.stderr
