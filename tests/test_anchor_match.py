from core.compile.anchors import DRIFT_THRESHOLD, normalize, similarity


def test_normalize_folds_whitespace_case_and_punctuation():
    assert normalize("登  录") == normalize("登录")
    assert normalize("Sign In") == normalize("sign in")
    assert normalize("登 录！") == normalize("登录")


def test_normalize_keeps_cjk_intact():
    assert normalize("新建") == "新建"


def test_identical_strings_are_maximally_similar():
    assert similarity("新建", "新建") == 1.0


def test_a_copy_edit_still_scores_above_threshold():
    # 「登 录」→「立即登录」：同一颗按钮，文案改了
    assert similarity("登 录", "立即登录") >= DRIFT_THRESHOLD


def test_unrelated_labels_score_below_threshold():
    assert similarity("新建", "删除") < DRIFT_THRESHOLD


def test_threshold_is_the_documented_value():
    assert DRIFT_THRESHOLD == 0.7
