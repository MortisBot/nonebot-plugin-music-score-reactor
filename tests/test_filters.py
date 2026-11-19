from __future__ import annotations

import asyncio
from types import SimpleNamespace

from nonebot_plugin_music_score_reactor.filters import (
    InFlightCoalescer,
    RateLimiter,
    ReactionDeduper,
    VerdictCache,
    image_key,
    image_skip_reason,
)


def _cfg(**kwargs):
    values = {"skip_gif": True, "min_file_bytes": 8192}
    values.update(kwargs)
    return SimpleNamespace(**values)


def _image(**kwargs):
    values = {
        "sub_type": "0",
        "summary": "",
        "url": "https://images.example.invalid/a.jpg",
        "file": "abc123",
        "file_size": "10000",
    }
    values.update(kwargs)
    return values


def test_valid_image_passes() -> None:
    assert image_skip_reason(_image(), _cfg()) == ""


def test_animated_sticker_and_sub_type_filtered() -> None:
    assert "sub_type" in image_skip_reason(_image(sub_type="1"), _cfg())
    assert image_skip_reason(_image(summary="[动画表情]"), _cfg()) == "animated sticker"


def test_empty_url_and_gif_filtered() -> None:
    assert image_skip_reason(_image(url=""), _cfg()) == "empty url"
    assert image_skip_reason(_image(file="a.gif"), _cfg()) == "gif image"
    assert image_skip_reason(_image(file="", url="https://x/a.gif?x=1"), _cfg()) == "gif image"
    assert image_skip_reason(_image(file="a.gif"), _cfg(skip_gif=False)) == ""


def test_small_file_filtered() -> None:
    assert "too small" in image_skip_reason(_image(file_size="100"), _cfg())
    assert image_skip_reason(_image(file_size="0"), _cfg()) == ""


def test_image_key_prefers_file_then_url_query() -> None:
    assert image_key(_image()) == "abc123"
    assert image_key(_image(file="", url="https://x/a?md5=deadbeef")) == "md5:deadbeef"
    assert image_key(_image(file="", url="https://x/a?fileid=fid")) == "fileid:fid"
    assert image_key(_image(file="", url="")) == ""
    assert image_key(_image(file="", url="https://x/a?other=1")) == ""


def test_verdict_cache_lru() -> None:
    cache = VerdictCache(ttl=60, maxsize=2)
    cache.put("a", "A")
    cache.put("b", "B")
    assert cache.get("a") == "A"
    cache.put("c", "C")
    assert cache.get("b") is None
    assert cache.get("a") == "A"
    assert cache.get("") is None


def test_reaction_deduper() -> None:
    deduper = ReactionDeduper(ttl=60)
    assert deduper.mark_if_new(1, 297) is True
    assert deduper.mark_if_new(1, 297) is False
    assert deduper.mark_if_new(1, 424) is True
    assert deduper.mark_if_new(2, 297) is True


async def test_rate_limiter() -> None:
    limiter = RateLimiter(2)
    assert await limiter.try_acquire() is True
    assert await limiter.try_acquire() is True
    assert await limiter.try_acquire() is False
    unlimited = RateLimiter(0)
    assert await unlimited.try_acquire() is True


async def test_inflight_coalescer_shares_result() -> None:
    coalescer = InFlightCoalescer()
    calls = {"n": 0}

    async def factory() -> str:
        calls["n"] += 1
        await asyncio.sleep(0.01)
        return "value"

    first, second = await asyncio.gather(
        coalescer.run("same", factory),
        coalescer.run("same", factory),
    )

    assert first == second == "value"
    assert calls["n"] == 1
    assert await coalescer.run("", factory) == "value"
    assert calls["n"] == 2
