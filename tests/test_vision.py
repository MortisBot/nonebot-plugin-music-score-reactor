from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest
from nonebot_plugin_music_score_reactor.config import VisionConfig
from nonebot_plugin_music_score_reactor.vision import (
    ImageRef,
    OpenAICompatibleVisionClassifier,
    parse_verdict,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-body"


def _config(*, supports_base64: bool = True) -> VisionConfig:
    return VisionConfig(
        api_key="test",
        base_url="https://vision.example.invalid/v1/chat/completions",
        model="vision-model",
        timeout=2.0,
        supports_base64=supports_base64,
        max_image_bytes=1024 * 1024,
        http_proxy="",
    )


def _success(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": text}}]},
    )


async def test_classify_url_success() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "url": str(request.url),
                "auth": request.headers.get("authorization"),
                "payload": json.loads(request.content),
            }
        )
        return _success("是")

    classifier = OpenAICompatibleVisionClassifier(
        _config(), transport=httpx.MockTransport(handler)
    )
    try:
        verdict = await classifier.classify(
            ImageRef(url="https://images.example.invalid/a.png", group_id=100001)
        )
    finally:
        await classifier.aclose()

    assert verdict.matched is True
    assert verdict.source == "url"
    assert verdict.raw_text == "是"
    assert verdict.error == ""
    assert seen[0]["method"] == "POST"
    assert seen[0]["auth"] == "Bearer test"
    assert seen[0]["payload"]["model"] == "vision-model"
    assert seen[0]["payload"]["messages"][0]["content"][0]["image_url"]["url"].startswith(
        "https://images.example.invalid/"
    )
    assert "thinking" not in seen[0]["payload"]


async def test_classify_non_score_image() -> None:
    classifier = OpenAICompatibleVisionClassifier(
        _config(), transport=httpx.MockTransport(lambda request: _success("否"))
    )
    try:
        verdict = await classifier.classify(ImageRef(url="https://images.example.invalid/a.png"))
    finally:
        await classifier.aclose()

    assert verdict.matched is False
    assert verdict.error == ""
    assert verdict.ambiguous is False


async def test_classify_ambiguous_output() -> None:
    classifier = OpenAICompatibleVisionClassifier(
        _config(), transport=httpx.MockTransport(lambda request: _success("maybe"))
    )
    try:
        verdict = await classifier.classify_bytes(PNG)
    finally:
        await classifier.aclose()

    assert verdict.matched is False
    assert verdict.ambiguous is True
    assert verdict.error == ""


@pytest.mark.parametrize("status", [500, 502])
async def test_classify_http_failure(status: int) -> None:
    classifier = OpenAICompatibleVisionClassifier(
        _config(supports_base64=False),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="upstream failed")
        ),
    )
    try:
        verdict = await classifier.classify(ImageRef(url="https://images.example.invalid/a.png"))
    finally:
        await classifier.aclose()

    assert verdict.matched is False
    assert verdict.http_status == status
    assert f"HTTP {status}" in verdict.error


async def test_auth_failure_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="unauthorized")

    classifier = OpenAICompatibleVisionClassifier(
        _config(), transport=httpx.MockTransport(handler)
    )
    try:
        verdict = await classifier.classify(ImageRef(url="https://images.example.invalid/a.png"))
    finally:
        await classifier.aclose()

    assert verdict.http_status == 401
    assert calls["n"] == 1


async def test_timeout_returns_error_without_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    classifier = OpenAICompatibleVisionClassifier(
        _config(), transport=httpx.MockTransport(handler)
    )
    try:
        verdict = await classifier.classify(
            ImageRef(url="https://images.example.invalid/a.png")
        )
    finally:
        await classifier.aclose()

    assert verdict.matched is False
    assert "Timeout" in verdict.error or "timeout" in verdict.error


async def test_base64_fallback_after_url_failure() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            calls.append("GET")
            return httpx.Response(
                200, content=PNG, headers={"content-type": "image/png"}
            )
        payload = json.loads(request.content)
        token = payload["messages"][0]["content"][0]["image_url"]["url"]
        calls.append(token)
        if token.startswith("https://"):
            return httpx.Response(500, text="cannot fetch url")
        return _success("是")

    classifier = OpenAICompatibleVisionClassifier(
        _config(), transport=httpx.MockTransport(handler)
    )
    try:
        verdict = await classifier.classify(
            ImageRef(url="https://images.example.invalid/a.png")
        )
    finally:
        await classifier.aclose()

    assert calls[0].startswith("https://")
    assert calls[1] == "GET"
    assert calls[2].startswith("data:image/png;base64,")
    assert verdict.matched is True
    assert verdict.source == "base64"


async def test_base64_disabled_and_size_limit() -> None:
    classifier = OpenAICompatibleVisionClassifier(
        _config(supports_base64=False),
        transport=httpx.MockTransport(lambda request: _success("是")),
    )
    small = OpenAICompatibleVisionClassifier(
        replace(_config(), max_image_bytes=2),
        transport=httpx.MockTransport(lambda request: _success("是")),
    )
    try:
        assert "does not support base64" in (await classifier.classify_bytes(PNG)).error
        verdict = await small.classify_bytes(PNG)
    finally:
        await classifier.aclose()
        await small.aclose()

    assert "too large" in verdict.error


async def test_local_url_rejected_without_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not request private url")

    classifier = OpenAICompatibleVisionClassifier(
        _config(), transport=httpx.MockTransport(handler)
    )
    try:
        verdict = await classifier.classify(ImageRef(url="http://127.0.0.1/a.png"))
    finally:
        await classifier.aclose()

    assert verdict.matched is False
    assert "not a public" in verdict.error


def test_parse_verdict() -> None:
    assert parse_verdict("是") is True
    assert parse_verdict("是。") is True
    assert parse_verdict("否") is False
    assert parse_verdict("不是音游成绩图") is False
    assert parse_verdict("YES") is True
    assert parse_verdict("no") is False
    assert parse_verdict("") is None
    assert parse_verdict("不确定") is None
