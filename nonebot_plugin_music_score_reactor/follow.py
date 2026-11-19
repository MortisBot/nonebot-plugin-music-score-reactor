"""表情回应跟随：按 (群, 消息, 表情) 统计去重人数，用条件概率决定是否跟随。

纯标准库实现，不 import nonebot，方便单独自检。

规则（用户定的）：
  * 按表情分别计数：某个表情在该消息上被 n 个不同的人贴过，才轮到它判定；
  * 目标累积概率 p(n) = min(MUSIC_SCORE_FOLLOW_MAX_P, (4n² − n) / 100)，
    即 n=1→3%、2→14%、3→33%、4→60%、5→95%、6→100%；
  * 每一步用**条件概率** q(n) = (p(n) − p(n−1)) / (1 − p(n−1)) 掷骰，
    于是「到 n 人为止至少跟过一次」的概率恰好等于 p(n)；
  * 跟随的表情与别人一致，不做随机选择；
  * 只在人数比历史最大值还大时掷骰（同一个人取消再重贴不会偷到额外概率）。
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

# 每消息计数的保留时长与条目上限（防无界增长）
DEFAULT_STATE_TTL = 21600.0
DEFAULT_STATE_MAX = 5000

FOLLOW_NOTICE_TYPE = "group_msg_emoji_like"


def follow_probability(users: int, max_p: float = 1.0) -> float:
    """目标累积概率 p(n) = min(max_p, (4n² − n) / 100)。"""
    n = int(users)
    if n <= 0:
        return 0.0
    value = (4.0 * n * n - n) / 100.0
    try:
        cap = float(max_p)
    except (TypeError, ValueError):
        cap = 1.0
    if not math.isfinite(cap):
        cap = 1.0
    return max(0.0, min(cap, value))


def conditional_probability(users: int, max_p: float = 1.0) -> float:
    """这一步的条件概率 q(n)，使「到 n 人为止至少跟过一次」恰为 p(n)。

        q(n) = (p(n) − p(n−1)) / (1 − p(n−1))

    等价闭式（未设上限时，x = 1..5）：q(x) = (8x − 5) / (95 + 9x − 4x²)，
    x ≥ 6 取 1（闭式在 x=6 给出 43/5 = 8.6，超出概率范围必须截断；分母
    95 + 9x − 4x² 的根 ≈ 6.1266，x ≥ 7 时为负）。
    一旦 `max_p` 小于 1，p 会被压平、闭式不再成立，所以统一用通用式；
    闭式只在自检里做等价断言。
    """
    n = int(users)
    if n <= 0:
        return 0.0
    current = follow_probability(n, max_p)
    previous = follow_probability(n - 1, max_p)
    if previous >= 1.0:
        # 前面都没跟的话这次必跟；已经到顶再涨就不该再掷
        return 1.0 if current > previous else 0.0
    if current <= previous:
        return 0.0
    return (current - previous) / (1.0 - previous)


def parse_emoji_like(event: Any) -> dict[str, Any] | None:
    """从通用 NoticeEvent 安全解析表情回应通知；不可用则返回 None。

    NapCat 的 `group_msg_emoji_like` 没有专门的适配器模型，会落到 `NoticeEvent`，
    但 `Event.model_config = {'extra': 'allow'}`，字段可直接属性访问。
    """
    if str(getattr(event, "notice_type", "") or "") != FOLLOW_NOTICE_TYPE:
        return None
    try:
        group_id = int(event.group_id)
        user_id = int(event.user_id)
        message_id = int(event.message_id)
    except (TypeError, ValueError):
        return None

    emojis: list[str] = []
    likes = getattr(event, "likes", None)
    if isinstance(likes, Iterable):
        for like in likes:
            if not isinstance(like, Mapping):
                continue
            emoji_id = str(like.get("emoji_id") or "").strip()
            if emoji_id and emoji_id not in emojis:
                emojis.append(emoji_id)
    if not emojis:
        return None

    return {
        "group_id": group_id,
        "user_id": user_id,
        "message_id": message_id,
        "is_add": bool(getattr(event, "is_add", True)),
        "emojis": emojis,
    }


@dataclass(slots=True)
class Progress:
    """某个 (消息, 表情) 收到一条通知后的状态。"""

    n: int  # 当前去重人数
    increased: bool  # 是否超过该 (消息, 表情) 的历史最大人数
    followed: bool  # bot 是否已经跟过这个 (消息, 表情)


@dataclass(slots=True)
class _Entry:
    users: set[int] = field(default_factory=set)
    n_max: int = 0
    followed: bool = False


class FollowState:
    """(group_id, message_id) -> {emoji_id: _Entry}，带 TTL 与条目上限。

    只保留最近若干条消息的计数；过期/超限淘汰的只是「在途」消息的部分计数，
    最坏情况是该条消息少跟一次，不影响其它功能。
    """

    def __init__(
        self, ttl: float = DEFAULT_STATE_TTL, max_entries: int = DEFAULT_STATE_MAX
    ) -> None:
        self.ttl = max(0.0, float(ttl))
        self.max_entries = max(1, int(max_entries))
        self._data: OrderedDict[
            tuple[int, int], tuple[float, dict[str, _Entry]]
        ] = OrderedDict()

    def _bucket(
        self, key: tuple[int, int], now: float
    ) -> dict[str, _Entry] | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        expires_at, bucket = hit
        if self.ttl > 0 and expires_at <= now:
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return bucket

    def _store(
        self, key: tuple[int, int], bucket: dict[str, _Entry], now: float
    ) -> None:
        expires_at = now + self.ttl if self.ttl > 0 else float("inf")
        self._data[key] = (expires_at, bucket)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    @staticmethod
    def _key(group_id: Any, message_id: Any) -> tuple[int, int]:
        return (int(group_id), int(message_id))

    def add_user(
        self, group_id: Any, message_id: Any, emoji_id: Any, user_id: Any
    ) -> Progress:
        """记一次「某人在该消息上贴了某表情」，返回该表情的最新进度。"""
        now = time.monotonic()
        key = self._key(group_id, message_id)
        bucket = self._bucket(key, now)
        if bucket is None:
            bucket = {}
        name = str(emoji_id)
        entry = bucket.get(name)
        if entry is None:
            entry = _Entry()
            bucket[name] = entry
        entry.users.add(int(user_id))
        n = len(entry.users)
        increased = n > entry.n_max
        if increased:
            entry.n_max = n
        self._store(key, bucket, now)
        return Progress(n=n, increased=increased, followed=entry.followed)

    def remove_user(
        self, group_id: Any, message_id: Any, emoji_id: Any, user_id: Any
    ) -> None:
        """某人取消了该表情（is_add=false）。"""
        now = time.monotonic()
        key = self._key(group_id, message_id)
        bucket = self._bucket(key, now)
        if bucket is None:
            return
        entry = bucket.get(str(emoji_id))
        if entry is None:
            return
        entry.users.discard(int(user_id))
        self._store(key, bucket, now)

    def mark_followed(
        self, group_id: Any, message_id: Any, emoji_id: Any
    ) -> None:
        """标记 bot 已经跟过这个 (消息, 表情)。"""
        now = time.monotonic()
        key = self._key(group_id, message_id)
        bucket = self._bucket(key, now)
        if bucket is None:
            bucket = {}
        name = str(emoji_id)
        entry = bucket.get(name)
        if entry is None:
            entry = _Entry()
            bucket[name] = entry
        entry.followed = True
        self._store(key, bucket, now)

    def size(self) -> int:
        return len(self._data)


__all__ = [
    "DEFAULT_STATE_MAX",
    "DEFAULT_STATE_TTL",
    "FOLLOW_NOTICE_TYPE",
    "FollowState",
    "Progress",
    "conditional_probability",
    "follow_probability",
    "parse_emoji_like",
]
