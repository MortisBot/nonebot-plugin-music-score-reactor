"""音游成绩图 Reaction 插件配置。

纯标准库实现，不依赖 NoneBot，方便单独复用与自检。
所有配置均通过环境变量读取；视觉服务与具体厂商解耦，使用 OpenAI 兼容接口。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# ── QQ 表情 ID（NapCat set_msg_emoji_like 使用）────────────────
# 系统表情（EmojiType=1）用数字 ID；emoji 表情（EmojiType=2）用其 Unicode 码点，
# NapCat 依据字符串长度自动判定类型（>3 位即 type 2）。
EMOJI_THANKS = 297  # /拜谢（系统表情）
EMOJI_RENEW_BADGE = 424  # /续标识（系统表情）
EMOJI_QUESTION_MARK = 10068  # ❔ 问号（emoji 表情，U+2754）

DEFAULT_MODEL = "gpt-4o-mini"

# 学习统计默认落盘路径（相对当前工作目录）
DEFAULT_STATS_STORE_PATH = "data/music_score_reactor/reaction_stats.json"
DEFAULT_STATS_POWER = 1.2
DEFAULT_STATS_HALF_LIFE_DAYS = 14.0
DEFAULT_STATS_MIN_SAMPLES = 5
DEFAULT_FOLLOW_MAX_P = 1.0
DEFAULT_FOLLOW_STATE_TTL = 21600.0
DEFAULT_FOLLOW_STATE_MAX = 5000

_TRUE_VALUES = {"1", "true", "yes", "y", "on", "enable", "enabled"}
_FALSE_VALUES = {"0", "false", "no", "n", "off", "disable", "disabled"}


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip()


def parse_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    return default


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_id_set(value: object) -> frozenset[int]:
    """解析用户 / 群集合，逗号/空格/分号分隔；空表示空集合。"""
    ids: set[int] = set()
    text = str(value or "")
    for token in text.replace(",", " ").replace(";", " ").split():
        number = parse_int(token, 0)
        if number > 0:
            ids.add(number)
    return frozenset(ids)


def parse_token_list(value: object) -> tuple[str, ...]:
    """解析表情 ID 列表（逗号/空格/分号分隔），保留原始字符串形态。"""
    text = str(value or "")
    return tuple(
        token
        for token in text.replace(",", " ").replace(";", " ").split()
        if token
    )


@dataclass(frozen=True, slots=True)
class VisionConfig:
    """OpenAI 兼容视觉接口配置，与具体服务商解耦。"""

    api_key: str
    base_url: str
    model: str
    timeout: float
    supports_base64: bool
    max_image_bytes: int
    http_proxy: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


@dataclass(frozen=True, slots=True)
class ReactorConfig:
    """插件整体配置。"""

    enabled: bool
    emoji_id: int
    groups: frozenset[int]
    ignore_users: frozenset[int]
    detect_robots: bool
    robot_cache_ttl: float
    random_enabled: bool
    random_rate: float
    random_emoji_ids: tuple[str, ...]
    stats_enabled: bool
    stats_exclude_emoji_ids: tuple[str, ...]
    stats_power: float
    stats_half_life_days: float
    stats_min_samples: int
    stats_store_path: str
    stats_save_debounce: float
    follow_enabled: bool
    follow_max_p: float
    follow_state_ttl: float
    follow_state_max: int
    min_file_bytes: int
    skip_gif: bool
    max_images_per_message: int
    max_concurrent: int
    rate_limit_per_minute: int
    verdict_ttl: float
    verdict_cache_max: int
    vision: VisionConfig


def load_config() -> ReactorConfig:
    vision = VisionConfig(
        api_key=_env("VISION_API_KEY"),
        base_url=_env("MUSIC_SCORE_VISION_BASE_URL"),
        model=_env("VISION_MODEL", DEFAULT_MODEL),
        timeout=max(1.0, parse_float(_env("VISION_TIMEOUT"), 30.0)),
        supports_base64=parse_bool(_env("VISION_SUPPORTS_BASE64"), True),
        max_image_bytes=max(
            1024, parse_int(_env("MUSIC_SCORE_VISION_MAX_IMAGE_KB"), 5120) * 1024
        ),
        http_proxy=_env("MUSIC_SCORE_HTTP_PROXY"),
    )

    return ReactorConfig(
        enabled=parse_bool(_env("MUSIC_SCORE_ENABLED"), False),
        emoji_id=parse_int(_env("MUSIC_SCORE_REACTION_EMOJI_ID"), EMOJI_THANKS),
        groups=parse_id_set(_env("MUSIC_SCORE_GROUPS")),
        ignore_users=parse_id_set(_env("MUSIC_SCORE_IGNORE_USERS")),
        detect_robots=parse_bool(_env("MUSIC_SCORE_DETECT_ROBOTS"), True),
        robot_cache_ttl=max(
            1.0, parse_float(_env("MUSIC_SCORE_ROBOT_CACHE_TTL"), 3600.0)
        ),
        random_enabled=parse_bool(_env("MUSIC_SCORE_RANDOM_ENABLED"), True),
        random_rate=min(
            1.0, max(0.0, parse_float(_env("MUSIC_SCORE_RANDOM_RATE"), 0.002))
        ),
        random_emoji_ids=parse_token_list(
            _env(
                "MUSIC_SCORE_RANDOM_EMOJI_IDS",
                f"{EMOJI_RENEW_BADGE},{EMOJI_QUESTION_MARK}",
            )
        ),
        stats_enabled=parse_bool(_env("MUSIC_SCORE_STATS_ENABLED"), True),
        stats_exclude_emoji_ids=parse_token_list(
            _env("MUSIC_SCORE_STATS_EXCLUDE_EMOJI_IDS", str(EMOJI_THANKS))
        ),
        stats_power=min(
            5.0, max(0.1, parse_float(_env("MUSIC_SCORE_STATS_POWER"), DEFAULT_STATS_POWER))
        ),
        stats_half_life_days=max(
            0.0,
            parse_float(
                _env("MUSIC_SCORE_STATS_HALF_LIFE"), DEFAULT_STATS_HALF_LIFE_DAYS
            ),
        ),
        stats_min_samples=max(
            1,
            parse_int(
                _env("MUSIC_SCORE_STATS_MIN_SAMPLES"), DEFAULT_STATS_MIN_SAMPLES
            ),
        ),
        stats_store_path=_env(
            "MUSIC_SCORE_STATS_STORE_PATH", DEFAULT_STATS_STORE_PATH
        ),
        stats_save_debounce=max(
            0.0, parse_float(_env("MUSIC_SCORE_STATS_SAVE_DEBOUNCE"), 10.0)
        ),
        follow_enabled=parse_bool(_env("MUSIC_SCORE_FOLLOW_ENABLED"), True),
        follow_max_p=min(
            1.0,
            max(0.0, parse_float(_env("MUSIC_SCORE_FOLLOW_MAX_P"), DEFAULT_FOLLOW_MAX_P)),
        ),
        follow_state_ttl=max(
            0.0,
            parse_float(
                _env("MUSIC_SCORE_FOLLOW_STATE_TTL"), DEFAULT_FOLLOW_STATE_TTL
            ),
        ),
        follow_state_max=max(
            1,
            parse_int(
                _env("MUSIC_SCORE_FOLLOW_STATE_MAX"), DEFAULT_FOLLOW_STATE_MAX
            ),
        ),
        min_file_bytes=max(0, parse_int(_env("MUSIC_SCORE_MIN_FILE_KB"), 8) * 1024),
        skip_gif=parse_bool(_env("MUSIC_SCORE_SKIP_GIF"), True),
        max_images_per_message=max(
            1, parse_int(_env("MUSIC_SCORE_MAX_IMAGES_PER_MESSAGE"), 1)
        ),
        max_concurrent=max(1, parse_int(_env("MUSIC_SCORE_MAX_CONCURRENT"), 2)),
        rate_limit_per_minute=max(
            0, parse_int(_env("MUSIC_SCORE_RATE_LIMIT_PER_MIN"), 10)
        ),
        verdict_ttl=max(
            1.0, parse_float(_env("MUSIC_SCORE_VERDICT_TTL"), 900.0)
        ),
        verdict_cache_max=max(
            1, parse_int(_env("MUSIC_SCORE_VERDICT_CACHE_MAX"), 512)
        ),
        vision=vision,
    )
