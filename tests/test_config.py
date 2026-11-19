from __future__ import annotations

from nonebot_plugin_music_score_reactor.config import (
    load_config,
    parse_bool,
    parse_float,
    parse_id_set,
    parse_int,
    parse_token_list,
)

_ENV_KEYS = [
    "MUSIC_SCORE_ENABLED",
    "MUSIC_SCORE_GROUPS",
    "MUSIC_SCORE_IGNORE_USERS",
    "MUSIC_SCORE_VISION_BASE_URL",
    "VISION_API_KEY",
    "VISION_MODEL",
    "VISION_TIMEOUT",
    "VISION_SUPPORTS_BASE64",
    "MUSIC_SCORE_RANDOM_RATE",
    "MUSIC_SCORE_FOLLOW_MAX_P",
    "MUSIC_SCORE_STATS_POWER",
    "MUSIC_SCORE_STATS_HALF_LIFE",
    "MUSIC_SCORE_MAX_CONCURRENT",
    "MUSIC_SCORE_STATS_STORE_PATH",
]


def _clear(monkeypatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_safe_defaults(monkeypatch) -> None:
    _clear(monkeypatch)
    cfg = load_config()

    assert cfg.enabled is False
    assert cfg.groups == frozenset()
    assert cfg.vision.base_url == ""
    assert cfg.vision.api_key == ""
    assert cfg.vision.model == "gpt-4o-mini"
    assert cfg.vision.timeout == 30.0
    assert cfg.vision.supports_base64 is True
    assert cfg.vision.configured is False
    assert cfg.stats_store_path.endswith("reaction_stats.json")
    assert cfg.follow_enabled is True


def test_parses_vision_and_groups(monkeypatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("MUSIC_SCORE_ENABLED", "true")
    monkeypatch.setenv("MUSIC_SCORE_GROUPS", "100001, 100002;100003")
    monkeypatch.setenv("MUSIC_SCORE_IGNORE_USERS", "100004 100005")
    monkeypatch.setenv("MUSIC_SCORE_VISION_BASE_URL", "https://api.example.invalid/v1/chat/completions")
    monkeypatch.setenv("VISION_API_KEY", "test-key")
    monkeypatch.setenv("VISION_MODEL", "vision-model")
    monkeypatch.setenv("VISION_TIMEOUT", "2.5")
    monkeypatch.setenv("VISION_SUPPORTS_BASE64", "off")

    cfg = load_config()
    assert cfg.enabled is True
    assert cfg.groups == frozenset({100001, 100002, 100003})
    assert cfg.ignore_users == frozenset({100004, 100005})
    assert cfg.vision.configured is True
    assert cfg.vision.base_url.endswith("/chat/completions")
    assert cfg.vision.timeout == 2.5
    assert cfg.vision.supports_base64 is False


def test_clamps_numeric_bounds(monkeypatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("MUSIC_SCORE_RANDOM_RATE", "9")
    monkeypatch.setenv("MUSIC_SCORE_FOLLOW_MAX_P", "9")
    monkeypatch.setenv("MUSIC_SCORE_STATS_POWER", "99")
    monkeypatch.setenv("MUSIC_SCORE_STATS_HALF_LIFE", "-5")
    monkeypatch.setenv("MUSIC_SCORE_MAX_CONCURRENT", "0")
    monkeypatch.setenv("VISION_TIMEOUT", "0")

    cfg = load_config()
    assert cfg.random_rate == 1.0
    assert cfg.follow_max_p == 1.0
    assert cfg.stats_power == 5.0
    assert cfg.stats_half_life_days == 0.0
    assert cfg.max_concurrent == 1
    assert cfg.vision.timeout == 1.0


def test_helpers() -> None:
    assert parse_bool("YES") is True
    assert parse_bool("off") is False
    assert parse_bool("nonsense", default=True) is True
    assert parse_int("12") == 12
    assert parse_int("x", 7) == 7
    assert parse_float("1.5") == 1.5
    assert parse_float("x", 2.0) == 2.0
    assert parse_id_set("1, 2;3") == frozenset({1, 2, 3})
    assert parse_id_set("") == frozenset()
    assert parse_token_list("297, 10068;424") == ("297", "10068", "424")
