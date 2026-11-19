"""OpenAI 兼容视觉模型二分类客户端（与 NoneBot 完全解耦）。

只依赖 httpx 与标准库，不 import nonebot。
任务是判断一张图片是否为「音游成绩结算/分享图」，只输出二分类结果。

任何兼容 ``/chat/completions`` 的服务（自建网关、OpenAI、智谱等）都可以使用；
更换实现时新增一个满足 ``VisionClassifier`` 协议的类，并在 ``build_classifier()``
中分支即可，本模块其余部分无需改动。
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlsplit

import httpx

if TYPE_CHECKING:  # 仅类型检查时引入
    from .config import VisionConfig

logger = logging.getLogger(__name__)

PROMPT = """你是一个图片分类器。请判断这张图片【是否】是音乐游戏（例如 maimai、CHUNITHM、Arcaea、Phigros、osu!、Lanota、Deemo、Project SEKAI、中二节奏等）一局结束后的「成绩结算 / 成绩分享」页面截图。

判定为「是」的典型特征（出现一种或多种即可）：
- 曲名 + 难度（如 MASTER / EXPERT / ADVANCED / 等級）或难度等级数字
- 分数或达成率（如 100.5%、1,000,000、Score、Acc）
- 评级（S / SS / SSS / AAA / S+ 等）
- 判定统计（PERFECT / GREAT / GOOD / MISS / CRITICAL PERFECT / PURE 等）
- FC / AP / Full Combo / All Perfect / 全连 / 理论值 等标识
- 结算画面特有的 Ranking、新纪录、Rate、单曲成绩条、段位/评级结算

判定为「否」的典型情况：
- 普通电子游戏截图（对战、背包、抽卡、任务界面等）
- 音游的选曲界面、游戏主页、设置、商店、好友、活动界面
- 聊天截图、聊天记录、网页列表、二维码
- 照片、风景、人物、食物
- 表情包、梗图、动画表情

严格要求：只输出一个汉字，「是」或「否」，不要输出任何其它文字、标点或解释。"""


@dataclass(frozen=True, slots=True)
class ImageRef:
    """待识别图片的最小描述（不持有图片数据本身）。"""

    url: str = ""
    file_name: str = ""
    file_size: int = 0
    group_id: int = 0


@dataclass(frozen=True, slots=True)
class Verdict:
    """一次二分类结果。error 非空表示调用失败，不代表「非音游」。"""

    matched: bool
    raw_text: str = ""
    source: str = ""  # "url" | "base64"
    error: str = ""
    ambiguous: bool = False  # 模型输出无法判定
    http_status: int = 0  # 非 200 时的 HTTP 状态码，0 表示无


class VisionClassifier(Protocol):
    """视觉分类器协议；实现方需保证 classify 不抛异常。"""

    async def classify(self, image: ImageRef) -> Verdict: ...

    async def classify_bytes(self, data: bytes) -> Verdict: ...

    async def aclose(self) -> None: ...


def parse_verdict(text: str) -> bool | None:
    """把模型输出解析成 True/False；无法判定时返回 None。"""
    raw = (text or "").strip()
    if not raw:
        return None

    first_line = raw.splitlines()[0].strip()
    compact = "".join(ch for ch in first_line if not ch.isspace())
    compact = compact.strip("。.!！,，:：、\"'`*#-")
    if not compact:
        return None

    # 明确表示「无法判断」时不能当成否定
    if compact.startswith(("不确定", "无法判断", "无法确定", "不能确定")):
        return None

    # 否定优先，避免「不是音游成绩图」被其中的「是」误判
    if compact.startswith(("不", "否", "非")):
        return False
    if compact[0] == "是":
        return True

    lowered = compact.lower()
    if "否" in compact or "不是" in compact or lowered.startswith("no"):
        return False
    if "是" in compact or lowered.startswith("yes"):
        return True
    return None


def _extract_content(data: Any) -> str | None:
    """从 OpenAI 兼容响应中取出文本内容。"""
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        if parts:
            return "".join(parts)
    return None


def _is_remote_url(url: str) -> bool:
    if not url.lower().startswith(("http://", "https://")):
        return False
    host = (urlsplit(url).hostname or "").strip().lower()
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        return False
    return True


def _sniff_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


class OpenAICompatibleVisionClassifier:
    """OpenAI 兼容视觉模型客户端。

    先尝试把图片 URL 直接交给云端模型；失败且模型支持 base64 时，
    再由本地下载图片并转成 data URL 重试一次。任何异常都转成 Verdict.error。
    """

    def __init__(
        self,
        cfg: VisionConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._cfg = cfg
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(cfg.timeout, connect=min(10.0, cfg.timeout)),
            proxy=cfg.http_proxy or None,
            transport=transport,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except Exception:  # pragma: no cover - 关闭失败无需处理
            pass

    # ── 对外接口 ────────────────────────────────────────────────
    async def classify(self, image: ImageRef) -> Verdict:
        url = (image.url or "").strip()
        if not _is_remote_url(url):
            return Verdict(
                matched=False,
                error=f"image url is not a public http(s) url: {url[:80]!r}",
            )

        verdict = await self._request(url, source="url")
        if not verdict.error:
            return verdict

        # 鉴权/限流类错误与图片 URL 无关，重试 base64 没有意义
        if verdict.http_status in (401, 403, 429):
            return verdict

        if not self._cfg.supports_base64:
            return verdict

        logger.info("[ScoreReactor] url mode failed (%s), retry with base64", verdict.error)
        data = await self._download(url)
        if data is None:
            return Verdict(
                matched=False,
                source="base64",
                error=f"{verdict.error}; base64 fallback download failed",
            )
        retry = await self.classify_bytes(data)
        if not retry.error:
            return retry
        return Verdict(
            matched=False,
            source="base64",
            error=f"{verdict.error}; base64 retry failed: {retry.error}",
        )

    async def classify_bytes(self, data: bytes) -> Verdict:
        """直接对图片字节做分类（本地文件/兜底路径使用）。"""
        if not self._cfg.supports_base64:
            return Verdict(matched=False, error="model does not support base64 input")
        if not data:
            return Verdict(matched=False, error="empty image data")
        if len(data) > self._cfg.max_image_bytes:
            return Verdict(
                matched=False,
                error=(
                    f"image too large for base64: {len(data)} bytes "
                    f"(limit {self._cfg.max_image_bytes})"
                ),
            )
        try:
            token = base64.b64encode(data).decode("ascii")
        except Exception as exc:  # pragma: no cover - b64encode 不会失败
            return Verdict(matched=False, error=f"base64 encode failed: {exc}")
        return await self._request(
            f"data:{_sniff_mime(data)};base64,{token}", source="base64"
        )

    # ── 内部实现 ────────────────────────────────────────────────
    def _build_payload(self, image_token: str) -> dict[str, Any]:
        return {
            "model": self._cfg.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_token}},
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
            "stream": False,
            "temperature": 0.1,
        }

    async def _request(self, image_token: str, *, source: str) -> Verdict:
        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = await self._client.post(
                self._cfg.base_url,
                headers=headers,
                json=self._build_payload(image_token),
            )
        except Exception as exc:
            return Verdict(
                matched=False, source=source, error=f"{exc.__class__.__name__}: {exc}"
            )

        if response.status_code != 200:
            return Verdict(
                matched=False,
                source=source,
                error=f"HTTP {response.status_code}: {response.text[:200]}",
                http_status=response.status_code,
            )

        try:
            data = response.json()
        except Exception as exc:
            return Verdict(
                matched=False, source=source, error=f"invalid json response: {exc}"
            )

        text = _extract_content(data)
        if text is None:
            return Verdict(
                matched=False,
                source=source,
                error=f"unexpected response: {str(data)[:200]}",
            )

        parsed = parse_verdict(text)
        if parsed is None:
            return Verdict(
                matched=False, raw_text=text, source=source, ambiguous=True
            )
        return Verdict(matched=parsed, raw_text=text, source=source)

    async def _download(self, url: str) -> bytes | None:
        limit = self._cfg.max_image_bytes
        try:
            async with self._client.stream("GET", url) as response:
                if response.status_code != 200:
                    logger.warning(
                        "[ScoreReactor] download image failed: HTTP %s",
                        response.status_code,
                    )
                    return None
                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > limit:
                        logger.info(
                            "[ScoreReactor] image exceeds %s bytes, skip base64 fallback",
                            limit,
                        )
                        return None
                return bytes(buffer)
        except Exception as exc:
            logger.warning(
                "[ScoreReactor] download image error: %s: %s",
                exc.__class__.__name__,
                exc,
            )
            return None


def build_classifier(
    cfg: VisionConfig, *, transport: httpx.AsyncBaseTransport | None = None
) -> VisionClassifier:
    """构造视觉分类器。未来支持更多协议时在此分支。"""
    return OpenAICompatibleVisionClassifier(cfg, transport=transport)


__all__ = [
    "ImageRef",
    "OpenAICompatibleVisionClassifier",
    "Verdict",
    "VisionClassifier",
    "build_classifier",
    "parse_verdict",
]
