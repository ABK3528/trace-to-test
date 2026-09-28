from pathlib import Path

import pytest

from adapters.instance.demo import DemoTarget, demo_oracle_from_spec


def test_demo_target_declares_loopback_only():
    target = DemoTarget()
    assert target.base_url.startswith("http://127.0.0.1")
    assert target.allow_hosts == ()


def test_demo_target_keeps_credentials_out_of_the_target_itself():
    # 凭据只以"环境变量名"的形式声明，值不落在代码里
    assert set(DemoTarget().credentials) == {"DEMO_USERNAME", "DEMO_PASSWORD"}


def test_demo_oracle_reads_expectations_from_the_spec_document(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("## items\n\n- 三条记录的文本依次为 `Alpha`、`Beta`、`Gamma`。\n", encoding="utf-8")
    oracle = demo_oracle_from_spec(spec)
    assert oracle.source_tag.startswith("spec:")
    assert "spec.md" in oracle.source_tag
    body = oracle.expectation("items#2-列表页")
    assert "Alpha" in body and "Gamma" in body


def test_demo_oracle_refuses_a_key_it_cannot_source(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("## items\n\n- 无\n", encoding="utf-8")
    oracle = demo_oracle_from_spec(spec)
    with pytest.raises(KeyError, match="not in the spec document"):
        oracle.expectation("something/not/documented")


def test_the_demo_target_build_id_is_callable():
    target = DemoTarget()
    assert callable(target.build_id)  # 可调用
