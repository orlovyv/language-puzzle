from app.services.scoring import confidence_for, pos_to_relation, priority_for, rank_for


def test_rank_for_common_verb_is_index_based():
    assert rank_for("be") == 1
    assert rank_for("call") == 20


def test_rank_for_uncommon_word_uses_length_formula():
    assert rank_for("the") == 600 + len("the") * 137
    assert rank_for("a" * 100) == 9000  # capped


def test_confidence_for():
    assert confidence_for("known") == 0.95
    assert confidence_for("ignored") == 1
    assert confidence_for("anything-else") == 0.1


def test_priority_for_ignored_is_negative():
    assert priority_for(5, 100, "ignored", "cat") == -1


def test_priority_for_penalises_single_letter():
    assert priority_for(1, 600, "unknown", "x") < priority_for(1, 600, "unknown", "cat")


def test_pos_to_relation():
    assert pos_to_relation("verb") == "action"
    assert pos_to_relation("noun") == "object"
    assert pos_to_relation("adj") == "problem"
    assert pos_to_relation("interjection") == "object"
