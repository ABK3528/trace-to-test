from core.compile.anchors import ANCHOR_PRIORITY, ElementSnapshot, candidates


def snap(**over) -> ElementSnapshot:
    base = dict(
        tag="button", role="button", name="新建", text="新建", testid="",
        attrs={}, path="body > div > button:nth-of-type(1)", rect={"x": 0, "y": 0, "w": 1, "h": 1},
    )
    base.update(over)
    return ElementSnapshot(**base)


def test_priority_order_is_the_declared_one():
    assert ANCHOR_PRIORITY == ("testid", "role", "text", "path", "xy")


def test_testid_wins_when_present():
    got = candidates(snap(testid="create-btn"))
    assert got[0].by == "testid"
    assert got[0].value == "create-btn"
    assert got[0].fallback is False


def test_role_anchor_carries_role_and_name():
    got = candidates(snap())
    top = got[0]
    assert top.by == "role" and top.role == "button" and top.name == "新建"


def test_text_anchor_is_marked_copy_sensitive():
    got = candidates(snap(role="", name="", testid=""))
    top = got[0]
    assert top.by == "text" and top.value == "新建"
    assert top.copy_sensitive is True


def test_role_anchor_is_marked_copy_sensitive():
    assert candidates(snap())[0].copy_sensitive is True


def test_testid_anchor_is_not_copy_sensitive():
    assert candidates(snap(testid="create-btn"))[0].copy_sensitive is False


def test_path_is_offered_when_no_semantic_hook_exists():
    got = [a for a in candidates(snap(role="", name="", testid="")) if a.by == "path"]
    assert got and got[0].copy_sensitive is False


def test_always_ends_with_an_xy_fallback():
    got = candidates(snap())
    assert got[-1].by == "xy"
    assert got[-1].fallback is True


def test_blank_hooks_are_not_emitted_as_candidates():
    got = candidates(snap(role="", name="", testid="", text=""))
    assert all(a.value or a.by in ("xy", "path") for a in got)
    assert not any(a.by in ("testid", "text") for a in got)


def test_long_text_is_truncated_to_keep_anchors_readable():
    got = candidates(snap(role="", name="", testid="", text="x" * 200))
    assert len(got[0].value) <= 80
