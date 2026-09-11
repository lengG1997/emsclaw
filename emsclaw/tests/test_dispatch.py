from emsclaw_backend.deepagent.agents import normalize_mode, VALID_MODES


def test_known_modes_passthrough():
    assert normalize_mode("business") == "business"


def test_unknown_mode_falls_back_to_business():
    assert normalize_mode("deep") == "business"
    assert normalize_mode("research") == "business"
    assert normalize_mode("") == "business"
    assert normalize_mode(None) == "business"
    assert normalize_mode("nonsense") == "business"


def test_legacy_team_ops_falls_back_to_business():
    """已删除的 team_ops profile：存量 DB 会话的 mode 兜底走 business。"""
    assert normalize_mode("team_ops") == "business"


def test_valid_modes_set():
    assert VALID_MODES == {"business"}
