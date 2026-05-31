from app.utils.parsing import clamp_float, parse_bool


def test_clamp_float_clamps_and_defaults():
    assert clamp_float("abc", 1.0, 0.5, 2.0) == 1.0
    assert clamp_float(5, 1.0, 0.5, 2.0) == 2.0
    assert clamp_float(0.1, 1.0, 0.5, 2.0) == 0.5
    assert clamp_float("1.5", 1.0, 0.5, 2.0) == 1.5


def test_parse_bool():
    assert parse_bool(None, True) is True
    assert parse_bool("no") is False
    assert parse_bool("yes") is True
    assert parse_bool(True) is True
    assert parse_bool("weird", default=False) is False
