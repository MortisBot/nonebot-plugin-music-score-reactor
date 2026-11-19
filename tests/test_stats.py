from __future__ import annotations

import json
from pathlib import Path

import pytest
from nonebot_plugin_music_score_reactor import reaction_stats
from nonebot_plugin_music_score_reactor.reaction_stats import (
    DEFAULT_HALF_LIFE_DAYS,
    MAX_POWER,
    MIN_POWER,
    ReactionStats,
    clamp_half_life,
    clamp_power,
    emoji_weight,
)

DAY = 86400.0


def test_clamps() -> None:
    assert clamp_power(0) == MIN_POWER
    assert clamp_power(100) == MAX_POWER
    assert clamp_power("x") == 1.2
    assert clamp_half_life(-1) == 0.0
    assert clamp_half_life("x") == DEFAULT_HALF_LIFE_DAYS


def test_emoji_weight_matches_formula() -> None:
    now = 1_700_000_000.0
    fresh = emoji_weight(1, now, power=1.2, half_life_days=14, now=now)
    assert fresh == pytest.approx(2**1.2)

    old = emoji_weight(1, now - 14 * DAY, power=1.2, half_life_days=14, now=now)
    assert old == pytest.approx(fresh * 0.5)

    no_decay = emoji_weight(1, now - 999 * DAY, power=1.2, half_life_days=0, now=now)
    assert no_decay == pytest.approx(fresh)

    missing_timestamp = emoji_weight(1, None, power=1.2, half_life_days=14, now=now)
    assert missing_timestamp == pytest.approx(fresh)

    assert emoji_weight(0, now, now=now) == pytest.approx(2**1.2)


def test_record_retract_and_ready(tmp_path: Path) -> None:
    stats = ReactionStats(
        tmp_path / "stats.json",
        min_samples=1,
        exclude_ids=["999"],
        save_debounce=0,
    )
    assert stats.record(100001, "297") is True
    assert stats.record(100001, "297") is True
    assert stats.record(100001, "424") is True
    assert stats.record(100001, "999") is False
    assert stats.record(None, "297") is False

    assert stats.size(100001) == 2
    assert stats.ready(100001) is True
    assert stats.ready(100002) is False

    assert stats.retract(100001, "297") is True
    assert stats.retract(100001, "297") is True
    assert stats.retract(100001, "297") is False

    picked = stats.pick(100001, fallback=("1",))
    assert picked == "424"
    assert stats.pick(100002, fallback=("8", "9")) in {"8", "9"}
    assert stats.pick(100002) == ""


def test_cold_start_falls_back_to_fixed_list(tmp_path: Path) -> None:
    stats = ReactionStats(tmp_path / "stats.json", min_samples=3)
    stats.record(100001, "297")
    stats.record(100001, "424")
    assert stats.ready(100001) is False
    assert stats.pick(100001, fallback=("7",)) == "7"


async def test_save_and_reload(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "stats.json"
    stats = ReactionStats(path, min_samples=1, save_debounce=0)
    stats.record(100001, "297")
    stats.record(100001, "424")

    assert await stats.save() is True
    payload = json.loads(path.read_text("utf-8"))
    assert payload["version"] == 1
    assert payload["groups"]["100001"]["297"]["count"] == 1
    assert not list(path.parent.glob("*.tmp"))

    loaded = ReactionStats(path, min_samples=1)
    assert loaded.size(100001) == 2

    assert await stats.save() is False


async def test_disabled_stats_never_writes(tmp_path: Path) -> None:
    path = tmp_path / "stats.json"
    stats = ReactionStats(path, enabled=False, min_samples=1)

    assert stats.record(100001, "297") is False
    assert await stats.save(force=True) is False
    assert not path.exists()


def test_corrupt_file_is_quarantined(tmp_path: Path) -> None:
    path = tmp_path / "stats.json"
    path.write_text("{ not-json", encoding="utf-8")

    stats = ReactionStats(path, min_samples=1)

    assert stats.groups == {}
    assert not path.exists()
    assert list(tmp_path.glob("stats.json.corrupt-*"))


def test_pick_uses_learned_weights(tmp_path: Path, monkeypatch) -> None:
    stats = ReactionStats(tmp_path / "stats.json", min_samples=1)
    stats.record(100001, "a")
    stats.record(100001, "b")

    captured: dict = {}

    def fake_choices(population, weights, k):
        captured["population"] = list(population)
        captured["weights"] = list(weights)
        return [population[0]]

    monkeypatch.setattr(reaction_stats.random, "choices", fake_choices)
    assert stats.pick(100001) == "a"
    assert sorted(captured["population"]) == ["a", "b"]
    assert all(weight > 0 for weight in captured["weights"])
