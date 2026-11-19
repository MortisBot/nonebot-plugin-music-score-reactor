"""群级表情回应频数统计：衰减加权挑选 + 原子 JSON 持久化。

纯标准库实现，不 import nonebot，方便单独自检。

数据来源是 NapCat 的 `group_msg_emoji_like` 通知（谁给哪条消息贴了什么表情）。
用途只有一个：让「随机贴表情」按本群实际用得多的表情来挑，而不是固定几个。
统计按群隔离，并带时间衰减，压住「以前很热、现在没人发」的表情。
"""

from __future__ import annotations

import json
import math
import os
import random
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# 默认落盘路径（相对当前工作目录；可用 MUSIC_SCORE_STATS_STORE_PATH 覆盖）
DEFAULT_STORE_PATH = "data/music_score_reactor/reaction_stats.json"

# 频数加权指数：权重 = (count + 1) ** power（对齐 mface_pool 的经验值）
DEFAULT_POWER = 1.2
MIN_POWER = 0.1
MAX_POWER = 5.0

# 时间衰减半衰期（天）：多久没被再次贴过，权重就减半；0 = 关闭衰减
DEFAULT_HALF_LIFE_DAYS = 14.0

# 采样下限：学习到的不同表情数少于该值就回退固定列表（冷启动保护）
DEFAULT_MIN_SAMPLES = 5

# 防止脏数据把幂运算撑爆
MAX_COUNT = 1_000_000
_SECONDS_PER_DAY = 86400.0


def _text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def clamp_power(value: Any, default: float = DEFAULT_POWER) -> float:
    try:
        power = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(power):
        return default
    return min(MAX_POWER, max(MIN_POWER, power))


def clamp_half_life(value: Any, default: float = DEFAULT_HALF_LIFE_DAYS) -> float:
    try:
        half_life = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(half_life):
        return default
    if half_life < 0:
        return 0.0
    return half_life


def emoji_weight(
    count: Any,
    last_seen: Any,
    power: float = DEFAULT_POWER,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    now: float | None = None,
) -> float:
    """挑选权重 = 频数权重 × 时间衰减因子。

        (count + 1) ** power  ×  0.5 ** (距今未出现天数 / 半衰期天数)

    用 `count + 1` 而不是 `count`：否则所有只贴过一次的表情权重都是 1，
    建池初期毫无区分度。时间戳缺失/异常时按「刚出现」处理，绝不放大权重。
    """
    seen = _int(count)
    if seen is None or seen < 1:
        seen = 1
    seen = min(seen, MAX_COUNT)
    weight = (seen + 1) ** clamp_power(power)

    half_life = clamp_half_life(half_life_days)
    if half_life > 0:
        if not isinstance(last_seen, (int, float)) or not math.isfinite(
            float(last_seen)
        ):
            return weight
        reference = time.time() if now is None else now
        age_days = max(0.0, (reference - float(last_seen)) / _SECONDS_PER_DAY)
        weight *= 0.5 ** (age_days / half_life)

    return weight


class ReactionStats:
    """内存统计 + JSON 持久化。

    改内存的操作都是同步的（无 await），因此不会被事件循环打断；
    只有写盘是异步的，并用一把 asyncio.Lock 串行化、以「临时文件 + os.replace」
    原子替换，避免并发写坏文件。
    """

    def __init__(
        self,
        store_path: str | Path = DEFAULT_STORE_PATH,
        *,
        enabled: bool = True,
        power: float = DEFAULT_POWER,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
        exclude_ids: Iterable[Any] = (),
        min_samples: int = DEFAULT_MIN_SAMPLES,
        save_debounce: float = 10.0,
    ) -> None:
        self.store_path = Path(store_path)
        self.enabled = bool(enabled)
        self.power = clamp_power(power)
        self.half_life_days = clamp_half_life(half_life_days)
        self.exclude_ids = {_text(item) for item in exclude_ids if _text(item)}
        self.min_samples = max(1, int(min_samples))
        self.save_debounce = max(0.0, float(save_debounce))
        # {group_id: {emoji_id: {"count": int, "last_seen": float}}}
        self.groups: dict[str, dict[str, dict[str, Any]]] = {}
        self._lock: Any = None
        self._dirty = False
        self._last_save = 0.0
        self.load()

    # ── 统计 ────────────────────────────────────────────────────

    def record(self, group_id: Any, emoji_id: Any) -> bool:
        """记录一次表情回应；被排除的表情直接丢弃。返回是否写入。"""
        if not self.enabled:
            return False
        gid = _text(group_id)
        eid = _text(emoji_id)
        if not gid or not eid or eid in self.exclude_ids:
            return False

        bucket = self.groups.setdefault(gid, {})
        item = bucket.get(eid)
        now = time.time()
        if item is None:
            bucket[eid] = {"count": 1, "last_seen": now}
        else:
            item["count"] = min(MAX_COUNT, (_int(item.get("count")) or 0) + 1)
            item["last_seen"] = now
        self._dirty = True
        return True

    def retract(self, group_id: Any, emoji_id: Any) -> bool:
        """撤回一次表情回应（is_add=false）：计数 -1，减到 0 就移除该表情。

        不计入 last_seen —— 撤回不算「最近用过」。
        """
        if not self.enabled:
            return False
        gid = _text(group_id)
        eid = _text(emoji_id)
        if not gid or not eid or eid in self.exclude_ids:
            return False

        bucket = self.groups.get(gid)
        if not bucket:
            return False
        item = bucket.get(eid)
        if item is None:
            return False

        count = (_int(item.get("count")) or 0) - 1
        if count <= 0:
            bucket.pop(eid, None)
            if not bucket:
                self.groups.pop(gid, None)
        else:
            item["count"] = count
        self._dirty = True
        return True

    def candidates(self, group_id: Any) -> list[tuple[str, Mapping[str, Any]]]:
        bucket = self.groups.get(_text(group_id)) or {}
        return [
            (eid, item)
            for eid, item in bucket.items()
            if _text(eid) and _text(eid) not in self.exclude_ids
        ]

    def size(self, group_id: Any) -> int:
        return len(self.candidates(group_id))

    def ready(self, group_id: Any) -> bool:
        """学习池是否够用；不够就回退固定列表（冷启动保护）。"""
        cands = self.candidates(group_id)
        if len(cands) < self.min_samples:
            return False
        total = sum((_int(item.get("count")) or 0) for _eid, item in cands)
        return total >= self.min_samples

    def pick(self, group_id: Any, fallback: Sequence[str] = ()) -> str:
        """按本群频数加权挑一个表情；学习池不足或异常时回退固定列表。"""
        if self.enabled and self.ready(group_id):
            cands = self.candidates(group_id)
            now = time.time()
            weights = [
                emoji_weight(
                    item.get("count"),
                    item.get("last_seen"),
                    self.power,
                    self.half_life_days,
                    now,
                )
                for _eid, item in cands
            ]
            total = sum(weights)
            if (
                all(math.isfinite(w) for w in weights)
                and math.isfinite(total)
                and total > 0
            ):
                return random.choices(
                    [eid for eid, _item in cands], weights=weights, k=1
                )[0]
        return self._pick_fallback(fallback)

    @staticmethod
    def _pick_fallback(fallback: Sequence[str]) -> str:
        pool = [str(item) for item in fallback if str(item)]
        return random.choice(pool) if pool else ""

    # ── 持久化 ──────────────────────────────────────────────────

    def _get_lock(self):
        if self._lock is None:
            import asyncio

            self._lock = asyncio.Lock()
        return self._lock

    def load(self) -> None:
        path = self.store_path
        self.groups = {}
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._quarantine(exc)
            return
        if not isinstance(data, Mapping):
            return

        raw_groups = data.get("groups")
        if not isinstance(raw_groups, Mapping):
            return

        for raw_gid, raw_bucket in raw_groups.items():
            gid = _text(raw_gid)
            if not gid or not isinstance(raw_bucket, Mapping):
                continue
            bucket: dict[str, dict[str, Any]] = {}
            for raw_eid, raw_item in raw_bucket.items():
                eid = _text(raw_eid)
                if not eid or eid in self.exclude_ids or not isinstance(raw_item, Mapping):
                    continue
                count = _int(raw_item.get("count"))
                if count is None or count < 1:
                    continue
                last_seen = raw_item.get("last_seen")
                if not isinstance(last_seen, (int, float)) or not math.isfinite(
                    float(last_seen)
                ):
                    last_seen = time.time()
                bucket[eid] = {
                    "count": min(count, MAX_COUNT),
                    "last_seen": float(last_seen),
                }
            if bucket:
                self.groups[gid] = bucket

    def _quarantine(self, exc: Exception) -> None:
        stamp = time.strftime("%Y%m%d%H%M%S")
        backup = self.store_path.with_name(f"{self.store_path.name}.corrupt-{stamp}")
        try:
            os.replace(self.store_path, backup)
            name = backup.name
        except OSError:
            name = "(备份失败)"
        from nonebot import logger

        logger.warning(
            "[ScoreReactor] 统计文件解析失败({}: {})，已处理为 {}，本次从空统计开始",
            exc.__class__.__name__,
            exc,
            name,
        )

    def _dump(self) -> str:
        return json.dumps(
            {
                "version": SCHEMA_VERSION,
                "groups": {
                    gid: {
                        eid: {
                            "count": int(item.get("count") or 1),
                            "last_seen": float(item.get("last_seen") or 0.0),
                        }
                        for eid, item in bucket.items()
                    }
                    for gid, bucket in sorted(self.groups.items())
                },
                "updated": time.time(),
            },
            ensure_ascii=False,
            indent=2,
        )

    async def save(self, force: bool = False) -> bool:
        """原子落盘；默认按 `save_debounce` 合并写，失败只告警。"""
        from nonebot import logger

        if not self.enabled:
            return False
        now = time.monotonic()
        if not force:
            if not self._dirty:
                return False
            if self.save_debounce > 0 and now - self._last_save < self.save_debounce:
                return False

        try:
            async with self._get_lock():
                self.store_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.store_path.with_name(f"{self.store_path.name}.tmp")
                with open(tmp, "w", encoding="utf-8") as handle:
                    handle.write(self._dump())
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, self.store_path)
                try:
                    dir_fd = os.open(str(self.store_path.parent), os.O_RDONLY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except OSError:
                    pass
            self._dirty = False
            self._last_save = now
            return True
        except Exception as exc:
            logger.warning(
                "[ScoreReactor] 写入统计文件失败: {}: {}",
                exc.__class__.__name__,
                exc,
            )
            return False


__all__ = [
    "DEFAULT_HALF_LIFE_DAYS",
    "DEFAULT_MIN_SAMPLES",
    "DEFAULT_POWER",
    "DEFAULT_STORE_PATH",
    "MAX_POWER",
    "MIN_POWER",
    "ReactionStats",
    "SCHEMA_VERSION",
    "clamp_half_life",
    "clamp_power",
    "emoji_weight",
]
