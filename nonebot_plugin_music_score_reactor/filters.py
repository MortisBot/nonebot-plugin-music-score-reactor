"""本地廉价过滤、结果缓存、并发合并与限流。

只依赖标准库，不 import nonebot / vision，方便单独自检。
所有图片相关的判断都只使用 OneBot 图片消息段的 data 字段，
不做任何本地图像解码或识别。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any
from urllib.parse import parse_qs, urlsplit

logger = logging.getLogger(__name__)


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def image_skip_reason(data: dict[str, Any], cfg: Any) -> str:
    """返回应跳过该图片的原因；返回空字符串表示可以继续识别。"""
    sub_type = str(data.get("sub_type", "0") or "0").strip()
    if sub_type not in {"", "0"}:
        return f"sub_type={sub_type}"

    summary = str(data.get("summary", "") or "")
    if "动画表情" in summary:
        return "animated sticker"

    url = str(data.get("url", "") or "").strip()
    if not url:
        return "empty url"

    file_name = str(data.get("file", "") or "")
    if cfg.skip_gif:
        # NapCat 的 file 通常是图片 md5（无扩展名），URL 也常无扩展名，
        # 这里只是廉价的尽力而为判断；动画表情主要靠 sub_type 过滤。
        probe = file_name or urlsplit(url).path
        if probe.lower().endswith(".gif"):
            return "gif image"

    size = _to_int(data.get("file_size"), 0)
    if 0 < size < cfg.min_file_bytes:
        return f"too small ({size} bytes)"

    return ""


def image_key(data: dict[str, Any]) -> str:
    """图片的稳定缓存键：优先文件名（通常为图片 md5），否则用 URL 里的文件标识。"""
    file_name = str(data.get("file", "") or "").strip()
    if file_name:
        return file_name
    url = str(data.get("url", "") or "")
    if not url:
        return ""
    try:
        query = parse_qs(urlsplit(url).query)
    except ValueError:
        return ""
    for name in ("fileid", "md5", "file"):
        values = query.get(name)
        if values and values[0]:
            return f"{name}:{values[0]}"
    return ""


class VerdictCache:
    """识别结果缓存（TTL + LRU），用于避免重复图片反复调用云端模型。"""

    def __init__(self, ttl: float, maxsize: int) -> None:
        self._ttl = max(1.0, float(ttl))
        self._max = max(1, int(maxsize))
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        if not key:
            return None
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, verdict = item
        if expires_at <= time.monotonic():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return verdict

    def put(self, key: str, verdict: Any) -> None:
        if not key:
            return
        self._data[key] = (time.monotonic() + self._ttl, verdict)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)


class InFlightCoalescer:
    """同一张图片在途时合并为一次调用（factory 约定不抛异常）。"""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Task[Any]] = {}

    def _discard(self, key: str, task: asyncio.Task[Any]) -> None:
        if self._pending.get(key) is task:
            self._pending.pop(key, None)

    async def run(
        self, key: str, factory: Callable[[], Awaitable[Any]]
    ) -> Any:
        if not key:
            return await factory()
        task = self._pending.get(key)
        if task is None:
            task = asyncio.ensure_future(factory())
            self._pending[key] = task
            task.add_done_callback(partial(self._discard, key))
        return await asyncio.shield(task)


class RateLimiter:
    """全局滑动窗口限流；limit <= 0 表示不限制。"""

    def __init__(self, per_minute: int) -> None:
        self._limit = int(per_minute)
        self._events: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> bool:
        if self._limit <= 0:
            return True
        async with self._lock:
            now = time.monotonic()
            while self._events and now - self._events[0] >= 60.0:
                self._events.popleft()
            if len(self._events) >= self._limit:
                return False
            self._events.append(now)
            return True


class ReactionDeduper:
    """同一条消息 + 同一个表情只贴一次。"""

    def __init__(self, ttl: float, maxsize: int = 1024) -> None:
        self._ttl = max(1.0, float(ttl))
        self._max = max(1, int(maxsize))
        self._seen: OrderedDict[tuple[int, str], float] = OrderedDict()

    def mark_if_new(self, message_id: int, emoji_id: int | str) -> bool:
        key = (int(message_id), str(emoji_id))
        now = time.monotonic()
        expires_at = self._seen.get(key)
        if expires_at is not None and expires_at > now:
            return False
        self._seen[key] = now + self._ttl
        self._seen.move_to_end(key)
        while len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return True
