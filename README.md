<div align="center">

# nonebot-plugin-music-score-reactor

_✨ 用视觉模型识别音游成绩图并贴 QQ 表情 Reaction ✨_

[![LICENSE](https://img.shields.io/github/license/MortisBot/nonebot-plugin-music-score-reactor.svg)](./LICENSE)
[![pypi](https://img.shields.io/pypi/v/nonebot-plugin-music-score-reactor.svg)](https://pypi.python.org/pypi/nonebot-plugin-music-score-reactor)
![python](https://img.shields.io/badge/python-3.10+-blue.svg)

</div>

## 📖 介绍

收到群图片时，调用**你自己配置的** OpenAI 兼容视觉 API 判断是否为音游成绩结算图；命中后通过 NapCat 的 `set_msg_emoji_like` 给原消息贴一个 QQ 表情，不发送文字。另带随机贴表情、跟随贴表情、频数学习三个可选能力。

## 💿 安装

<details open>
<summary>使用 nb-cli 安装</summary>

在 NoneBot2 项目根目录下执行：

```bash
nb plugin install nonebot-plugin-music-score-reactor --upgrade
```

国内网络可换镜像源：

```bash
nb plugin install nonebot-plugin-music-score-reactor --upgrade -i "https://pypi.tuna.tsinghua.edu.cn/simple"
```

</details>

<details>
<summary>使用包管理器安装</summary>

在 NoneBot2 项目根目录下执行其一：

```bash
uv add nonebot-plugin-music-score-reactor
# 或
pdm add nonebot-plugin-music-score-reactor
# 或
poetry add nonebot-plugin-music-score-reactor
```

直接装仓库主分支（PyPI 包发布前可用）：

```bash
uv add git+https://github.com/MortisBot/nonebot-plugin-music-score-reactor@main
```

然后在 `pyproject.toml` 的 `[tool.nonebot]` 中追加：

```toml
plugins = ["nonebot_plugin_music_score_reactor"]
```

</details>

## ⚙️ 配置

在 NoneBot2 项目的 `.env` 中配置（配置项即环境变量名，大写）：

| 配置项 | 必填 | 默认值 | 说明 |
|:---:|:---:|:---:|:---|
| `MUSIC_SCORE_ENABLED` | 是 | `false` | 总开关 |
| `MUSIC_SCORE_GROUPS` | 是 | 空 | 生效群号，逗号分隔（空 = 不生效） |
| `MUSIC_SCORE_VISION_BASE_URL` | 是 | 空 | OpenAI 兼容视觉 API 地址 |
| `MUSIC_SCORE_VISION_API_KEY` | 是 | 空 | API Key |
| `MUSIC_SCORE_VISION_MODEL` | 否 | 无 | 模型名 |
| `MUSIC_SCORE_REACTION_EMOJI_ID` | 否 | `297` | 贴的表情 ID |
| `MUSIC_SCORE_RANDOM_ENABLED` | 否 | `false` | 随机贴表情 |
| `MUSIC_SCORE_FOLLOW_ENABLED` | 否 | `false` | 跟随别人贴表情 |
| `MUSIC_SCORE_RATE_LIMIT_PER_MIN` | 否 | `10` | 每分钟最多识别图片数 |

## 🎉 使用

无需命令，自动生效（默认关闭）：

1. 配置 `MUSIC_SCORE_ENABLED=true`、`MUSIC_SCORE_GROUPS` 与视觉 API；
2. 群里发图 → 视觉模型判断 → 命中则给原消息贴表情。

> 开启后群内图片会发送到你配置的第三方 API，请自行评估隐私与合规。

## 🔌 适配器

OneBot v11（`supported_adapters={"~onebot.v11"}`）。贴表情依赖 NapCat 扩展 `set_msg_emoji_like`。

## 📄 License

[MIT](./LICENSE) · 维护模式（best-effort，无 SLA）
