# nonebot-plugin-music-score-reactor

_✨ 识别音游成绩图，并给原消息贴一个 QQ 表情 Reaction（不发送文字）。 ✨_

<a href="./LICENSE"><img src="https://img.shields.io/github/license/MortisBot/nonebot-plugin-music-score-reactor.svg" alt="license"></a>
<a href="https://pypi.python.org/pypi/nonebot-plugin-music-score-reactor"><img src="https://img.shields.io/pypi/v/nonebot-plugin-music-score-reactor.svg" alt="pypi"></a>
<img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="python">

## 安装

在 NoneBot2 项目根目录下执行：

```bash
nb plugin install nonebot-plugin-music-score-reactor
```

或手动安装：

```bash
pip install nonebot-plugin-music-score-reactor
```

并在 `pyproject.toml` 的 `[tool.nonebot]` 中追加：

```toml
plugins = ["nonebot_plugin_music_score_reactor"]
```

## 配置

在 `.env` 中配置（环境变量名即配置项大写）：

| 配置项 | 必填 | 默认值 | 说明 |
|:---:|:---:|:---:|:---|
| `MUSIC_SCORE_ENABLED` | 是 | `false` | 总开关 |
| `MUSIC_SCORE_GROUPS` | 是 | 空 | 生效群号，逗号分隔（空 = 不生效） |
| `MUSIC_SCORE_VISION_BASE_URL` | 是 | 空 | OpenAI 兼容视觉 API 地址 |
| `MUSIC_SCORE_VISION_API_KEY` | 是 | 空 | API Key |
| `MUSIC_SCORE_VISION_MODEL` | 否 | 无 | 模型名 |
| `MUSIC_SCORE_REACTION_EMOJI_ID` | 否 | `297` | 贴的表情 ID |
| `MUSIC_SCORE_RATE_LIMIT_PER_MIN` | 否 | `10` | 每分钟最多识别图片数 |

## 使用

无需命令，自动生效（默认关闭）：

收到群图片 → 调用配置的视觉模型判断是否音游成绩图 → 命中则给原消息贴表情。

开启前请确认图片会发送到你配置的第三方 API，并自行评估隐私与合规。

## 适配器

OneBot v11（`supported_adapters={"~onebot.v11"}`）。

## License

[MIT](./LICENSE)

> 维护模式：原项目已停止运营，本插件按 best-effort 维护，无 SLA。
