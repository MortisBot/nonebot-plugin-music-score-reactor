from __future__ import annotations

from nonebot_plugin_music_score_reactor.reaction import add_reaction


class FakeBot:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = {"result": True} if result is None else result
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def call_api(self, action: str, **kwargs):
        self.calls.append((action, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


async def test_add_reaction_success() -> None:
    bot = FakeBot()
    ok, error = await add_reaction(bot, 123, 297)

    assert ok is True
    assert error == ""
    assert bot.calls == [
        ("set_msg_emoji_like", {"message_id": 123, "emoji_id": "297", "set": True})
    ]


async def test_add_reaction_napcat_failure() -> None:
    ok, error = await add_reaction(FakeBot(result={"result": False}), 1, 297)
    assert ok is False
    assert "napcat returned" in error


async def test_add_reaction_exception_is_swallowed() -> None:
    ok, error = await add_reaction(FakeBot(error=RuntimeError("offline")), 1, 297)
    assert ok is False
    assert "RuntimeError: offline" in error
