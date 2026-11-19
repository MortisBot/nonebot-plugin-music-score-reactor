from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from nonebot_plugin_music_score_reactor import follow as follow_mod
from nonebot_plugin_music_score_reactor.follow import (
    FollowState,
    conditional_probability,
    follow_probability,
    parse_emoji_like,
)


def test_follow_probability_curve() -> None:
    assert follow_probability(0) == 0.0
    assert follow_probability(1) == pytest.approx(0.03)
    assert follow_probability(2) == pytest.approx(0.14)
    assert follow_probability(3) == pytest.approx(0.33)
    assert follow_probability(4) == pytest.approx(0.60)
    assert follow_probability(5) == pytest.approx(0.95)
    assert follow_probability(6) == 1.0
    assert follow_probability(99) == 1.0
    assert follow_probability(3, max_p=0.2) == pytest.approx(0.2)


def test_conditional_probability_reaches_cumulative_target() -> None:
    for n in range(1, 6):
        miss_all = math.prod(1.0 - conditional_probability(i) for i in range(1, n + 1))
        assert 1.0 - miss_all == pytest.approx(follow_probability(n), abs=1e-12)

    assert conditional_probability(0) == 0.0
    assert conditional_probability(6) == 1.0
    assert conditional_probability(7) == 0.0
    assert conditional_probability(4, max_p=0.5) > 0


def test_parse_emoji_like() -> None:
    event = SimpleNamespace(
        notice_type="group_msg_emoji_like",
        group_id=100001,
        user_id=100002,
        message_id=5,
        is_add=True,
        likes=[{"emoji_id": 297}, {"emoji_id": "297"}, {"emoji_id": "424"}],
    )
    assert parse_emoji_like(event) == {
        "group_id": 100001,
        "user_id": 100002,
        "message_id": 5,
        "is_add": True,
        "emojis": ["297", "424"],
    }

    assert parse_emoji_like(SimpleNamespace(notice_type="group_upload")) is None
    assert parse_emoji_like(SimpleNamespace(
        notice_type="group_msg_emoji_like", group_id=1, user_id=2, message_id=3, likes=[]
    )) is None
    assert parse_emoji_like(SimpleNamespace(
        notice_type="group_msg_emoji_like", group_id=1, user_id=2, message_id=3,
        likes=["297"],
    )) is None


def test_follow_state_dedup_and_history_max() -> None:
    state = FollowState(ttl=60, max_entries=10)

    first = state.add_user(100001, 5, "297", 100002)
    assert (first.n, first.increased, first.followed) == (1, True, False)

    duplicate = state.add_user(100001, 5, "297", 100002)
    assert (duplicate.n, duplicate.increased) == (1, False)

    second = state.add_user(100001, 5, "297", 100003)
    assert (second.n, second.increased) == (2, True)

    state.remove_user(100001, 5, "297", 100003)
    readded = state.add_user(100001, 5, "297", 100003)
    assert (readded.n, readded.increased) == (2, False)

    state.mark_followed(100001, 5, "297")
    assert state.add_user(100001, 5, "297", 100004).followed is True
    assert state.size() == 1


def test_follow_state_ttl(monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(follow_mod.time, "monotonic", lambda: now[0])
    state = FollowState(ttl=10, max_entries=10)

    assert state.add_user(1, 2, "297", 3).n == 1
    now[0] = 1011.0
    assert state.add_user(1, 2, "297", 3).n == 1
    assert state.size() == 1


def test_follow_state_eviction(monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(follow_mod.time, "monotonic", lambda: now[0])
    state = FollowState(ttl=0, max_entries=2)
    state.add_user(1, 1, "297", 1)
    state.add_user(1, 2, "297", 1)
    state.add_user(1, 3, "297", 1)
    assert state.size() == 2
