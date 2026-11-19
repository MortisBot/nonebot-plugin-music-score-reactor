"""NoneBot2 插件：音游成绩图 Reaction。

群聊收到图片后：
  1. 本地极廉价过滤（表情包 / 小图 / gif / 无链接）；
  2. 调用配置的 OpenAI 兼容视觉模型做二分类；
  3. 命中则用 NapCat set_msg_emoji_like 给【原消息】贴 Reaction，不发文字。

默认关闭；群列表为空时不生效。成绩图识别另需配置视觉 API。

第一阶段只判断「是不是音游成绩结算/分享图」，不解析具体成绩内容。
"""

from __future__ import annotations

import asyncio
import random

from nonebot import get_driver, logger, on_message, on_notice
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    MessageEvent,
    NoticeEvent,
)
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from .config import EMOJI_RENEW_BADGE, EMOJI_THANKS, load_config, parse_int
from .filters import (
    InFlightCoalescer,
    RateLimiter,
    ReactionDeduper,
    VerdictCache,
    image_key,
    image_skip_reason,
)
from .follow import (
    FollowState,
    conditional_probability,
    follow_probability,
    parse_emoji_like,
)
from .reaction import add_reaction
from .reaction_stats import ReactionStats
from .vision import ImageRef, Verdict, build_classifier

__plugin_meta__ = PluginMetadata(
    name="音游成绩图 Reaction",
    description=(
        "群聊收到图片时，用云端视觉模型判断是否为音乐游戏成绩结算图，"
        "命中则对原消息添加 QQ 表情 Reaction（不发送文字）。"
    ),
    usage="无需命令，自动生效。可通过环境变量配置模型、表情 ID、群白名单与限流。",
    type="application",
    supported_adapters={"~onebot.v11"},
)

# ── 配置与全局状态 ──────────────────────────────────────────────

CFG = load_config()
classifier = build_classifier(CFG.vision)
_cache = VerdictCache(CFG.verdict_ttl, CFG.verdict_cache_max)
_coalescer = InFlightCoalescer()
_limiter = RateLimiter(CFG.rate_limit_per_minute)
_deduper = ReactionDeduper(ttl=max(CFG.verdict_ttl, 300.0))
_semaphore = asyncio.Semaphore(CFG.max_concurrent)
# (group_id, user_id) -> 是否官方机器人，避免每条消息都查一次群成员信息
_robot_cache = VerdictCache(CFG.robot_cache_ttl, 1024)
# 群级表情回应频数统计（决定随机贴哪个表情）
stats = ReactionStats(
    CFG.stats_store_path,
    enabled=CFG.stats_enabled,
    power=CFG.stats_power,
    half_life_days=CFG.stats_half_life_days,
    exclude_ids=CFG.stats_exclude_emoji_ids,
    min_samples=CFG.stats_min_samples,
    save_debounce=CFG.stats_save_debounce,
)
# 每 (群, 消息, 表情) 的跟贴人数，用于「跟随贴表情」判定
follow_state = FollowState(CFG.follow_state_ttl, CFG.follow_state_max)
# 学习统计的周期落盘任务（on_startup 里创建）
_stats_saver: asyncio.Task[None] | None = None


def _api_key_configured() -> bool:
    """视觉服务是否配置完整（API key + base URL + model）。"""
    return CFG.vision.configured


async def _sender_is_robot(bot: Bot, event: GroupMessageEvent) -> bool:
    """查询群成员信息里的 is_robot（QQ 官方机器人标记）。

    查询失败时按「不是机器人」处理，绝不影响正常贴表情。
    """
    if not CFG.detect_robots:
        return False
    key = f"{event.group_id}:{event.user_id}"
    cached = _robot_cache.get(key)
    if cached is not None:
        return bool(cached)
    try:
        info = await bot.call_api(
            "get_group_member_info",
            group_id=event.group_id,
            user_id=event.user_id,
            no_cache=False,
        )
    except Exception as exc:
        logger.debug(
            "[ScoreReactor] get_group_member_info failed user={}: {}",
            event.user_id,
            exc,
        )
        return False
    is_robot = bool(info.get("is_robot")) if isinstance(info, dict) else False
    _robot_cache.put(key, is_robot)
    return is_robot


def _candidate(event: MessageEvent) -> bool:
    """廉价的前置条件，避免对每条消息都进入 handler。"""
    if not CFG.enabled or not _api_key_configured():
        return False
    if not isinstance(event, GroupMessageEvent):
        return False
    if event.group_id not in CFG.groups:
        return False
    if str(event.user_id) == str(event.self_id):
        return False
    if not any(segment.type == "image" for segment in event.message):
        return False
    # OneBot v11 不提供「发送者是机器人」标记，只能按配置的 QQ 号忽略
    if event.user_id in CFG.ignore_users:
        logger.info(
            "[ScoreReactor] sender in ignore list, skip image user={} group={}",
            event.user_id,
            event.group_id,
        )
        return False
    return True


matcher = on_message(rule=Rule(_candidate), priority=100, block=False)


def _random_candidate(event: MessageEvent) -> bool:
    """随机贴表情：任意文字消息，排除机器人与自己。

    含图片的消息交给成绩图逻辑处理，避免同一条消息被贴两个表情。
    """
    if not CFG.enabled or not CFG.random_enabled:
        return False
    if not CFG.random_emoji_ids or CFG.random_rate <= 0:
        return False
    if not isinstance(event, GroupMessageEvent):
        return False
    if event.group_id not in CFG.groups:
        return False
    if str(event.user_id) == str(event.self_id):
        return False
    if event.user_id in CFG.ignore_users:
        return False
    if any(segment.type == "image" for segment in event.message):
        return False
    return random.random() < CFG.random_rate


random_matcher = on_message(rule=Rule(_random_candidate), priority=110, block=False)


def _emoji_like_candidate(event: NoticeEvent) -> bool:
    """表情回应通知的前置条件。

    只要求「统计或跟随至少有一个开着」：只开统计时也要学习，
    只开跟随时也要用人数判定。取消（is_add=false）也要放进来，用于回退计数。
    """
    if not CFG.enabled:
        return False
    if not CFG.stats_enabled and not CFG.follow_enabled:
        return False
    if str(getattr(event, "notice_type", "") or "") != "group_msg_emoji_like":
        return False

    group_id = getattr(event, "group_id", None)
    user_id = getattr(event, "user_id", None)
    if group_id is None or user_id is None:
        return False
    if int(group_id) not in CFG.groups:
        return False
    if str(user_id) == str(event.self_id):
        return False  # bot 自己贴的表情会回灌成通知，必须排除
    if int(user_id) in CFG.ignore_users:
        return False
    return True


follow_matcher = on_notice(
    rule=Rule(_emoji_like_candidate), priority=100, block=False
)


async def _classify(image: ImageRef) -> Verdict:
    """调用视觉模型；即使实现方违约抛异常也在此兜底。"""
    try:
        return await classifier.classify(image)
    except Exception as exc:  # pragma: no cover - 防御性兜底
        logger.exception("[ScoreReactor] classifier raised")
        return Verdict(matched=False, error=f"{exc.__class__.__name__}: {exc}")


async def _react(bot: Bot, event: GroupMessageEvent, verdict: Verdict) -> None:
    if not _deduper.mark_if_new(event.message_id, CFG.emoji_id):
        return
    ok, error = await add_reaction(bot, event.message_id, CFG.emoji_id)
    if ok:
        logger.info(
            "[ScoreReactor] reacted group={} msg={} emoji={} source={}",
            event.group_id,
            event.message_id,
            CFG.emoji_id,
            verdict.source or "unknown",
        )
    else:
        logger.warning(
            "[ScoreReactor] reaction failed group={} msg={} emoji={}: {}",
            event.group_id,
            event.message_id,
            CFG.emoji_id,
            error,
        )


async def _handle_group_images(bot: Bot, event: GroupMessageEvent) -> None:
    if await _sender_is_robot(bot, event):
        logger.info(
            "[ScoreReactor] skip image from QQ robot user={} group={}",
            event.user_id,
            event.group_id,
        )
        return
    images = [
        segment for segment in event.message if segment.type == "image"
    ][: CFG.max_images_per_message]

    for segment in images:
        data = dict(segment.data)
        image_url = str(data.get("url", "") or "")
        reason = image_skip_reason(data, CFG)
        if reason:
            logger.info(
                "[ScoreReactor] skip image group={} msg={}: {}",
                event.group_id,
                event.message_id,
                reason,
            )
            continue

        key = image_key(data)
        cached = _cache.get(key)
        if cached is not None:
            logger.debug(
                "[ScoreReactor] verdict cache hit group={} key={}",
                event.group_id,
                key,
            )
            verdict = cached
        else:
            if not await _limiter.try_acquire():
                logger.info(
                    "[ScoreReactor] rate limit reached, skip group={} msg={}",
                    event.group_id,
                    event.message_id,
                )
                return
            image = ImageRef(
                url=str(data.get("url", "") or ""),
                file_name=str(data.get("file", "") or ""),
                file_size=parse_int(data.get("file_size"), 0),
                group_id=event.group_id,
            )
            async with _semaphore:
                verdict = await _coalescer.run(key, lambda img=image: _classify(img))
            if not verdict.error:
                # 只缓存成功结果；瞬时失败（429/网络错误）下次可重试
                _cache.put(key, verdict)

        if verdict.error:
            logger.warning(
                "[ScoreReactor] vision failed group={} msg={}: {} | url={}",
                event.group_id,
                event.message_id,
                verdict.error,
                image_url[:300],
            )
            continue
        if verdict.ambiguous:
            logger.info(
                "[ScoreReactor] ambiguous model output: {}", verdict.raw_text[:120]
            )
        if not verdict.matched:
            logger.info(
                "[ScoreReactor] not a score image group={} msg={} source={} raw={}",
                event.group_id,
                event.message_id,
                verdict.source,
                verdict.raw_text[:40],
            )
            continue

        await _react(bot, event, verdict)
        return


@matcher.handle()
async def handle_group_image(bot: Bot, event: GroupMessageEvent) -> None:
    try:
        await _handle_group_images(bot, event)
    except Exception:  # pragma: no cover - 绝不让异常影响其它插件
        logger.exception("[ScoreReactor] unexpected error")


@random_matcher.handle()
async def handle_random_reaction(bot: Bot, event: GroupMessageEvent) -> None:
    """按配置概率在随机文字消息上贴一个随机表情。"""
    try:
        if await _sender_is_robot(bot, event):
            logger.info(
                "[ScoreReactor] skip random reaction for QQ robot user={} group={}",
                event.user_id,
                event.group_id,
            )
            return
        # 按本群实测的表情频数加权挑选；学习池不足时回退固定列表
        emoji_id = stats.pick(event.group_id, CFG.random_emoji_ids)
        if not emoji_id:
            return
        if not _deduper.mark_if_new(event.message_id, emoji_id):
            return
        ok, error = await add_reaction(bot, event.message_id, emoji_id)
        if ok:
            logger.info(
                "[ScoreReactor] random reacted group={} msg={} emoji={}",
                event.group_id,
                event.message_id,
                emoji_id,
            )
        else:
            logger.warning(
                "[ScoreReactor] random reaction failed group={} msg={} emoji={}: {}",
                event.group_id,
                event.message_id,
                emoji_id,
                error,
            )
    except Exception:  # pragma: no cover - 绝不让异常影响其它插件
        logger.exception("[ScoreReactor] random reaction unexpected error")


@follow_matcher.handle()
async def handle_emoji_like(bot: Bot, event: NoticeEvent) -> None:
    """有人贴表情时：先学习频数，再按条件概率决定是否跟随贴同一个表情。"""
    try:
        parsed = parse_emoji_like(event)
        if parsed is None:
            return

        group_id = parsed["group_id"]
        message_id = parsed["message_id"]
        user_id = parsed["user_id"]

        for emoji_id in parsed["emojis"]:
            if not parsed["is_add"]:
                # 取消贴表情：回退跟随计数与学习统计，不参与判定
                follow_state.remove_user(group_id, message_id, emoji_id, user_id)
                if CFG.stats_enabled:
                    stats.retract(group_id, emoji_id)
                continue

            if CFG.stats_enabled:
                stats.record(group_id, emoji_id)

            if not CFG.follow_enabled:
                continue

            progress = follow_state.add_user(
                group_id, message_id, emoji_id, user_id
            )
            if progress.followed or not progress.increased:
                continue

            chance = conditional_probability(progress.n, CFG.follow_max_p)
            if chance <= 0 or random.random() >= chance:
                logger.info(
                    "[ScoreReactor] follow roll missed group={} msg={} emoji={} "
                    "n={} q={:.4f} p={:.4f}",
                    group_id,
                    message_id,
                    emoji_id,
                    progress.n,
                    chance,
                    follow_probability(progress.n, CFG.follow_max_p),
                )
                continue

            if not _deduper.mark_if_new(message_id, emoji_id):
                follow_state.mark_followed(group_id, message_id, emoji_id)
                continue
            follow_state.mark_followed(group_id, message_id, emoji_id)

            ok, error = await add_reaction(bot, message_id, emoji_id)
            if ok:
                logger.info(
                    "[ScoreReactor] followed group={} msg={} emoji={} n={} q={:.4f}",
                    group_id,
                    message_id,
                    emoji_id,
                    progress.n,
                    chance,
                )
            else:
                logger.warning(
                    "[ScoreReactor] follow failed group={} msg={} emoji={}: {}",
                    group_id,
                    message_id,
                    emoji_id,
                    error,
                )
    except Exception:  # pragma: no cover - 绝不让异常影响其它插件
        logger.exception("[ScoreReactor] follow unexpected error")


@get_driver().on_startup
async def _log_startup_config() -> None:
    logger.info(
        "[ScoreReactor] enabled={} model={} emoji_id={} groups={} ignore_users={} "
        "detect_robots={} rate={}/min concurrency={} ttl={}s api_key={} "
        "| random_enabled={} random_rate={} random_emoji_ids={}",
        CFG.enabled,
        CFG.vision.model,
        CFG.emoji_id,
        sorted(CFG.groups) if CFG.groups else "none",
        sorted(CFG.ignore_users) if CFG.ignore_users else "none",
        CFG.detect_robots,
        CFG.rate_limit_per_minute,
        CFG.max_concurrent,
        CFG.verdict_ttl,
        "configured" if _api_key_configured() else "MISSING",
        CFG.random_enabled,
        CFG.random_rate,
        list(CFG.random_emoji_ids),
    )
    logger.info(
        "[ScoreReactor] stats_enabled={} stats_groups={} stats_exclude={} "
        "stats_power={} stats_half_life={}d follow_enabled={} follow_max_p={}",
        CFG.stats_enabled,
        len(stats.groups),
        list(CFG.stats_exclude_emoji_ids) or "none",
        CFG.stats_power,
        CFG.stats_half_life_days,
        CFG.follow_enabled,
        CFG.follow_max_p,
    )
    if CFG.enabled and not _api_key_configured():
        logger.error(
            "[ScoreReactor] 未配置 VISION_API_KEY 或 MUSIC_SCORE_VISION_BASE_URL，"
            "插件不会调用视觉模型（表情 ID 可选：{}=/拜谢, {}=/续标识）。",
            EMOJI_THANKS,
            EMOJI_RENEW_BADGE,
        )


@get_driver().on_startup
async def _start_stats_saver() -> None:
    """周期性把学习统计落盘。

    `save()` 内部按 `stats_save_debounce` 合并、无改动时直接跳过，
    因此这里只需要一个较短的周期兜底，避免进程被外部重启时丢失最近统计。
    """
    global _stats_saver
    if not CFG.stats_enabled or _stats_saver is not None:
        return
    interval = max(5.0, min(30.0, CFG.stats_save_debounce or 10.0))

    async def _loop() -> None:
        while True:
            await asyncio.sleep(interval)
            await stats.save()

    _stats_saver = asyncio.create_task(_loop())


@get_driver().on_shutdown
async def _close_classifier() -> None:
    global _stats_saver
    if _stats_saver is not None:
        _stats_saver.cancel()
        try:
            await _stats_saver
        except asyncio.CancelledError:
            pass
        _stats_saver = None
    if CFG.stats_enabled:
        await stats.save(force=True)
    await classifier.aclose()
