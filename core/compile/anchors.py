"""元素快照 → 候选锚点（纯函数），以及锚点失效时的近似匹配。

为什么 testid 排第一而不是文案（spec §4.2）：文案会随发布变化，
拿文案定位会把「按钮没了」和「按钮改叫别的了」混成一件事。
role/text 类锚点因此标 copy_sensitive，失效时走近似匹配 → 归 FAIL_PRODUCT。

本模块不碰浏览器：SNAP_JS 只是发给页面的字符串，取回来的 dict 由这里解释。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .schema import Anchor

ANCHOR_PRIORITY: tuple[str, ...] = ("testid", "role", "text", "path", "xy")
DRIFT_THRESHOLD = 0.7
_MAX_TEXT = 80
# 公共段短于这个长度就不算"文案改写"——否则短标签被包含即得满分
_MIN_PARTIAL_CHARS = 2

# 在页面里取「这个元素是什么」。返回结构必须与 ElementSnapshot 的字段对齐。
SNAP_JS = r"""
(() => {
  const el = window.__ttt_target;
  if (!el || el.nodeType !== 1) return null;
  const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
  const r = el.getBoundingClientRect();
  const path = (() => {
    const parts = [];
    let n = el;
    while (n && n.nodeType === 1 && parts.length < 8) {
      let sel = n.tagName.toLowerCase();
      if (n.parentElement) {
        const sibs = [...n.parentElement.children].filter(c => c.tagName === n.tagName);
        if (sibs.length > 1) sel += `:nth-of-type(${sibs.indexOf(n) + 1})`;
      }
      parts.unshift(sel);
      n = n.parentElement;
    }
    return parts.join(' > ');
  })();
  const aria = el.getAttribute('aria-label') || '';
  const labelled = el.getAttribute('aria-labelledby');
  const labelText = labelled
    ? (document.getElementById(labelled)?.textContent || '')
    : (el.labels && el.labels[0] ? el.labels[0].textContent : '');
  const name = (aria || labelText || t || el.getAttribute('placeholder')
                || el.getAttribute('title') || el.getAttribute('alt') || '').trim();
  // 隐式角色：真实页面里绝大多数元素没有显式 role 属性，
  // 只读 getAttribute('role') 会让 role 锚点几乎永远缺席。
  const IMPLICIT = {
    a: 'link', button: 'button', select: 'combobox', textarea: 'textbox',
    nav: 'navigation', main: 'main', header: 'banner', footer: 'contentinfo',
    h1: 'heading', h2: 'heading', h3: 'heading', ul: 'list', li: 'listitem',
    table: 'table', dialog: 'dialog', form: 'form',
  };
  const input = el.tagName.toLowerCase() === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : '';
  const INPUT_ROLE = { submit: 'button', button: 'button', checkbox: 'checkbox', radio: 'radio', search: 'searchbox' };
  const role = el.getAttribute('role') || IMPLICIT[el.tagName.toLowerCase()] || INPUT_ROLE[input] || '';
  return {
    tag: el.tagName.toLowerCase(),
    role: role,
    name: name.slice(0, 200),
    text: t.slice(0, 200),
    testid: el.getAttribute('data-testid') || el.getAttribute('data-test') || '',
    attrs: { id: el.id || '', name: el.getAttribute('name') || '', type: el.getAttribute('type') || '' },
    path,
    rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
  };
})()
"""


@dataclass(frozen=True)
class ElementSnapshot:
    tag: str
    role: str
    name: str
    text: str
    testid: str
    attrs: dict = field(default_factory=dict)
    path: str = ""
    rect: dict = field(default_factory=dict)

    @staticmethod
    def from_json(d: dict | None) -> "ElementSnapshot | None":
        if not isinstance(d, dict) or not d.get("tag"):
            return None
        return ElementSnapshot(
            tag=str(d.get("tag") or ""),
            role=str(d.get("role") or ""),
            name=str(d.get("name") or ""),
            text=str(d.get("text") or ""),
            testid=str(d.get("testid") or ""),
            attrs=dict(d.get("attrs") or {}),
            path=str(d.get("path") or ""),
            rect=dict(d.get("rect") or {}),
        )


def _clip(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:_MAX_TEXT]


def candidates(snap: ElementSnapshot) -> tuple[Anchor, ...]:
    """按 ANCHOR_PRIORITY 产出候选锚点，最后一颗永远是 xy 兜底。

    语义钩子为空的一律不产出——宁可少一个候选，也不要一个空值锚点
    在回放时"匹配到所有人"。
    """
    out: list[Anchor] = []

    if snap.testid:
        out.append(Anchor(by="testid", value=snap.testid))

    role_name = _clip(snap.name)
    if snap.role and role_name:
        out.append(Anchor(by="role", role=snap.role, name=role_name, copy_sensitive=True))

    text = _clip(snap.text)
    if text:
        out.append(Anchor(by="text", value=text, copy_sensitive=True))

    if snap.path:
        out.append(Anchor(by="path", value=snap.path))

    rect = snap.rect or {}
    out.append(Anchor(
        by="xy",
        value=f"{int(rect.get('x', 0))},{int(rect.get('y', 0))}",
        fallback=True,
    ))
    return tuple(out)


def normalize(text: str) -> str:
    """折叠空白、大小写与标点，用于近似匹配。CJK 原样保留。"""
    text = (text or "").strip().lower()
    text = re.sub(r"[\s　]+", "", text)
    return re.sub(r"[!-/:-@\[-`{-~！-／：-＠［-｀｛-～、-〜。，．・：；？！…—－（）「」『』【】]", "", text)


def similarity(a: str, b: str) -> float:
    """归一化之后的序列相似度 ∈ [0, 1]，对"前后加字的文案改写"也认。

    纯 SequenceMatcher.ratio() 会稀释短标签的前后扩展（"登录" vs "立即登录"
    只有 4/6 ≈ 0.667，低于 0.7 阈值），因此也考虑最长公共连续段相对短串的比例。
    为避免单字符偶然包含产生假匹配，partial 项要求最长公共段至少两个字符。
    """
    na, nb = normalize(a), normalize(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0

    matcher = SequenceMatcher(None, na, nb)
    ratio = matcher.ratio()
    longest = matcher.find_longest_match().size
    if longest < _MIN_PARTIAL_CHARS:
        return ratio
    return max(ratio, longest / min(len(na), len(nb)))
