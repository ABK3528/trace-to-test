"""回放前的假红自查（spec §4.2）。

三项自查里，这一层负责两项：
- 构建标识变没变（构建标识取自 workflow.source["build"]，由编译器或调用方盖章）
- 目标起没起、就绪没就绪

第三项「首轮失败次轮通过」由 run_with_retry 负责。

🔴 本模块产出的都**不是**三态结论：FAIL_ENV / STALE_TARGET 表示"现在还不能下判"。
调用方在 proceed=False 时不得把任何结果报成产品缺陷或脚本缺陷。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, replace

from .result import FAIL_ENV, STALE_TARGET, RunResult


@dataclass(frozen=True)
class PreflightVerdict:
    status: str = ""            # "" = 可以下结论
    reason: str = ""
    detail: str = ""

    @property
    def proceed(self) -> bool:
        return self.status == ""


def stamp_build(workflow, build: str):
    """把构建标识写进 workflow 的溯源信息，供下次回放判断是否换了构建。"""
    return replace(workflow, source={**workflow.source, "build": build})


def fetch_health(base_url: str, timeout: float = 5.0) -> dict | Exception:
    """打 /healthz。**任何失败都返回异常对象，不抛** —— 调用方要能把它当证据看。"""
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/healthz", timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return exc


def preflight(workflow, health: dict | Exception) -> PreflightVerdict:
    if isinstance(health, BaseException):
        return PreflightVerdict(FAIL_ENV, "environment", f"target unreachable: {health}")
    if not health.get("ready"):
        return PreflightVerdict(FAIL_ENV, "not_ready", "target is up but not ready")

    expected = workflow.source.get("build")
    if not expected:
        return PreflightVerdict("", "build_unknown", "workflow records no build id; staleness unchecked")
    actual = health.get("build")
    if actual != expected:
        return PreflightVerdict(
            STALE_TARGET, "build_drift",
            f"workflow was compiled against {expected!r} but the target serves {actual!r}",
        )
    return PreflightVerdict()


def run_with_retry(run_once, *, attempts: int = 2) -> tuple[RunResult, str]:
    """跑一次；失败且还有余量就再跑一次。

    第二次通过 = 首轮是冷加载造成的假红，标注 COLD_START_FLAKE（spec §4.2）。
    两次都失败 = 保留第二次的结果（它是稳定的那次）。
    """
    result = run_once()
    if result.ok or attempts <= 1:
        return result, ""
    second = run_once()
    if second.ok:
        return second, "COLD_START_FLAKE"
    return second, ""
