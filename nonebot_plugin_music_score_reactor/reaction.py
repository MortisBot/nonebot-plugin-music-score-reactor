"""对原消息添加 QQ 表情 Reaction（NapCat set_msg_emoji_like）。

使用显式 call_api 而不是 bot.set_msg_emoji_like，避免 NoneBot
Bot.__getattr__ 把拼写错误静默变成一个不存在的 API 调用。
"""

from __future__ import annotations

from typing import Any


async def add_reaction(
    bot: Any, message_id: int, emoji_id: int | str
) -> tuple[bool, str]:
    """给消息贴表情。

    Returns:
        (是否成功, 错误描述)。任何失败都不会抛出异常。
    """
    try:
        result = await bot.call_api(
            "set_msg_emoji_like",
            message_id=int(message_id),
            emoji_id=str(emoji_id),
            set=True,
        )
    except Exception as exc:
        return False, f"{exc.__class__.__name__}: {exc}"

    if isinstance(result, dict) and result.get("result") is False:
        return False, f"napcat returned {result!r}"

    return True, ""
